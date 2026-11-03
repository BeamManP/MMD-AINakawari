"""ポーズ用の小物: 先を半球で丸めた縦の円柱を DirectX .x（MMD のアクセサリ）で書く。座標は MMD の単位で、そのまま置ける位置に焼き込む。

MMD はアクセサリの .x を 10 倍で読み込むので、ファイルには 1/10 で書く（11-03、最初の版が 10 倍の遠くに置かれて見えなかった）。
使い方: python make_pole.py 出力.x 中心X 下端Y 上端Y 中心Z 半径   （どれも MMD の単位）
"""
X_SCALE = 0.1   # MMD の単位 → .x の単位
import math
import sys


def make(path, cx, y0, y1, cz, r, seg=24, cap_rings=6, color=(0.95, 0.72, 0.62)):
    cx, y0, y1, cz, r = (v * X_SCALE for v in (cx, y0, y1, cz, r))
    verts, faces = [], []
    body_top = y1 - r
    # 胴体の輪: 下端と、半球の付け根
    for y in (y0, body_top):
        for k in range(seg):
            a = 2 * math.pi * k / seg
            verts.append((cx + r * math.cos(a), y, cz + r * math.sin(a)))
    # 半球の輪
    for i in range(1, cap_rings):
        t = (math.pi / 2) * i / cap_rings
        rr, yy = r * math.cos(t), body_top + r * math.sin(t)
        for k in range(seg):
            a = 2 * math.pi * k / seg
            verts.append((cx + rr * math.cos(a), yy, cz + rr * math.sin(a)))
    top = len(verts); verts.append((cx, y1, cz))
    bottom = len(verts); verts.append((cx, y0, cz))
    rings = 1 + cap_rings          # 輪の数（下端・付け根・半球の輪）
    for ring in range(rings - 1):
        for k in range(seg):
            a, b = ring * seg + k, ring * seg + (k + 1) % seg
            c, d = a + seg, b + seg
            faces += [(a, c, b), (b, c, d)]
    last = (rings - 1) * seg
    for k in range(seg):
        faces.append((last + k, top, last + (k + 1) % seg))
        faces.append((k, (k + 1) % seg, bottom))
    faces += [(a, c, b) for (a, b, c) in faces]   # 裏表どちらからも見えるように両面にする（片面だと裏表を取り違えると消える）
    # 法線は頂点ごとに（中心軸からの向き。半球は中心からの向き）
    normals = []
    for (x, y, z) in verts:
        if y > body_top + 1e-6:
            v = (x - cx, y - body_top, z - cz)
        elif abs(y - y0) < 1e-9 and abs(x - cx) < 1e-9 and abs(z - cz) < 1e-9:
            v = (0, -1, 0)
        else:
            v = (x - cx, 0, z - cz)
        n = math.sqrt(sum(c * c for c in v)) or 1
        normals.append(tuple(c / n for c in v))
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("xof 0302txt 0064\n\nHeader{\n1;\n0;\n1;\n}\n\nMesh {\n")   # MMD 付属のアクセサリと同じ書き出し
        f.write(f" {len(verts)};\n" + ",\n".join(f" {x:.5f};{y:.5f};{z:.5f};" for x, y, z in verts) + ";\n")
        f.write(f" {len(faces)};\n" + ",\n".join(f" 3;{a},{b},{c};" for a, b, c in faces) + ";\n")
        f.write(" MeshMaterialList {\n  1;\n  %d;\n  " % len(faces) + ",".join("0" for _ in faces) + ";;\n")   # 付属のものと同じく ;; で閉じる
        f.write("  Material {\n   %.3f;%.3f;%.3f;1.000;;\n   10.000;\n   0.200;0.200;0.200;;\n   %.3f;%.3f;%.3f;;\n  }\n }\n"
                % (color[0], color[1], color[2], color[0] * 0.35, color[1] * 0.35, color[2] * 0.35))
        f.write(" MeshNormals {\n")
        f.write(f"  {len(normals)};\n" + ",\n".join(f"  {x:.5f};{y:.5f};{z:.5f};" for x, y, z in normals) + ";\n")
        f.write(f"  {len(faces)};\n" + ",\n".join(f"  3;{a},{b},{c};" for a, b, c in faces) + ";\n }\n}\n")
    print(f"書いた {path}: 頂点 {len(verts)}・面 {len(faces)}")


if __name__ == "__main__":
    a = sys.argv
    make(a[1], float(a[2]), float(a[3]), float(a[4]), float(a[5]), float(a[6]))
