# -*- coding: utf-8 -*-
"""
Ball Map Generator
  - in-line       : 격자 배열, 중심 행/열 비움 -> (0,0)에 볼 없음
  - staggered-XX  : 지그재그 배열, pitch = 최근접 볼 중심거리 -> (0,0)에 볼 있음

좌표 생성 로직만 담고 있어 GUI 없이도 CLI 로 쓸 수 있다.
  python -m tools.ball_map.core --pitch 0.4 --px 20 --py 20
"""

import math
import argparse

_TOL = 1e-9


# ============================================================
#  in-line
# ============================================================
def _axis_n(length, pitch, margin):
    """1축 방향 볼 개수. 중심선에 볼이 놓이지 않도록 짝수로 강제."""
    usable = length - 2.0 * margin
    if usable < 0.0:
        return 0
    n = int(math.floor(usable / pitch + _TOL)) + 1
    if n % 2 == 1:
        n -= 1
    return n if n >= 2 else 0


def _axis_coords(length, pitch, margin):
    """1축 방향 좌표 리스트. 중심 0 기준 대칭."""
    n = _axis_n(length, pitch, margin)
    if n == 0:
        return []
    start = -(n - 1) * pitch / 2.0
    return [start + i * pitch for i in range(n)]


def generate_inline(pitch, pkg_x, pkg_y, edge_margin=0.0):
    xs = _axis_coords(pkg_x, pitch, edge_margin)
    ys = _axis_coords(pkg_y, pitch, edge_margin)
    return [(x, y) for y in ys for x in xs]      # 아래 행부터 좌 -> 우


# ============================================================
#  staggered
# ============================================================
def _staggered_layout(pitch, angle_deg, len_along, len_across, margin, corner):
    """배열 파라미터만 계산 (좌표 생성 없음).

    a = 2*P*cos(theta) : 같은 행 내 볼 간격
    b =   P*sin(theta) : 행 간격
    imax : |k| 짝수 행(오프셋 0)의 최대 인덱스, -1 이면 볼 없음
    jmax : |k| 홀수 행(오프셋 a/2)의 최대 인덱스, -1 이면 볼 없음
    kmax : 최외곽 행 인덱스 (코너 볼 유무에 따라 1줄 조정됨)
    return (a, b, imax, jmax, kmax) 또는 None
    """
    th = math.radians(angle_deg)
    a = 2.0 * pitch * math.cos(th)
    b = 1.0 * pitch * math.sin(th)
    if a <= _TOL or b <= _TOL:
        raise ValueError("angle은 0도 초과, 90도 미만이어야 합니다.")

    half_u = len_along / 2.0 - margin
    half_v = len_across / 2.0 - margin
    if half_u < 0.0 or half_v < 0.0:
        return None

    imax = int(math.floor(half_u / a + _TOL))
    jmax = int(math.floor((half_u - a / 2.0) / a + _TOL))
    x_even = imax * a if imax >= 0 else -1.0
    x_odd = (a / 2.0 + jmax * a) if jmax >= 0 else -1.0
    if x_even < 0.0 and x_odd < 0.0:
        return None

    # 최외곽 x에 도달하는 행의 |k| 패리티. 요청한 코너 상태와 다르면 한 줄 제거.
    edge_parity = 0 if x_even > x_odd else 1
    kmax = int(math.floor(half_v / b + _TOL))
    if kmax > 0 and ((kmax % 2 == edge_parity) != bool(corner)):
        kmax -= 1

    return (a, b, imax, jmax, kmax)


def _staggered_rows(pitch, angle_deg, len_along, len_across, margin, corner=True):
    """행이 'along' 축 방향으로 놓인 staggered 배열의 (u, v) 좌표."""
    lay = _staggered_layout(pitch, angle_deg, len_along, len_across, margin, corner)
    if lay is None:
        return []
    a, b, imax, jmax, kmax = lay

    # 두 종류의 행 템플릿만 만들고 y만 바꿔 재사용
    us_even = [i * a for i in range(-imax, imax + 1)] if imax >= 0 else []
    us_odd = []
    if jmax >= 0:
        us_odd = [-(a / 2.0 + j * a) for j in range(jmax, -1, -1)]
        us_odd.extend(a / 2.0 + j * a for j in range(jmax + 1))

    pts = []
    for k in range(-kmax, kmax + 1):
        v = k * b
        us = us_even if abs(k) % 2 == 0 else us_odd
        pts.extend([(u, v) for u in us])
    return pts                       # 이미 (v 오름차순, u 오름차순) 정렬 상태


def generate_staggered(pitch, angle_deg, pkg_x, pkg_y, edge_margin=0.0,
                       axis="x", corner=True):
    """axis='x' : 행이 x방향(각도는 x축 기준) / axis='y' : 열이 y방향"""
    ax = axis.strip().lower()
    if ax == "x":
        return _staggered_rows(pitch, angle_deg, pkg_x, pkg_y, edge_margin, corner)
    if ax == "y":
        pts = [(v, u) for (u, v) in
               _staggered_rows(pitch, angle_deg, pkg_y, pkg_x, edge_margin, corner)]
        pts.sort(key=lambda p: (p[1], p[0]))
        return pts
    raise ValueError("axis는 'x' 또는 'y' 여야 합니다.")


# ============================================================
#  공통 인터페이스
# ============================================================
def _parse_type(array_type):
    """'in-line' 또는 'staggered-45' 파싱 -> (kind, angle)"""
    t = array_type.strip().lower().replace("_", "-").replace(" ", "")
    if t in ("inline", "in-line", "grid"):
        return ("inline", None)
    for key in ("staggered-", "stagger-", "stg-"):
        if t.startswith(key):
            return ("staggered", float(t[len(key):].replace("deg", "").replace("도", "")))
    raise NotImplementedError("'%s' 타입은 인식할 수 없습니다." % array_type)


def generate_ballmap(array_type, pitch, pkg_x, pkg_y, edge_margin=0.0,
                     axis="x", corner=True):
    kind, angle = _parse_type(array_type)
    if kind == "inline":
        return generate_inline(pitch, pkg_x, pkg_y, edge_margin)
    return generate_staggered(pitch, angle, pkg_x, pkg_y, edge_margin, axis, corner)


def estimate_count(array_type, pitch, pkg_x, pkg_y, edge_margin=0.0,
                   axis="x", corner=True):
    """좌표를 만들지 않고 볼 개수만 계산 (입력 크기와 무관하게 즉시 반환)."""
    kind, angle = _parse_type(array_type)
    if kind == "inline":
        return _axis_n(pkg_x, pitch, edge_margin) * _axis_n(pkg_y, pitch, edge_margin)

    if axis.strip().lower() == "x":
        len_along, len_across = pkg_x, pkg_y
    else:
        len_along, len_across = pkg_y, pkg_x

    lay = _staggered_layout(pitch, angle, len_along, len_across, edge_margin, corner)
    if lay is None:
        return 0
    _, _, imax, jmax, kmax = lay
    n_even = (2 * imax + 1) if imax >= 0 else 0
    n_odd = (2 * (jmax + 1)) if jmax >= 0 else 0
    n_row_even = 2 * (kmax // 2) + 1
    n_row_odd = 2 * ((kmax + 1) // 2)
    return n_row_even * n_even + n_row_odd * n_odd


def write_indexed_txt(coords, path, decimals=4):
    """첫 줄 헤더 '0,1,2', 이후 1부터 시작하는 인덱스 + x + y 의 3열."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("0,1,2\n")
        for i, (x, y) in enumerate(coords, start=1):
            f.write("{0},{1:.{3}f},{2:.{3}f}\n".format(i, x, y, decimals))


# ============================================================
#  CLI
# ============================================================
def _cli():
    ap = argparse.ArgumentParser(description="Ball map generator")
    ap.add_argument("--type", default="in-line",
                    help="in-line | staggered-30 | staggered-45 | staggered-60")
    ap.add_argument("--pitch", type=float, required=True)
    ap.add_argument("--px", type=float, required=True, help="pkg X size")
    ap.add_argument("--py", type=float, required=True, help="pkg Y size")
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--axis", default="x", choices=["x", "y"])
    ap.add_argument("--corner", default="on", choices=["on", "off"])
    ap.add_argument("--dec", type=int, default=4)
    ap.add_argument("--out", default="ballmap.txt")
    args = ap.parse_args()

    corner = (args.corner == "on")
    n = estimate_count(args.type, args.pitch, args.px, args.py,
                       args.margin, args.axis, corner)
    print("예상 볼 개수: {:,}".format(n))

    pts = generate_ballmap(args.type, args.pitch, args.px, args.py,
                           args.margin, args.axis, corner)
    write_indexed_txt(pts, args.out, decimals=args.dec)
    print("type=%s, pitch=%g, pkg=%gx%g -> %d balls -> %s"
          % (args.type, args.pitch, args.px, args.py, len(pts), args.out))


if __name__ == "__main__":
    _cli()
