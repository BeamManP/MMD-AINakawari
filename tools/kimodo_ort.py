"""Kimodo の重い計算（2 つの Transformer）を ONNX Runtime で動かす（Kimodo の Python で動かす）。

Kimodo は PyTorch のモデルで、Windows の PyTorch が GPU を使えるのは NVIDIA（CUDA）だけ。
CPU の PyTorch だけだと 67 フレームで約 40 秒・300 フレームで 2〜4 分かかる（11-10・i7-12700F）。
時間のほとんどは、ノイズ除去 1 回ごとに 2 回呼ばれる Transformer（腰用 root_model・体用 body_model。各 16 層・約 1.4 億個の重み）なので、
この 2 つだけを ONNX に書き出して ONNX Runtime で動かす:
    DirectML … DirectX 12 の GPU（NVIDIA・AMD・Intel）    CPU … GPU なし
100 回のループ・キーの条件・プロンプトの効き（CFG）・後処理は、Kimodo の PyTorch のコードのまま CPU で動く（軽い）。

使い方: Kimodo のモデルを device="cpu" で読んでから install(model, provider, cache_dir)。
書き出した ONNX は cache_dir に置く（1 つ約 570MB。モデルの重みと同じ物なので、配らずにその PC で作る）。
"""
import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

PROVIDERS = {"directml": "DmlExecutionProvider", "cpu": "CPUExecutionProvider"}
EXPORT = 3      # 書き出し方の版（変えたら作り直す）
OPSET = 17
BLOCKS = ("root_model", "body_model")
INPUTS = ("x", "text_feat", "timesteps", "first_heading_angle")
SESSIONS_KEPT = 2   # 形（フレーム数）ごとに開いた物を、いくつ覚えておくか


class _Exportable(nn.Module):
    """TransformerEncoderBlock.forward と同じ計算を、マスク無しで行う（書き出し用）。

    元の forward は「使わない所」のマスクを Transformer に渡す。その経路を ONNX に書き出すと、書き出した時のフレーム数が
    形として焼き付き、違うフレーム数で落ちる（11-10・Reshape で確かめた）。AIナカワリは 1 回に 1 本だけ作るので
    マスクは常に「全部使う」。だからマスクを渡さずに同じ結果になる（export_blocks が書き出す前に検算する）。
    """

    def __init__(self, block):
        super().__init__()
        if block.use_text_mask or not block.input_first_heading_angle or block.num_text_tokens is None:
            raise RuntimeError("このモデルの設定（文のマスク・最初の向き）には、書き出しが対応していません")
        layer = block.seqTransEncoder.layers[0]
        if block.norm_first or not layer.self_attn.batch_first or not layer.self_attn._qkv_same_embed_dim:
            raise RuntimeError("このモデルの Transformer の形（先に正規化など）には、書き出しが対応していません")
        self.block = block

    def forward(self, x, text_feat, timesteps, first_heading_angle):
        b = self.block
        x = b.input_linear(x)
        pad = b.num_text_tokens - text_feat.shape[1]   # 文の並びを決まった個数まで 0 で埋める（pad_x_and_mask_to_fixed_size と同じ）
        if pad > 0:
            text_feat = torch.cat((text_feat, torch.zeros_like(text_feat[:, :1]).expand(-1, pad, -1)), dim=1)
        emb_text = b.embed_text(text_feat)
        emb_time = b.embed_timestep(timesteps)
        heading = b.linear_first_heading_angle(torch.stack([torch.cos(first_heading_angle), torch.sin(first_heading_angle)], dim=-1))
        prefix = torch.cat((emb_text, emb_time, heading[:, None]), dim=1)
        xseq = b.sequence_pos_encoder(torch.cat((prefix, x), dim=1))
        out = self._encoder(xseq)
        return b.output_linear(out[:, prefix.shape[1]:])

    def _encoder(self, x):
        """nn.TransformerEncoder（後ろで正規化・batch_first）と同じ計算を、同じ重みで書き下す。

        nn.MultiheadAttention をそのまま書き出すと、中の view に書き出した時の「長さ」「人数×ヘッド数」が数字で焼き付く
        （11-10・76×24×128 で固定された）。ここでは形を数字で指定せず、最後の次元をヘッドに割るだけにする。
        掛け算は全部 4 次元（[人数, ヘッド, 長さ, …]）なので DirectML もそのまま受ける。
        """
        encoder = self.block.seqTransEncoder
        for layer in encoder.layers:
            attn = layer.self_attn
            heads = attn.num_heads
            head_dim = attn.embed_dim // heads
            q, k, v = F.linear(x, attn.in_proj_weight, attn.in_proj_bias).chunk(3, dim=-1)
            q = q.unflatten(-1, (heads, head_dim)).transpose(1, 2)   # [人数, ヘッド, 長さ, head_dim]
            k = k.unflatten(-1, (heads, head_dim)).transpose(1, 2)
            v = v.unflatten(-1, (heads, head_dim)).transpose(1, 2)
            weights = torch.softmax(torch.matmul(q, k.transpose(-1, -2)) * (head_dim ** -0.5), dim=-1)
            mixed = torch.matmul(weights, v).transpose(1, 2).flatten(-2)   # [人数, 長さ, embed_dim]
            x = layer.norm1(x + attn.out_proj(mixed))
            x = layer.norm2(x + layer.linear2(layer.activation(layer.linear1(x))))
        return x if encoder.norm is None else encoder.norm(x)


def _check_same(block, exportable, text_tokens):
    """マスク無しの計算が、元の forward と同じ結果か（書き出した時と違うフレーム数・乱数の入力で）。

    倍精度で比べる。単精度だと、元の計算どうしでも丸めの差が 1e-3 ほど出る（体用・16 層。11-10）ので、違いと見分けられない。
    倍精度なら同じ計算は差 0 になる。重みは単精度 → 倍精度 → 単精度で元どおりに戻る。
    """
    gen = torch.Generator().manual_seed(0)
    batch, frames = 3, 37
    x = torch.randn(batch, frames, block.input_dim, generator=gen, dtype=torch.float64)
    text = torch.randn(batch, text_tokens, int(block.llm_shape[-1]), generator=gen, dtype=torch.float64)
    t = torch.tensor([3, 40, 77])
    heading = torch.randn(batch, generator=gen, dtype=torch.float64)
    block.double()
    try:
        with torch.no_grad():
            ref = block(x, torch.ones(batch, frames, dtype=torch.bool), text, torch.ones(batch, text_tokens, dtype=torch.bool), t, heading)
            got = exportable(x, text, t, heading)
    finally:
        block.float()
    diff = float((ref - got).abs().max())
    if not diff < 1e-9:
        raise RuntimeError(f"書き出し用の計算が元と合いません（倍精度での差 {diff}）")
    return diff


def _stamp(model, name):
    """書き出した物が今のモデルの物かを見分ける印（重みの個数と、いくつかの重みの合計）。"""
    block = getattr(model.denoiser.model, name)
    params = list(block.parameters())
    return {"export": EXPORT, "opset": OPSET, "torch": torch.__version__, "count": int(sum(p.numel() for p in params)),
            "probe": [round(float(p.detach().double().sum()), 6) for p in params[:4]]}


def export_blocks(model, cache_dir, log=print):
    """2 つの Transformer を ONNX に書き出す（もうあれば何もしない）。{名前: ONNX の場所} を返す。"""
    os.makedirs(cache_dir, exist_ok=True)
    denoiser = model.denoiser.model
    paths = {}
    for name in BLOCKS:
        block = getattr(denoiser, name)
        if isinstance(block, OrtBlock):
            raise RuntimeError("install 済みのモデルからは書き出せません")
        path = os.path.join(cache_dir, f"kimodo_{name}.onnx")
        stamp_file = path + ".json"
        stamp = _stamp(model, name)
        paths[name] = path
        try:
            if os.path.isfile(path) and json.load(open(stamp_file, encoding="utf-8")) == stamp:
                continue
        except (OSError, ValueError):
            pass
        t0 = time.time()
        frames, batch = 24, 3
        text_tokens, llm_dim = int(block.llm_shape[0]), int(block.llm_shape[-1])
        was_training = block.training
        block.eval()
        exportable = _Exportable(block)
        diff = _check_same(block, exportable, text_tokens)
        args = (torch.zeros(batch, frames, block.input_dim), torch.zeros(batch, text_tokens, llm_dim),
                torch.zeros(batch, dtype=torch.long), torch.zeros(batch))
        tmp = path + ".tmp"
        try:
            with torch.no_grad():
                torch.onnx.export(
                    exportable, args, tmp, input_names=list(INPUTS), output_names=["out"], opset_version=OPSET, dynamo=False,
                    dynamic_axes={"x": {0: "batch", 1: "frames"}, "text_feat": {0: "batch"}, "timesteps": {0: "batch"},
                                  "first_heading_angle": {0: "batch"}, "out": {0: "batch", 1: "frames"}})
        finally:
            block.train(was_training)
        os.replace(tmp, path)
        with open(stamp_file, "w", encoding="utf-8") as f:
            json.dump(stamp, f)
        log(f"kimodo onnx exported: {name} {os.path.getsize(path) / 2**20:.0f}MB {time.time() - t0:.1f}s（元の計算との差 {diff:.1e}）")
    return paths


class OrtBlock(nn.Module):
    """TransformerEncoderBlock の代わり。同じ引数で呼ばれ、ONNX Runtime で計算して torch のテンソルで返す。"""

    def __init__(self, onnx_path, provider, text_tokens):
        super().__init__()
        import onnxruntime as ort

        if provider not in PROVIDERS:
            raise ValueError(f"provider は {sorted(PROVIDERS)} のどれか（{provider!r}）")
        if PROVIDERS[provider] not in ort.get_available_providers():
            raise RuntimeError(f"この ONNX Runtime では {PROVIDERS[provider]} が使えません（使える物: {ort.get_available_providers()}）")
        self._ort = ort
        self.onnx_path = onnx_path
        self.provider = provider
        self.text_tokens = text_tokens
        self._sessions = {}   # (batch, frames) → (session, 入力の名前)。新しい順
        self.seconds = 0.0    # ONNX Runtime の中にいた時間（測る用）
        self.calls = 0

    def _session(self, batch, frames):
        key = (batch, frames)
        if key in self._sessions:
            self._sessions[key] = self._sessions.pop(key)   # 一番新しい所へ
            return self._sessions[key]
        ort = self._ort
        options = ort.SessionOptions()
        options.add_free_dimension_override_by_name("batch", batch)   # 形を全部決める（DirectML は決まっている方が速い）
        options.add_free_dimension_override_by_name("frames", frames)
        if self.provider == "directml":   # DirectML の決まり（メモリの使い回しを切る・順に実行）
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = [PROVIDERS[self.provider]] + (["CPUExecutionProvider"] if self.provider != "cpu" else [])
        session = ort.InferenceSession(self.onnx_path, options, providers=providers)
        if session.get_providers()[0] != PROVIDERS[self.provider]:   # 開けないと黙って CPU になるので、確かめる
            raise RuntimeError(f"{PROVIDERS[self.provider]} で開けませんでした（開いたのは {session.get_providers()}）")
        while len(self._sessions) >= SESSIONS_KEPT:
            self._sessions.pop(next(iter(self._sessions)))
        self._sessions[key] = (session, [i.name for i in session.get_inputs()])
        return self._sessions[key]

    def forward(self, x, x_pad_mask, text_feat, text_feat_pad_mask, timesteps, first_heading_angle=None):
        if first_heading_angle is None:
            raise ValueError("first_heading_angle が要ります")
        if text_feat.shape[1] != self.text_tokens:
            raise ValueError(f"text_feat は {self.text_tokens} 個の並びのはず（{tuple(text_feat.shape)}）")
        if not bool(x_pad_mask.all()):   # 書き出した計算はマスク無し（_Exportable）
            raise ValueError("長さの違う動きをまとめて作るのには対応していません（x_pad_mask に False があります）")
        session, names = self._session(int(x.shape[0]), int(x.shape[1]))
        values = {"x": x.detach().cpu().numpy().astype(np.float32, copy=False),
                  "text_feat": text_feat.detach().cpu().numpy().astype(np.float32, copy=False),
                  "timesteps": timesteps.detach().cpu().numpy().astype(np.int64, copy=False),
                  "first_heading_angle": first_heading_angle.detach().cpu().numpy().astype(np.float32, copy=False)}
        t0 = time.perf_counter()
        out = session.run(["out"], {n: values[n] for n in names})[0]   # 書き出しで使われなかった入力は ONNX に無い
        self.seconds += time.perf_counter() - t0
        self.calls += 1
        return torch.from_numpy(out).to(device=x.device, dtype=x.dtype)

    def release(self):
        self._sessions.clear()


def install(model, provider, cache_dir, log=print):
    """model（device="cpu" で読んだ Kimodo）の 2 つの Transformer を ONNX Runtime の物に差し替える。"""
    if str(model.device) != "cpu":
        raise ValueError(f"Kimodo は device='cpu' で読んでください（{model.device}）")
    paths = export_blocks(model, cache_dir, log)
    denoiser = model.denoiser.model
    for name in BLOCKS:
        block = getattr(denoiser, name)
        setattr(denoiser, name, OrtBlock(paths[name], provider, int(block.llm_shape[0])))   # 元の重みはここで手放す
    return model
