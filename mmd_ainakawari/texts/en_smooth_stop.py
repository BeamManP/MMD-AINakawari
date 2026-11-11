"""smooth_stop.py（なめらかに止まる）と nakawari.py の共通の文の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "MotionBricks がまだ入っていません。「なめらかに止まる」を外すか、詳細の窓の「セットアップ」で入れてください":
        "MotionBricks is not installed yet. Turn off Smooth stop, or install it with Setup in the details window",
    "  キーの手前の腰の速さ {approach:.2f} m/s（{min_speed} 未満）なので、止まり方は Kimodo のままにします":
        "  The hip speed before the key is {approach:.2f} m/s (under {min_speed}), so the stopping is left to Kimodo",
    "  キーの手前の目印まで {limit} フレームしかない（MotionBricks は {min_len} フレームから）ので、止まり方は Kimodo のままにします":
        "  Only {limit} frames before the previous marker (MotionBricks needs {min_len} or more), so the stopping is left to Kimodo",
    "  止まり方を MotionBricks で作り直しました: {a}〜{stop}F（{L} フレーム・候補 {n} 通りから）・一番強い減速 {base_dec:.1f} → {dec:.1f} m/s²・加速 {base_acc:.1f} → {acc:.1f} m/s²（{sec:.1f} 秒）":
        "  Redid the stopping with MotionBricks: {a}-{stop}F ({L} frames, from {n} candidates), "
        "peak deceleration {base_dec:.1f} -> {dec:.1f} m/s², acceleration {base_acc:.1f} -> {acc:.1f} m/s² ({sec:.1f} s)",
    "・床に沈んだ足を最大 {cm:.1f}cm 持ち上げ": ", lifted sunken feet by up to {cm:.1f}cm",
}
