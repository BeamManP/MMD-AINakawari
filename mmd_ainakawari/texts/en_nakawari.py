"""nakawari.py（MotionBricks で中割り）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "MotionBricks が入っていません。詳細の窓のセットアップで MotionBricks を入れてください":
        "MotionBricks is not installed. Install it with Setup in the details window",
    "中割りには体のキーが 2 つ以上要ります": "In-between needs at least 2 body keys",
    "  中割りに使うのは体のキーです（全ての親だけ・手足の IK だけのキーは対象外）":
        "  Only body keys are used for in-between (keys on the master bone alone or on limb IK alone are ignored)",
    "キーの間が {lo}〜{hi} フレームの所がありません": "No gap between keys is {lo}-{hi} frames long",
    "  MotionBricks で {runs} 回・{done} フレームを作りました（{sec:.1f} 秒・{stop}・手首は{wrist}）":
        "  Created {done} frames in {runs} runs with MotionBricks ({sec:.1f} s, {stop}, wrists: {wrist})",
    "  {a}〜{b}F は {gap} フレーム（MotionBricks は {lo}〜{hi}）なので、MMD の補間のままにします":
        "  {a}-{b}F is {gap} frames (MotionBricks handles {lo}-{hi}), so MMD's interpolation is kept",
    "キーごとに止まる": "stops at each key",
    "キーを通る": "passes through the keys",
    "補間": "interpolated",
    " MotionBricks のまま": "as MotionBricks made them",
}
