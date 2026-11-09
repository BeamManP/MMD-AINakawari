"""MotionBricks を ONNX Runtime で動かす（TensorRT の代わり。MotionBricks の Python で動かす）。

MotionBricks の公式のエンジンは TensorRT（NVIDIA の GPU だけ・GPU ごとに初回の準備が数分）で動く。
モデルそのものは ONNX なので、推論のところだけを ONNX Runtime に差し替える:
    DirectML … DirectX 12 の GPU（NVIDIA・AMD・Intel）    CPU … GPU なし
前後の計算（姿勢の詰め替え・端の合わせ込み）は公式の Warp のカーネルをそのまま CPU で動かす（1 回に 8 姿勢 × 77 関節と小さい）。

公式のコードは書き換えない。motionbricks.inference.engine.InferenceEngine（TensorRT を呼ぶ所）の口を、
MotionBricksSOMAEngine の子クラスで全部上書きする。tensorrt が入っていなくても読めるように、空の tensorrt を先に置く
（このファイルを motionbricks より先に import すること）。
"""
import contextlib
import sys
import time
import types
from types import MappingProxyType


def _stub_tensorrt():
    """空の tensorrt を置く。motionbricks.inference.builder が import の時に触る名前だけ持たせる（中身は呼ばれない）。"""
    stub = types.ModuleType("tensorrt")
    stub.__version__ = "0 (AINakawari: ONNX Runtime で動かすので使わない)"

    class ILogger:
        Severity = int

        def __init__(self):
            pass

    class Logger:
        INTERNAL_ERROR, ERROR, WARNING, INFO, VERBOSE = range(5)

    stub.ILogger, stub.Logger = ILogger, Logger
    sys.modules["tensorrt"] = stub


_stub_tensorrt()

import numpy as np   # noqa: E402
import onnxruntime as ort   # noqa: E402
import warp as wp   # noqa: E402

from motionbricks.inference.types import TensorMode   # noqa: E402
from motionbricks.model.soma.engine import MotionBricksSOMAEngine   # noqa: E402

PROVIDERS = {"directml": "DmlExecutionProvider", "cpu": "CPUExecutionProvider"}
# DirectML は何も言わないと 1 番目の GPU を使う（ノート PC では内蔵の GPU のことが多い）。性能の高い GPU を選ばせる
DML_OPTIONS = {"performance_preference": "high_performance", "device_filter": "gpu"}
BATCH_DIM = "batch_size"   # ONNX の入出力の先頭の次元の名前。MotionBricks は 1 で使う
DML_PATCH = 1              # directml_model の手直しの版（変えたら作り直す）


def directml_model(onnx_path, cache_dir):
    """DirectML が受けられる形に手直しした ONNX の場所（無ければ作る。モデルの重みは変えない）。

    DirectML の MatMul は 4 次元まで。このモデルには 5 次元の MatMul（[1, 姿勢, 30 関節, 3, 3] の回転行列）が 4 個あり、
    そのままだと「パラメーターが間違っています」（80070057）で落ちる（11-10 に確かめた）。
    先頭の 1 を Squeeze で外して掛け、Unsqueeze で戻す。どの MatMul が 5 次元かは、CPU で 1 回動かして実際の形を見て決める。
    """
    import json
    import os

    src = os.path.abspath(str(onnx_path))
    stat = os.stat(src)
    stamp = {"source": src, "size": stat.st_size, "mtime": stat.st_mtime, "patch": DML_PATCH}
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, os.path.splitext(os.path.basename(src))[0] + ".directml.onnx")
    stamp_file = out + ".json"
    try:
        if os.path.isfile(out) and json.load(open(stamp_file, encoding="utf-8")) == stamp:
            return out
    except (OSError, ValueError):
        pass

    import onnx
    from onnx import helper, numpy_helper

    model = onnx.load(src)
    matmuls = [n for n in model.graph.node if n.op_type == "MatMul"]
    initializers = {i.name: len(i.dims) for i in model.graph.initializer}
    # 形を見る用: MatMul の入力を全部出力に足して、CPU で 1 回動かす（入力は 0。形は入力の中身によらない）
    probe = onnx.ModelProto()
    probe.CopyFrom(model)
    watched = list(dict.fromkeys(x for n in matmuls for x in n.input if x not in initializers))
    probe.graph.output.extend(onnx.ValueInfoProto(name=x) for x in watched)
    options = ort.SessionOptions()
    options.add_free_dimension_override_by_name(BATCH_DIM, 1)
    session = ort.InferenceSession(probe.SerializeToString(), options, providers=["CPUExecutionProvider"])
    feeds = {}
    for i in session.get_inputs():
        if any(not isinstance(d, int) for d in i.shape):
            raise RuntimeError(f"ONNX の入力 {i.name} の形が決まりません（{i.shape}）")
        feeds[i.name] = np.zeros(i.shape, np.int32 if "int32" in i.type else np.float32)
    shapes = {o.name: v.shape for o, v in zip(session.get_outputs(), session.run(None, feeds))}
    del session, probe

    axis = "ainakawari_axis0"
    nodes, patched = [], []
    for n in model.graph.node:
        ranks = [len(shapes[x]) if x in shapes else initializers.get(x) for x in n.input] if n.op_type == "MatMul" else []
        if not any(r is not None and r > 4 for r in ranks):
            nodes.append(n)
            continue
        lead = [shapes[x][0] if x in shapes else None for x in n.input]
        if ranks != [5, 5] or lead != [1, 1]:
            raise RuntimeError(f"MatMul {n.name} は DirectML 用に直せない形です（{[shapes.get(x) for x in n.input]}）")
        tag = "ainakawari" + n.name.replace("/", "_")
        nodes += [helper.make_node("Squeeze", [n.input[0], axis], [tag + "_a"], name=tag + "_squeeze_a"),
                  helper.make_node("Squeeze", [n.input[1], axis], [tag + "_b"], name=tag + "_squeeze_b"),
                  helper.make_node("MatMul", [tag + "_a", tag + "_b"], [tag + "_out"], name=n.name),
                  helper.make_node("Unsqueeze", [tag + "_out", axis], [n.output[0]], name=tag + "_unsqueeze")]
        patched.append(n.name)
    if patched:
        model.graph.initializer.append(numpy_helper.from_array(np.array([0], np.int64), axis))
    del model.graph.node[:]
    model.graph.node.extend(nodes)
    tmp = out + ".tmp"
    onnx.save(model, tmp)
    os.replace(tmp, out)
    with open(stamp_file, "w", encoding="utf-8") as f:
        json.dump(stamp, f)
    print(f"directml model ready: {out}（MatMul {len(patched)} 個を 4 次元に: {patched}）", flush=True)
    return out


class _Timer:
    """公式の GenerationTimer（CUDA のイベントで測る）の代わり。段ごとの時間（ミリ秒）。"""

    def __init__(self):
        self.milliseconds = {}

    @contextlib.contextmanager
    def stage(self, name):
        t0 = time.perf_counter()
        yield
        self.milliseconds[name] = (time.perf_counter() - t0) * 1000

    def read(self):
        pass


class OrtSOMAEngine(MotionBricksSOMAEngine):
    """MotionBricksSOMAEngine の推論を ONNX Runtime で行う。入出力の置き場は Warp の CPU の配列（numpy と同じメモリ）。"""

    def __init__(self, onnx_path, provider="directml", model_to_runtime=None, cache_dir=".ort-cache"):
        """cache_dir は DirectML 用に手直しした ONNX の置き場（directml_model）。相対なら今のフォルダから。"""
        # 親の __init__（TensorRT のエンジンを作る）は呼ばない。親が持つはずの物を、ここで全部そろえる
        if provider not in PROVIDERS:
            raise ValueError(f"provider は {sorted(PROVIDERS)} のどれか（{provider!r}）")
        if PROVIDERS[provider] not in ort.get_available_providers():
            raise RuntimeError(f"この ONNX Runtime では {PROVIDERS[provider]} が使えません（使える物: {ort.get_available_providers()}）")
        wp.init()
        self._closed = False
        self._device = wp.get_device("cpu")
        self.provider = provider

        options = ort.SessionOptions()
        options.add_free_dimension_override_by_name(BATCH_DIM, 1)   # 形を全部決める（DirectML は 1 回 30ms → 10ms。11-10）
        if provider == "directml":   # DirectML の決まり（メモリの使い回しを切る・順に実行）
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            onnx_path = directml_model(onnx_path, cache_dir)
        providers = [("DmlExecutionProvider", DML_OPTIONS), "CPUExecutionProvider"] if provider == "directml" else ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(str(onnx_path), options, providers=providers)
        if self._session.get_providers()[0] != PROVIDERS[provider]:
            raise RuntimeError(f"{PROVIDERS[provider]} で開けませんでした（開いたのは {self._session.get_providers()}）")

        specs = {spec.name: spec for spec in self.contract.tensor_specs}
        self._inputs = [i.name for i in self._session.get_inputs()]
        self._outputs = [o.name for o in self._session.get_outputs()]
        expected_in = sorted(n for n, s in specs.items() if s.mode is TensorMode.INPUT)
        expected_out = sorted(n for n, s in specs.items() if s.mode is TensorMode.OUTPUT)
        if sorted(self._inputs) != expected_in or sorted(self._outputs) != expected_out:
            raise RuntimeError(f"ONNX の入出力がモデルの決まりと違います: 入力 {self._inputs}・出力 {self._outputs}")
        self._tensor_specs = MappingProxyType(specs)
        self._buffers = {name: wp.zeros(spec.shape, dtype=wp.dtype_from_numpy(spec.dtype), device=self._device)
                         for name, spec in specs.items()}
        self._views = {name: buffer.numpy() for name, buffer in self._buffers.items()}   # 同じメモリを numpy として見る
        for name, view in self._views.items():
            if not np.shares_memory(view, self._buffers[name].numpy()) or view.dtype != specs[name].dtype:
                raise RuntimeError(f"{name}: Warp の配列を numpy として共有できません")

        # ここから下は MotionBricksEngine.__init__ の後半と同じ
        self._use_cuda_graph = False
        self._model_to_runtime = wp.transform(model_to_runtime if model_to_runtime is not None else wp.transform_identity())
        self._runtime_to_model = wp.transform_inverse(self._model_to_runtime)
        self.timer = _Timer()
        self._alignment = wp.empty(1, dtype=wp.transform, device=self._device)
        self._generated_frame_count = wp.empty(1, dtype=wp.int32, device=self._device)
        self._initialize_pose_layout()

    @property
    def device(self):
        return self._device

    @property
    def stream(self):
        """CPU には stream が無い（Warp は stream=None を「今の stream」として扱う）。"""
        return None

    @property
    def tensor_specs(self):
        return self._tensor_specs

    @property
    def cuda_graph_baked(self):
        return False

    def device_tensor(self, name):
        self._ensure_open()
        try:
            return self._buffers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown engine tensor {name!r}.") from exc

    def enqueue_async(self):
        """1 回推論する（その場で終わるまで待つ）。結果は出力の置き場へ写す。"""
        self._ensure_open()
        results = self._session.run(self._outputs, {name: self._views[name] for name in self._inputs})
        for name, value in zip(self._outputs, results):
            view = self._views[name]
            if value.shape != view.shape or value.dtype != view.dtype:
                raise RuntimeError(f"{name}: 出力の形が違います（{value.shape} {value.dtype}、決まりは {view.shape} {view.dtype}）")
            np.copyto(view, value)

    def synchronize(self):
        self._ensure_open()

    def bake_cuda_graph(self):
        pass

    def close(self):
        if self._closed:
            return
        self._session = None
        self._buffers.clear()
        self._views.clear()
        self._closed = True
