"""四元数（x, y, z, w の numpy 配列）の計算。"""
import numpy as np

IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])


def mul(a, b):
    """a * b（b を先に回してから a）。"""
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return np.array([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ])


def inv(q):
    return np.array([-q[0], -q[1], -q[2], q[3]]) / np.dot(q, q)


def normalize(q):
    return q / np.linalg.norm(q)


def cross(a, b):
    """3 次元の外積。np.cross は配列向けの汎用の作りで、3 つの数 1 組だと 10 倍ほど遅い（11-04、書き戻しの計算の 7 割を占めていた）。"""
    ax, ay, az = a
    bx, by, bz = b
    return np.array([ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx])


def rotate(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.array([vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)])


def from_axis_angle(axis, angle):
    axis = np.asarray(axis, dtype=float)
    n = np.linalg.norm(axis)
    if n < 1e-12:
        return IDENTITY.copy()
    s = np.sin(angle / 2) / n
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, np.cos(angle / 2)])


def to_axis_angle(q):
    q = normalize(q)
    if q[3] < 0:
        q = -q
    angle = 2 * np.arccos(np.clip(q[3], -1, 1))
    s = np.sqrt(max(1 - q[3] * q[3], 0))
    axis = q[:3] / s if s > 1e-9 else np.array([1.0, 0, 0])
    return axis, angle


def scale_angle(q, t):
    """同じ軸で角度だけ t 倍（付与の割合。負もあり）。"""
    axis, angle = to_axis_angle(q)
    return from_axis_angle(axis, angle * t)


def from_to(a, b):
    """向き a を向き b へ回す最小の回転。"""
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    d = np.dot(a, b)
    if d > 1 - 1e-9:
        return IDENTITY.copy()
    if d < -1 + 1e-9:
        ortho = np.cross(a, [1, 0, 0])
        if np.linalg.norm(ortho) < 1e-6:
            ortho = np.cross(a, [0, 1, 0])
        return from_axis_angle(ortho, np.pi)
    return normalize(np.array([*np.cross(a, b), 1 + d]))


def to_euler_xyz(q):
    """回転行列 R = Rx * Ry * Rz と見た時の (x, y, z) ラジアン。膝の制限に使う。"""
    m = to_matrix(q)
    y = np.arcsin(np.clip(m[0, 2], -1, 1))
    if abs(m[0, 2]) < 0.9999:
        x = np.arctan2(-m[1, 2], m[2, 2])
        z = np.arctan2(-m[0, 1], m[0, 0])
    else:
        x = np.arctan2(m[2, 1], m[1, 1])
        z = 0.0
    return np.array([x, y, z])


def from_euler_xyz(e):
    qx = from_axis_angle([1, 0, 0], e[0])
    qy = from_axis_angle([0, 1, 0], e[1])
    qz = from_axis_angle([0, 0, 1], e[2])
    return mul(mul(qx, qy), qz)


def to_matrix(q):
    x, y, z, w = normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def from_matrix(m):
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    return normalize(np.array(q))


def slerp(a, b, t):
    d = np.dot(a, b)
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        return normalize(a + t * (b - a))
    th = np.arccos(d)
    return (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / np.sin(th)
