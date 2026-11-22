"""smooth_stop.py（なめらかに止まる）と nakawari.py の共通の文の中国語（簡体字）の訳。用語は docs/中国語の用語.md。"""
TEXT = {
    "MotionBricks がまだ入っていません。「なめらかに止まる」を外すか、詳細の窓の「セットアップ」で入れてください":
        "尚未安装 MotionBricks。请取消“平滑停止”，或在详细窗口的“安装”中安装它",
    "  キーの手前の腰の速さ {approach:.2f} m/s（{min_speed} 未満）なので、止まり方は Kimodo のままにします":
        "  关键帧之前的腰部速度为 {approach:.2f} m/s（低于 {min_speed}），所以停止方式保持 Kimodo 的结果",
    "  キーの手前の目印まで {limit} フレームしかない（MotionBricks は {min_len} フレームから）ので、止まり方は Kimodo のままにします":
        "  距离关键帧之前的标记只有 {limit} 帧（MotionBricks 需要 {min_len} 帧以上），所以停止方式保持 Kimodo 的结果",
    "  止まり方を MotionBricks で作り直しました: {a}〜{stop}F（{L} フレーム・候補 {n} 通りから）・一番強い減速 {base_dec:.1f} → {dec:.1f} m/s²・加速 {base_acc:.1f} → {acc:.1f} m/s²（{sec:.1f} 秒）":
        "  已用 MotionBricks 重新生成停止方式：{a}～{stop}F（{L} 帧，从 {n} 个候选中选出）、最大减速度 {base_dec:.1f} → {dec:.1f} m/s²、加速度 {base_acc:.1f} → {acc:.1f} m/s²（{sec:.1f} 秒）",
    "・床に沈んだ足を最大 {cm:.1f}cm 持ち上げ": "、把陷入地面的脚最多抬高 {cm:.1f}cm",
}
