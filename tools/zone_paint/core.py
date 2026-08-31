# -*- coding: utf-8 -*-
"""zone_paint core ― 사각 드래그로 구역을 칠하고, 여러 알고리즘으로 zone 다각형
생성. 존별로 범프를 ASBA(또는 AOVLAP)로 부울 처리하는 APDL 매크로를 출력한다.

경계선 원칙
  - 범프는 점이 아니라 사각형. 경계는 사각형 '외곽선' 사이의 중앙을 지난다
  - 직선화는 통로 반폭에 비례하는 여유(margin)를 양쪽에서 확보할 때만 허용
  - 최외곽에 접한 변은 패키지 엣지와 정확히 일치, 마지막 변의 꺾임 제거

방법 (m 키로 순환)
  ortho    : 사각형 거리장 기반 경계 + min-link, 수평·수직만
  minlink  : 사각형 거리장 기반 경계 + min-link, 각도 제한 없음
  voronoi  : 사각형 외곽선 샘플 Voronoi + min-link (이격 최대)
  convex   : 존 쌍마다 최대마진 직선 1개 (정점 최소, 볼록 존 한정)

출력: labels.txt / bumps.mac / zones.mac / run.mac / zones.png
필요: numpy, scipy, matplotlib, shapely

원본 단독 스크립트에서 바뀐 점
  1. 모듈 상단 상수를 ``configure(**kwargs)`` 로 주입할 수 있게 했다.
  2. ``print`` 대신 ``log`` 를 써서 GUI 로그 창으로도 메시지가 흐르게 했다.
  3. 결과·스냅샷 파일을 ``OUT_DIR`` 아래에 쓰고, ``App`` 이 외부 Figure/Axes 를
     받아 tkinter 창에 임베드될 수 있게 했다.
알고리즘 자체는 원본 그대로다.
"""
import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import RectangleSelector
from scipy.ndimage import distance_transform_edt
from scipy.spatial import Voronoi, cKDTree
from shapely.geometry import Polygon, LineString, Point, MultiPoint, box
from shapely.ops import unary_union, nearest_points
from shapely.strtree import STRtree

# ============================================================
# 설정 ― GUI 가 configure() 로 덮어쓴다
# ============================================================
BUMP_FILE  = "bump.txt"        # 헤더 1줄 + "idx,x,y[,D]"
SEED_DIR   = "zone_sets"
AUTO_FILE  = "_autosave.npz"
OUT_DIR    = ""                # 결과 파일 폴더. ""이면 현재 폴더
AUTOSAVE   = True
D_DEFAULT  = 0.25
X1, X2 = -12.5, 12.5           # 패키지 외곽
Y1, Y2 = -12.5, 12.5

METHODS    = ["ortho", "minlink", "voronoi", "convex"]
METHOD     = "minlink"
CELL       = None              # 래스터/거리장 셀. None이면 자동

CLEAR      = 0.0               # 절대 최소 여유 (형상 단위)
CLEAR_FRAC = 0.40              # 통로 반폭 대비 확보 비율 (0~0.9). 핵심 노브
RECENTER   = True              # 분기점을 통로 중앙으로 재배치
SAMPLE_SIDE = 2                # voronoi: 사각형 한 변당 샘플 수

SNAP       = 9
RELAX_END  = True
EDGE_TOL   = 1e-7

BOOL_OP    = "ASBA"
EDGE_DIV   = 3
MESH_TRI   = True

# ---- 파생값 (configure() 가 다시 계산한다) ----
W_, H_ = X2 - X1, Y2 - Y1
PERIM = 2 * (W_ + H_)

_CONFIG_KEYS = (
    "BUMP_FILE", "SEED_DIR", "AUTO_FILE", "OUT_DIR", "AUTOSAVE", "D_DEFAULT",
    "X1", "X2", "Y1", "Y2", "METHOD", "CELL", "CLEAR", "CLEAR_FRAC",
    "RECENTER", "SAMPLE_SIDE", "SNAP", "RELAX_END", "EDGE_TOL",
    "BOOL_OP", "EDGE_DIV", "MESH_TRI",
)


def _update_derived() -> None:
    g = globals()
    g["W_"] = X2 - X1
    g["H_"] = Y2 - Y1
    g["PERIM"] = 2 * (g["W_"] + g["H_"])


def configure(**kwargs) -> None:
    """모듈 설정을 덮어쓰고 파생값을 다시 계산한다."""
    g = globals()
    for k, v in kwargs.items():
        if k not in _CONFIG_KEYS:
            raise KeyError(f"알 수 없는 설정 항목: {k}")
        g[k] = v
    _update_derived()


def current_config() -> dict:
    g = globals()
    return {k: g[k] for k in _CONFIG_KEYS}


# ============================================================
# 로그 ― stdout + (등록되어 있으면) GUI 로그 창
# ============================================================
_LOG_HOOK = None


def set_log_hook(fn) -> None:
    """log() 가 호출될 때마다 fn(msg) 를 함께 호출한다. None 이면 해제."""
    global _LOG_HOOK
    _LOG_HOOK = fn


def log(*args) -> None:
    msg = " ".join(str(a) for a in args)
    print(msg)
    if _LOG_HOOK is not None:
        try:
            _LOG_HOOK(msg)
        except Exception:
            pass


def out_path(name: str) -> str:
    """결과 파일 경로. OUT_DIR 이 비어 있으면 현재 폴더를 쓴다."""
    if not OUT_DIR:
        return name
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, name)


def seed_dir() -> str:
    return SEED_DIR if os.path.isabs(SEED_DIR) else out_path(SEED_DIR)


def auto_path() -> str:
    return AUTO_FILE if os.path.isabs(AUTO_FILE) else out_path(AUTO_FILE)


def disable_default_keymap() -> None:
    """matplotlib 기본 단축키를 꺼서 도구 단축키와 충돌하지 않게 한다."""
    for _k in list(plt.rcParams):
        if _k.startswith("keymap."):
            plt.rcParams[_k] = []


HELP = """
[ 마우스 ]
  드래그   사각 영역 안의 범프를 현재 구역으로 지정 (계속 누적)
  클릭     가장 가까운 범프 1개 지정
[ 키보드 ]
  n / b    다음 / 이전 구역        0~9  해당 번호로 점프
  l        사각선택 on/off         u    직전 동작 취소
  c        현재 구역 지정 해제     a    미지정 범프 자동 흡수
  w        스냅샷 저장             r/R  최근/이전 스냅샷 로드
  A        자동저장본 복구
  m        생성 방법 순환          g    다각형 생성
  G        네 방법 모두 비교
  [ / ]    CLEAR_FRAC 감소 / 증가 후 재생성
  s        저장                    h    도움말
※ 키가 안 먹으면 그림 안을 클릭해 포커스를 준다. R, A, G 는 Shift 필요.
"""


def load(path, d):
    dat = np.loadtxt(path, delimiter=",", skiprows=1)
    dat = np.atleast_2d(dat)
    xy = dat[:, 1:3].astype(float)
    D = dat[:, 3].astype(float) if dat.shape[1] >= 4 \
        else np.full(len(xy), d, float)
    return xy, D * np.sqrt(np.pi) / 4.0      # 등가 사각볼 반변


def R(p):
    return (round(float(p[0]), SNAP), round(float(p[1]), SNAP))


def shoelace(p):
    n = len(p)
    return 0.5 * sum(p[k][0]*p[(k+1) % n][1] - p[(k+1) % n][0]*p[k][1]
                     for k in range(n))


def _qidx(tree, geoms, geom):
    r = np.asarray(tree.query(geom))
    if r.size == 0:
        return []
    if np.issubdtype(r.dtype, np.integer):
        return r.tolist()
    return [geoms.index(x) for x in r]


# ============================================================
# 박스 둘레 좌표계 (CCW). t=0 이 좌하단 코너
# ============================================================
def snap_box(p):
    x, y = float(p[0]), float(p[1])
    if abs(x - X1) < EDGE_TOL: x = X1
    elif abs(x - X2) < EDGE_TOL: x = X2
    if abs(y - Y1) < EDGE_TOL: y = Y1
    elif abs(y - Y2) < EDGE_TOL: y = Y2
    return R((min(max(x, X1), X2), min(max(y, Y1), Y2)))


def on_box(p):
    return (abs(p[0]-X1) < EDGE_TOL or abs(p[0]-X2) < EDGE_TOL or
            abs(p[1]-Y1) < EDGE_TOL or abs(p[1]-Y2) < EDGE_TOL)


def edge_id(p):
    e = []
    if abs(p[1]-Y1) < EDGE_TOL: e.append(0)
    if abs(p[0]-X2) < EDGE_TOL: e.append(1)
    if abs(p[1]-Y2) < EDGE_TOL: e.append(2)
    if abs(p[0]-X1) < EDGE_TOL: e.append(3)
    return e[0] if len(e) == 1 else -1


def t_of(p):
    x, y = p
    if abs(y - Y1) < EDGE_TOL and abs(x - X2) >= EDGE_TOL:
        return x - X1
    if abs(x - X2) < EDGE_TOL and abs(y - Y2) >= EDGE_TOL:
        return W_ + (y - Y1)
    if abs(y - Y2) < EDGE_TOL and abs(x - X1) >= EDGE_TOL:
        return W_ + H_ + (X2 - x)
    if abs(x - X1) < EDGE_TOL:
        return 2*W_ + H_ + (Y2 - y)
    return W_ - 1e-12 if abs(y - Y1) < EDGE_TOL else 0.0


def p_of(t):
    t = t % PERIM
    if t <= W_:        return snap_box((X1 + t, Y1))
    if t <= W_ + H_:   return snap_box((X2, Y1 + (t - W_)))
    if t <= 2*W_ + H_: return snap_box((X2 - (t - W_ - H_), Y2))
    return snap_box((X1, Y2 - (t - 2*W_ - H_)))


def ray_to_box(a, b):
    d = (b[0]-a[0], b[1]-a[1])
    if abs(d[0]) < 1e-12 and abs(d[1]) < 1e-12:
        return None
    best = None
    for axis, val in ((0, X1), (0, X2), (1, Y1), (1, Y2)):
        dd = d[axis]
        if abs(dd) < 1e-14:
            continue
        s = (val - a[axis]) / dd
        if not np.isfinite(s) or s <= 1.0 + 1e-12:
            continue
        q = (a[0] + d[0]*s, a[1] + d[1]*s)
        if X1-1e-7 <= q[0] <= X2+1e-7 and Y1-1e-7 <= q[1] <= Y2+1e-7:
            if best is None or s < best[0]:
                best = (s, q)
    return None if best is None else snap_box(best[1])


# ============================================================
# 거리장 : 각 지점에서 가장 가까운 '사각 범프 외곽선'까지의 거리
# ============================================================
class DField:
    """dist[j,i] = 셀 중심에서 가장 가까운 범프 사각형까지의 거리"""

    def __init__(self, xy, half, lab, cell):
        nx = max(1, int(np.ceil(W_ / cell)))
        ny = max(1, int(np.ceil(H_ / cell)))
        dx, dy = W_ / nx, H_ / ny
        g = np.zeros((ny, nx), np.int32)              # 0 = 범프 밖
        for (x, y), h, z in zip(xy, half, lab):
            i0 = int(np.clip(np.floor((x-h-X1)/dx + 1e-12), 0, nx-1))
            i1 = int(np.clip(np.floor((x+h-X1)/dx - 1e-12), 0, nx-1))
            j0 = int(np.clip(np.floor((y-h-Y1)/dy + 1e-12), 0, ny-1))
            j1 = int(np.clip(np.floor((y+h-Y1)/dy - 1e-12), 0, ny-1))
            g[j0:j1+1, i0:i1+1] = z + 1
        dist, ind = distance_transform_edt(
            g == 0, sampling=(dy, dx),
            return_distances=True, return_indices=True)
        self.g = g[tuple(ind)]                         # 존 라벨 채움
        self.dist = dist
        self.nx, self.ny, self.dx, self.dy = nx, ny, dx, dy
        self.med = float(np.median(dist[dist > 0])) if (dist > 0).any() else cell

    def cell_of(self, p):
        i = int(np.clip(np.floor((p[0]-X1)/self.dx), 0, self.nx-1))
        j = int(np.clip(np.floor((p[1]-Y1)/self.dy), 0, self.ny-1))
        return i, j

    def at(self, p):
        """격자선 위 점 → 인접 4셀의 최대 거리 (통로 반폭 추정)"""
        i, j = self.cell_of(p)
        i0, i1 = max(0, i-1), min(self.nx-1, i)
        j0, j1 = max(0, j-1), min(self.ny-1, j)
        return float(self.dist[j0:j1+1, i0:i1+1].max())

    def recenter(self, p, rad):
        """반경 rad 안에서 거리가 최대인 셀 중심으로 이동"""
        if rad <= 0:
            return p
        i, j = self.cell_of(p)
        ri = max(1, int(rad/self.dx)); rj = max(1, int(rad/self.dy))
        i0, i1 = max(0, i-ri), min(self.nx, i+ri+1)
        j0, j1 = max(0, j-rj), min(self.ny, j+rj+1)
        w = self.dist[j0:j1, i0:i1]
        if w.size == 0:
            return p
        k = np.unravel_index(int(np.argmax(w)), w.shape)
        q = (X1 + (i0+k[1] + 0.5)*self.dx, Y1 + (j0+k[0] + 0.5)*self.dy)
        return snap_box(q)


# ============================================================
# 여유(margin) 판정
# ============================================================
def seg_clear(seg, margin, sq, sq_tree):
    """세그먼트가 모든 범프 사각형에서 margin 이상 떨어져 있는가"""
    x0, y0, x1, y1 = seg.bounds
    m = max(margin, 1e-12)
    env = box(x0-m, y0-m, x1+m, y1+m)
    for k in _qidx(sq_tree, sq, env):
        if sq[k].distance(seg) < margin - 1e-12:
            return False
        if margin <= 0 and sq[k].intersects(seg):
            return False
    return True


# ============================================================
# 체인 분해 → min-link → 끝점 완화 → 테두리 재구성 → 조립
# ============================================================
def make_chains(adj):
    used, chains = set(), []

    def walk(p, q):
        ch = [p, q]; used.add(frozenset((p, q)))
        prev, cur = p, q
        while len(adj[cur]) == 2:
            nx_ = [r for r in adj[cur] if r != prev]
            if not nx_:
                break
            r = nx_[0]; e = frozenset((cur, r))
            if e in used:
                break
            used.add(e); ch.append(r); prev, cur = cur, r
        return ch

    for p in [n for n, s in adj.items() if len(s) != 2]:
        for q in list(adj[p]):
            if frozenset((p, q)) not in used:
                chains.append(walk(p, q))
    for p in list(adj):
        for q in list(adj[p]):
            if frozenset((p, q)) not in used:
                ch = walk(p, q)
                if ch[0] != ch[-1]:
                    ch.append(ch[0])
                chains.append(ch)
    return chains


def simplify_chain(pts, dv, ok):
    """greedy min-link. ok(sub_pts, sub_dv) 가 여유까지 판정"""
    out, i, n = [pts[0]], 0, len(pts)
    while i < n - 1:
        lo, hi, best = i + 1, n - 1, i + 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if ok(pts[i:mid+1], dv[i:mid+1]):
                best = mid; lo = mid + 1
            else:
                hi = mid - 1
        out.append(pts[best]); i = best
    return out


def assemble(simp, zpair):
    per = {}
    for s, (za, zb) in zip(simp, zpair):
        if za: per.setdefault(za, []).append(list(s))
        if zb: per.setdefault(zb, []).append(list(s)[::-1])
    out = {}
    for z, segs in per.items():
        start = {}
        for s in segs:
            start.setdefault(R(s[0]), []).append(s)
        left, loops = len(segs), []
        while left > 0:
            k0 = next((k for k, v in start.items() if v), None)
            if k0 is None:
                break
            loop = list(start[k0].pop()); left -= 1
            while True:
                k2 = R(loop[-1])
                if k2 == k0 or not start.get(k2):
                    break
                loop += start[k2].pop()[1:]; left -= 1
            if R(loop[0]) == R(loop[-1]):
                loop = loop[:-1]
            if len(loop) >= 3:
                loops.append(loop)
        if not loops:
            continue
        conv = [(lp, shoelace(lp) < 0) for lp in loops]
        conv.sort(key=lambda t: t[1])
        out[z - 1] = conv
    return out


def relax_terminals(simp, sq, sq_tree, ctr, ct_tree, df, ortho):
    """박스 엣지 끝점을 엣지 위에서 미끄러뜨려 마지막 변의 꺾임 제거"""
    term = []
    for ci, s in enumerate(simp):
        for end in (0, -1):
            if on_box(s[end]):
                term.append([t_of(s[end]), ci, end])
    if not term:
        return simp, 0
    term.sort(key=lambda a: a[0])

    corners = [0.0, W_, W_ + H_, 2*W_ + H_, PERIM]
    lim = {}
    for k, (t, ci, end) in enumerate(term):
        lo = term[k-1][0] if k > 0 else 0.0
        hi = term[k+1][0] if k < len(term)-1 else PERIM
        for c in corners:
            if lo < c <= t: lo = c
            if t <= c < hi: hi = c
        lim[(ci, end)] = (lo + 1e-9, hi - 1e-9)

    def clear(quad, seg_pts, margin):
        seg = LineString(seg_pts)
        if not seg_clear(seg, margin, sq, sq_tree):
            return False
        try:
            q = Polygon(quad)
            if not q.is_valid:
                q = q.buffer(0)
        except Exception:
            return False
        if q.is_empty or q.area < 1e-14:
            return True
        for k in _qidx(ct_tree, ctr, q):
            if q.contains(ctr[k]):
                return False
        return True

    saved, out = 0, []
    for ci, s in enumerate(simp):
        s = list(s)
        for end in (0, -1):
            if not on_box(s[end]) or (ci, end) not in lim:
                continue
            lo, hi = lim[(ci, end)]
            rev = (end == -1)
            if rev:
                s = s[::-1]
            while len(s) >= 3:
                q0, q1, q2 = s[0], s[1], s[2]
                if on_box(q1):
                    break
                if ortho and abs(q2[0]-q1[0]) > 1e-9 and abs(q2[1]-q1[1]) > 1e-9:
                    break
                p = ray_to_box(q2, q1)
                if p is None or not on_box(p):
                    break
                tp = t_of(p)
                if not (lo <= tp <= hi):
                    break
                if edge_id(q0) != -1 and edge_id(p) != edge_id(q0):
                    break
                mg = max(CLEAR, CLEAR_FRAC * min(df.at(q1), df.at(q2)))
                if not clear([q0, q1, q2, p], [p, q2], mg):
                    break
                s = [p] + s[2:]
                saved += 1
            if rev:
                s = s[::-1]
        out.append(s)
    return out, saved


def rebuild_border(simp, zpair, xy, lab, tree):
    """테두리 체인을 버리고 코너 + 접점으로 직선 테두리를 재구성"""
    inner, izp = [], []
    for s, zp in zip(simp, zpair):
        if 0 in zp:
            continue
        inner.append(s); izp.append(zp)

    ts = {0.0, W_, W_ + H_, 2*W_ + H_}
    for s in inner:
        for p in (s[0], s[-1]):
            if on_box(p):
                ts.add(round(t_of(p), SNAP))
    ts = sorted(ts)
    if not ts:
        return inner, izp

    d = min(W_, H_) * 1e-4
    nrm = {0: (0, 1), 1: (-1, 0), 2: (0, -1), 3: (1, 0)}
    border, bzp = [], []
    for k in range(len(ts)):
        ta = ts[k]
        tb = ts[k+1] if k < len(ts)-1 else ts[0] + PERIM
        if tb - ta < 1e-9:
            continue
        pm = p_of(0.5*(ta + tb))
        nx_, ny_ = nrm.get(edge_id(pm), (0, 0))
        _, j = tree.query([pm[0] + nx_*d, pm[1] + ny_*d])
        border.append([p_of(ta), p_of(tb)])
        bzp.append((int(lab[j]) + 1, 0))
    return inner + border, izp + bzp


def simplify_and_assemble(chains, zpair, xy, half, lab, sq, ctr, df,
                          ortho, tag):
    raw = sum(len(c) for c in chains)
    sq_tree, ct_tree = STRtree(sq), STRtree(ctr)

    # --- 분기점을 통로 중앙으로 재배치 (전역 일관) ---
    moved = 0
    if RECENTER:
        ends = set()
        for c in chains:
            ends.add(c[0]); ends.add(c[-1])
        remap = {}
        for p in ends:
            if on_box(p):
                continue
            r = df.at(p) * 0.6
            q = df.recenter(p, r)
            if q != p and df.at(q) > df.at(p) * 1.02:
                remap[p] = q; moved += 1
        if remap:
            chains = [[remap.get(p, p) for p in c] for c in chains]

    dvs = [[df.at(p) for p in c] for c in chains]

    def make_ok(own, nodes, nd_tree):
        def ok(sub, dvsub):
            a, b = sub[0], sub[-1]
            if ortho and abs(a[0]-b[0]) > 1e-9 and abs(a[1]-b[1]) > 1e-9:
                return False
            seg = LineString([a, b])
            mg = max(CLEAR, CLEAR_FRAC * min(dvsub)) if dvsub else CLEAR
            if not seg_clear(seg, mg, sq, sq_tree):
                return False
            try:
                poly = Polygon(list(sub) + [a])
                if not poly.is_valid:
                    poly = poly.buffer(0)
            except Exception:
                return False
            if poly.is_empty or poly.area < 1e-14:
                return True
            for k in _qidx(ct_tree, ctr, poly):
                if poly.contains(ctr[k]):
                    return False
            for k in _qidx(nd_tree, nodes, poly):
                if nodes[k].coords[0] not in own and poly.contains(nodes[k]):
                    return False
            return True
        return ok

    nodes = [Point(p) for c in chains for p in c]
    nd_tree = STRtree(nodes)
    simp = [simplify_chain(c, d, make_ok(set(c), nodes, nd_tree))
            for c, d in zip(chains, dvs)]
    n1 = sum(len(s) for s in simp)

    saved = 0
    if RELAX_END:
        simp, saved = relax_terminals(simp, sq, sq_tree, ctr, ct_tree,
                                      df, ortho)

    simp, zpair = rebuild_border(simp, zpair, xy, lab, cKDTree(xy))
    log(f"[{tag}] {len(chains)} chains, {raw} -> {n1} verts  "
        f"(중앙보정 {moved}, 엣지꺾임 제거 {saved}, "
        f"최종 {sum(len(s) for s in simp)})")
    return assemble(simp, zpair)


# ============================================================
# 백엔드 A: 거리장 래스터 (ortho / minlink)
# ============================================================
def grid_boundary(g):
    gg = np.pad(g, 1, constant_values=0)
    dirmap, adj = {}, {}

    def add(p, q, z):
        dirmap[(p, q)] = int(z)
        adj.setdefault(p, set()).add(q)
        adj.setdefault(q, set()).add(p)

    a, b = gg[1:-1, :-1], gg[1:-1, 1:]
    for j, i in zip(*np.nonzero(a != b)):
        if a[j, i]: add((i, j), (i, j+1), a[j, i])
        if b[j, i]: add((i, j+1), (i, j), b[j, i])
    a, b = gg[:-1, 1:-1], gg[1:, 1:-1]
    for j, i in zip(*np.nonzero(a != b)):
        if a[j, i]: add((i+1, j), (i, j), a[j, i])
        if b[j, i]: add((i, j), (i+1, j), b[j, i])
    return dirmap, adj


def backend_raster(xy, half, lab, df, sq, ctr, ortho):
    log(f"[grid] {df.nx} x {df.ny}  cell={df.dx:.4f}  "
        f"통로 반폭 중앙값 {df.med:.4f}")
    dirmap, adj = grid_boundary(df.g)
    ch = make_chains(adj)
    chains = [[snap_box((X1 + i*df.dx, Y1 + j*df.dy)) for i, j in c]
              for c in ch]
    zpair = [(dirmap.get((c[0], c[1]), 0), dirmap.get((c[1], c[0]), 0))
             for c in ch]
    return simplify_and_assemble(chains, zpair, xy, half, lab, sq, ctr, df,
                                 ortho, "ortho" if ortho else "minlink")


# ============================================================
# 백엔드 B: 사각형 외곽선 샘플 Voronoi
# ============================================================
def square_samples(xy, half, ns):
    """각 사각 범프 외곽선 위의 샘플점 + 소속 범프 인덱스"""
    pts, own = [], []
    t = (np.arange(ns) + 0.5) / ns                    # 0..1 변 위 위치
    for b, ((x, y), h) in enumerate(zip(xy, half)):
        u = x - h + 2*h*t
        v = y - h + 2*h*t
        s = np.concatenate([
            np.c_[u, np.full(ns, y-h)], np.c_[u, np.full(ns, y+h)],
            np.c_[np.full(ns, x-h), v], np.c_[np.full(ns, x+h), v],
            np.array([[x-h, y-h], [x+h, y-h], [x+h, y+h], [x-h, y+h]])])
        pts.append(s); own.append(np.full(len(s), b))
    return np.vstack(pts), np.concatenate(own)


def voronoi_zone_polys(xy, half, lab, nz, bx):
    P, own = square_samples(xy, half, SAMPLE_SIDE)
    c = xy.mean(0)
    r = 12.0 * max(W_, H_)
    ang = np.linspace(0, 2*np.pi, 96, endpoint=False)
    ghost = c + r * np.c_[np.cos(ang), np.sin(ang)]
    vor = Voronoi(np.vstack([P, ghost]))
    log(f"[voronoi] 외곽선 샘플 {len(P)}점")

    cells = [[] for _ in range(nz)]
    for s in range(len(P)):
        reg = vor.regions[vor.point_region[s]]
        if not reg or -1 in reg:
            continue
        p = Polygon(vor.vertices[reg])
        if not p.is_valid:
            p = p.buffer(0)
        p = p.intersection(bx)
        if not p.is_empty:
            cells[lab[own[s]]].append(p)

    out = {}
    for z in range(nz):
        if not cells[z]:
            continue
        u = unary_union(cells[z])
        if not u.is_valid:
            u = u.buffer(0)
        out[z] = u
    return out


def polys_to_boundary(zone_polys):
    dirmap, adj = {}, {}

    def add(p, q, z):
        if p == q:
            return
        dirmap[(p, q)] = int(z)
        adj.setdefault(p, set()).add(q)
        adj.setdefault(q, set()).add(p)

    for z, geom in zone_polys.items():
        parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for pg in parts:
            for ring in [pg.exterior] + list(pg.interiors):
                pts = [snap_box(c) for c in ring.coords[:-1]]
                pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i-1]]
                if len(pts) < 3:
                    continue
                if (shoelace(pts) < 0) != (ring is not pg.exterior):
                    pts = pts[::-1]
                for i in range(len(pts)):
                    add(pts[i], pts[(i+1) % len(pts)], z + 1)
    return dirmap, adj


def backend_voronoi(xy, half, lab, nz, df, sq, ctr):
    bx = box(X1, Y1, X2, Y2)
    zp = voronoi_zone_polys(xy, half, lab, nz, bx)
    gap = bx.area - sum(p.area for p in zp.values())
    log(f"[voronoi] {len(zp)} zones, 미충전 {100*gap/bx.area:.4f}%")
    dirmap, adj = polys_to_boundary(zp)
    ch = make_chains(adj)
    zpair = [(dirmap.get((c[0], c[1]), 0), dirmap.get((c[1], c[0]), 0))
             for c in ch]
    return simplify_and_assemble(ch, zpair, xy, half, lab, sq, ctr, df,
                                 False, "voronoi")


# ============================================================
# 백엔드 C: 최대마진 반평면 (convex)
# ============================================================
def half_plane(mid, d, L):
    t = np.array([-d[1], d[0]])
    p1, p2 = mid + t*L, mid - t*L
    return Polygon([tuple(p1), tuple(p2),
                    tuple(p2 - d*2*L), tuple(p1 - d*2*L)])


def backend_convex(xy, half, lab, nz):
    bx = box(X1, Y1, X2, Y2)
    L = 10.0 * np.hypot(W_, H_)
    hull = {}
    for z in range(nz):
        idx = np.flatnonzero(lab == z)
        if len(idx) == 0:
            continue
        pts = []
        for b in idx:
            x, y = xy[b]; h = half[b]                  # 사각형 모서리 사용
            pts += [(x-h, y-h), (x+h, y-h), (x+h, y+h), (x-h, y+h)]
        hull[z] = MultiPoint(pts).convex_hull

    out, bad = {}, []
    for z in hull:
        p = bx
        for w in hull:
            if w == z:
                continue
            a, b = nearest_points(hull[z], hull[w])
            d = np.array([b.x - a.x, b.y - a.y])
            n = np.linalg.norm(d)
            if n < 1e-12:
                bad.append((z, w)); continue
            d /= n
            mid = np.array([(a.x + b.x)/2, (a.y + b.y)/2])   # 껍질 사이 중앙
            p = p.intersection(half_plane(mid, d, L))
            if p.is_empty:
                break
        if p.is_empty:
            continue
        if p.geom_type == "MultiPolygon":
            p = max(p.geoms, key=lambda q: q.area)
        pts = [snap_box(c) for c in p.exterior.coords[:-1]]
        pts = [q for i, q in enumerate(pts) if i == 0 or q != pts[i-1]]
        if shoelace(pts) < 0:
            pts = pts[::-1]
        out[z] = [(pts, False)]

    gap = bx.area - sum(Polygon(v[0][0]).area for v in out.values())
    log(f"[convex] {len(out)} zones, "
        f"{sum(len(v[0][0]) for v in out.values())} verts, "
        f"미충전 {100*gap/bx.area:.4f}%")
    if bad:
        log(f"[!] 선형 분리 불가 존 쌍 {len(bad)}개 → 다른 방법 사용")
    return out


# ============================================================
# 검증 : 잘림 / 이탈 / 충전율 / 최소 이격
# ============================================================
def zone_geom(loops):
    outer = [p for p, hl in loops if not hl]
    if not outer:
        return None
    pg = Polygon(outer[0])
    if not pg.is_valid:
        pg = pg.buffer(0)
    for hp in [p for p, hl in loops if hl]:
        h = Polygon(hp)
        if not h.is_valid:
            h = h.buffer(0)
        pg = pg.difference(h)
    return pg


def check_polys(polys, xy, half, lab):
    lines = []
    for z, loops in polys.items():
        for pts, _ in loops:
            lines.append(LineString(list(pts) + [pts[0]]))
    bnd = unary_union(lines)

    sq = [box(x-h, y-h, x+h, y+h) for (x, y), h in zip(xy, half)]
    cut, gaps = set(), []
    for b, s in enumerate(sq):
        d = bnd.distance(s)
        if bnd.intersects(s.buffer(-1e-9)):
            cut.add(b)
        elif d < 1e12:
            gaps.append(d)
    gaps = np.array(gaps) if gaps else np.array([0.0])

    miss, tot = 0, 0.0
    for z, loops in polys.items():
        pg = zone_geom(loops)
        if pg is None:
            continue
        tot += pg.area
        for b in np.flatnonzero(lab == z):
            if not pg.covers(Point(xy[b])):
                miss += 1
    cov = 100.0 * tot / (W_ * H_)
    log(f"[check] 잘린 범프 {len(cut)}, 존 이탈 {miss}, 충전율 {cov:.4f}%,"
        f" 이격 min {gaps.min():.5f} / p5 {np.percentile(gaps,5):.5f}"
        f" / med {np.median(gaps):.5f}")
    return cut, miss, cov, float(gaps.min())


# ============================================================
# GUI
# ============================================================
class App:
    def __init__(self, xy, half, fig=None, ax=None):
        disable_default_keymap()
        self.xy, self.half = xy, half
        self.lab = np.full(len(xy), -1, int)
        self.cur = 0
        self.undo = []
        self.polys = None
        self.slot = None
        self.method = METHOD
        self.cell = CELL if CELL else max(half.min()/2.5, W_/1600)
        self.cmap = plt.get_cmap("tab20")
        self._drag = False
        self.on_state = None            # 외부(GUI) 상태 표시 콜백

        if fig is None or ax is None:
            self.fig, self.ax = plt.subplots(figsize=(11, 10.5))
        else:
            self.fig, self.ax = fig, ax
        self.fig._zone_paint_app = self          # GC 방지 앵커
        self.ax.set_aspect("equal", adjustable="box")
        self.sc = self.ax.scatter(xy[:, 0], xy[:, 1],
                                  s=8 if len(xy) > 8000 else 18,
                                  c="0.78", linewidths=0, zorder=3)
        self.patches = []

        style = dict(facecolor="none", edgecolor="crimson",
                     linewidth=1.2, linestyle="--")
        try:
            self.rect = RectangleSelector(self.ax, self.on_rect, useblit=True,
                                          button=[1], minspanx=0, minspany=0,
                                          spancoords="data", props=style)
        except TypeError:
            self.rect = RectangleSelector(self.ax, self.on_rect, useblit=True,
                                          button=[1], minspanx=0, minspany=0,
                                          spancoords="data", rectprops=style)

        c = self.fig.canvas
        self._cids = [
            c.mpl_connect("key_press_event", self.on_key),
            c.mpl_connect("button_release_event", self.on_click),
        ]
        try:
            c.setFocusPolicy(2); c.setFocus()
        except Exception:
            pass

        log(HELP)
        log(f"[i] 범프 {len(xy)}개, 패키지 {W_:g} x {H_:g}, "
            f"셀 {self.cell:g}")
        s = self._slots()
        if s:
            log(f"[i] 스냅샷 {len(s)}개: " + ", ".join(s))
        if os.path.exists(auto_path()):
            log("[i] 자동저장본 있음 (A 로 복구)")
        self.draw()

    # ---------- 스냅샷 ----------
    def _sig(self):
        return np.array([len(self.xy), round(float(self.xy.sum()), 6)])

    def _dump(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        np.savez(path, lab=self.lab, cur=self.cur, sig=self._sig())

    def _slots(self):
        d = seed_dir()
        if not os.path.isdir(d):
            return []
        return sorted(f for f in os.listdir(d) if f.endswith(".npz"))

    def _load_npz(self, path):
        d = np.load(path)
        if len(d["lab"]) != len(self.xy):
            log(f"[!] 범프 수 불일치 ({len(d['lab'])} vs {len(self.xy)})")
            return False
        if "sig" in d and not np.allclose(d["sig"], self._sig()):
            log("[!] 경고: 범프 좌표가 저장 당시와 다르다")
        self.lab = d["lab"].copy()
        self.cur = int(d["cur"]) if "cur" in d else 0
        self.polys = None
        self.undo.clear()
        return True

    def snapshot(self):
        d = seed_dir()
        os.makedirs(d, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(d, f"set{n:02d}.npz")):
            n += 1
        p = os.path.join(d, f"set{n:02d}.npz")
        self._dump(p)
        self.slot = self._slots().index(f"set{n:02d}.npz")
        log(f"[snapshot] {p}   지정 {int((self.lab>=0).sum())}개")

    def restore(self, idx=None):
        s = self._slots()
        if not s:
            log(f"[!] {seed_dir()}/ 비어 있음"); return
        if idx is None:
            idx = self.slot if self.slot is not None else len(s) - 1
        idx = max(0, min(len(s) - 1, idx))
        if not self._load_npz(os.path.join(seed_dir(), s[idx])):
            return
        self.slot = idx
        log(f"[load] {s[idx]}  ({idx+1}/{len(s)})")
        self.draw()

    def prev_slot(self):
        s = self._slots()
        if not s:
            log(f"[!] {seed_dir()}/ 비어 있음"); return
        cur = self.slot if self.slot is not None else len(s)
        self.restore((cur - 1) % len(s))

    def restore_auto(self):
        p = auto_path()
        if not os.path.exists(p):
            log(f"[!] {p} 없음"); return
        if self._load_npz(p):
            log(f"[auto-load] 지정 {int((self.lab>=0).sum())}개")
            self.draw()

    # ---------- 선택 ----------
    def apply(self, idx, z):
        if len(idx) == 0:
            return
        self.undo.append((idx, self.lab[idx].copy()))
        self.lab[idx] = z
        self.polys = None
        if AUTOSAVE:
            self._dump(auto_path())
        self.draw()

    def on_rect(self, ec, er):
        if ec.xdata is None or er.xdata is None:
            self._drag = False; return
        x0, x1 = sorted((ec.xdata, er.xdata))
        y0, y1 = sorted((ec.ydata, er.ydata))
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            self._drag = False; return
        self._drag = True
        m = (self.xy[:, 0] >= x0) & (self.xy[:, 0] <= x1) & \
            (self.xy[:, 1] >= y0) & (self.xy[:, 1] <= y1)
        self.apply(np.flatnonzero(m), self.cur)

    def on_click(self, ev):
        if ev.inaxes is not self.ax or ev.button != 1:
            return
        if self.fig.canvas.toolbar and getattr(self.fig.canvas.toolbar, "mode", ""):
            return
        if self._drag:
            self._drag = False; return
        d = np.hypot(self.xy[:, 0]-ev.xdata, self.xy[:, 1]-ev.ydata)
        self.apply(np.array([int(d.argmin())]), self.cur)

    def autofill(self):
        bad = self.lab < 0
        if not bad.any():
            log("[auto] 미지정 없음"); return
        if not (~bad).any():
            log("[!] 지정된 범프가 없다"); return
        good = np.flatnonzero(~bad)
        _, j = cKDTree(self.xy[good]).query(self.xy[bad])
        self.lab[bad] = self.lab[good[j]]
        self.polys = None
        if AUTOSAVE:
            self._dump(auto_path())
        log(f"[auto] {int(bad.sum())}개 흡수")
        self.draw()

    # ---------- 생성 ----------
    def _prep(self):
        if (self.lab < 0).any():
            log(f"[!] 미지정 {int((self.lab<0).sum())}개 — a 로 흡수 먼저")
            return None
        ids = np.unique(self.lab)
        self.lab = np.searchsorted(ids, self.lab)
        sq = [box(x-h, y-h, x+h, y+h)
              for (x, y), h in zip(self.xy, self.half)]
        ctr = [Point(x, y) for x, y in self.xy]
        df = DField(self.xy, self.half, self.lab, self.cell)
        return len(ids), sq, ctr, df

    def _run(self, method, sq, ctr, df, nz):
        if method == "ortho":
            return backend_raster(self.xy, self.half, self.lab, df, sq, ctr, True)
        if method == "minlink":
            return backend_raster(self.xy, self.half, self.lab, df, sq, ctr, False)
        if method == "voronoi":
            return backend_voronoi(self.xy, self.half, self.lab, nz, df, sq, ctr)
        if method == "convex":
            return backend_convex(self.xy, self.half, self.lab, nz)
        raise ValueError(method)

    def generate(self):
        p = self._prep()
        if p is None:
            return
        nz, sq, ctr, df = p
        log(f"\n=== method = {self.method}   CLEAR_FRAC = {CLEAR_FRAC} ===")
        try:
            self.polys = self._run(self.method, sq, ctr, df, nz)
        except Exception as e:
            log(f"[!] {self.method} 실패: {e}")
            return
        vt = {z: sum(len(q) for q, _ in v) for z, v in self.polys.items()}
        log(f"[gen] zones={len(self.polys)}  verts={sum(vt.values())}  "
            f"max={max(vt.values())}")
        check_polys(self.polys, self.xy, self.half, self.lab)
        self.draw()

    def compare(self):
        p = self._prep()
        if p is None:
            return
        nz, sq, ctr, df = p
        rows = []
        for mth in METHODS:
            log(f"\n=== method = {mth} ===")
            try:
                pol = self._run(mth, sq, ctr, df, nz)
                v = sum(sum(len(q) for q, _ in val) for val in pol.values())
                cut, miss, cov, gmin = check_polys(pol, self.xy,
                                                   self.half, self.lab)
                rows.append((mth, len(pol), v, len(cut), miss, cov, gmin))
            except Exception as e:
                log(f"[!] 실패: {e}")
                rows.append((mth, 0, -1, -1, -1, 0.0, 0.0))
        log("\n" + "-"*72)
        log(f"{'method':<10}{'zones':>6}{'verts':>8}{'cut':>5}{'miss':>6}"
            f"{'cover%':>11}{'gap_min':>12}")
        for r in rows:
            log(f"{r[0]:<10}{r[1]:>6}{r[2]:>8}{r[3]:>5}{r[4]:>6}"
                f"{r[5]:>11.4f}{r[6]:>12.5f}")
        log("-"*72 + "\n")
        return rows

    def cycle_method(self):
        self.method = METHODS[(METHODS.index(self.method)+1) % len(METHODS)]
        self.polys = None
        log(f"[method] {self.method}")
        self.draw()

    def set_method(self, method):
        if method not in METHODS:
            log(f"[!] 알 수 없는 방법: {method}"); return
        self.method = method
        self.polys = None
        log(f"[method] {self.method}")
        self.draw()

    def bump_frac(self, up):
        global CLEAR_FRAC
        CLEAR_FRAC = float(np.clip(CLEAR_FRAC + (0.05 if up else -0.05), 0.0, 0.9))
        log(f"[CLEAR_FRAC] {CLEAR_FRAC:.2f}")
        self.generate()

    # ---------- APDL 출력 ----------
    @staticmethod
    def _loop(f, pts, var):
        n = len(pts)
        f.write("! -- polygon --\n"
                "*GET,ZK,KP,0,NUM,MAX\n*GET,ZL,LINE,0,NUM,MAX\n"
                "*GET,ZA,AREA,0,NUM,MAX\n"
                "ZK1 = ZK+1\nZL1 = ZL+1\nZA1 = ZA+1\n"
                "NUMSTR,KP,ZK1\nNUMSTR,LINE,ZL1\nNUMSTR,AREA,ZA1\n")
        f.write(f"{var} = ZA1\n")
        for px, py in pts:
            f.write(f"K,,{px:.6f},{py:.6f},0\n")
        f.write(f"ZKN = ZK+{n}\nZLN = ZL+{n}\n"
                "*DO,ii,ZK1,ZKN\n"
                "  *IF,ii,LT,ZKN,THEN\n    L,ii,ii+1\n"
                "  *ELSE\n    L,ii,ZK1\n  *ENDIF\n*ENDDO\n"
                "LSEL,S,LINE,,ZL1,ZLN\nAL,ALL\nALLSEL,ALL\nNUMSTR,DEFA\n")

    @staticmethod
    def _sel_runs(f, nums, first="A"):
        s = p = nums[0]
        for v in nums[1:] + [None]:
            if v == p + 1:
                p = v; continue
            f.write(f"ASEL,{first},AREA,,{s},{p}\n")
            if v is not None:
                s = p = v

    def write_bumps(self, path=None):
        path = path or out_path("bumps.mac")
        with open(path, "w") as f:
            f.write("/PREP7\n/NOPR\nNUMSTR,DEFA\nBOPTN,NUMB,OFF\n")
            for (x, y), h in zip(self.xy, self.half):
                f.write(f"RECTNG,{x-h:.6f},{x+h:.6f},{y-h:.6f},{y+h:.6f}\n")
            f.write("/GOPR\nALLSEL,ALL\nCM,SQ,AREA\n")

    def write_zones(self, path=None):
        path = path or out_path("zones.mac")
        nsq = len(self.xy)
        with open(path, "w") as f:
            f.write(f"/PREP7\n! method = {self.method}, "
                    f"CLEAR_FRAC = {CLEAR_FRAC}\n"
                    f"NSQ = {nsq}\nBOPTN,NUMB,OFF\nBOPTN,KEEP,NO\n")
            for k, (z, loops) in enumerate(sorted(self.polys.items())):
                nums = sorted(int(b)+1 for b in np.flatnonzero(self.lab == z))
                outer = [p for p, hl in loops if not hl]
                holes = [p for p, hl in loops if hl]
                if not outer:
                    continue
                f.write(f"\n! ===== zone {z}: bumps={len(nums)}, "
                        f"verts={len(outer[0])}\n")
                self._loop(f, outer[0], "AZONE")
                for hp in holes:
                    self._loop(f, hp, "AHOLE")
                    f.write("ALLSEL,ALL\nCM,_PREA,AREA\n"
                            "ASBA,AZONE,AHOLE,,DELETE,DELETE\n"
                            "ALLSEL,ALL\nCMSEL,U,_PREA\n"
                            "*GET,AZONE,AREA,0,NUM,MIN\n"
                            "CMDELE,_PREA\nALLSEL,ALL\n")
                if not nums:
                    f.write("ALLSEL,ALL\n"); continue
                f.write("ALLSEL,ALL\nASEL,NONE\n")
                self._sel_runs(f, nums)
                f.write(f"CM,SQ{z},AREA\nASEL,A,AREA,,AZONE\n")
                f.write("AOVLAP,ALL\n" if BOOL_OP == "AOVLAP"
                        else "ASBA,AZONE,ALL,,DELETE,KEEP\n")
                f.write("ALLSEL,ALL\nASEL,S,AREA,,1,NSQ\nASEL,INVE\n")
                if k > 0:
                    f.write("CMSEL,U,ZDONE\n")
                f.write(f"CM,ZN{z},AREA\n")
                if k > 0:
                    f.write("CMSEL,A,ZDONE\n")
                f.write("CM,ZDONE,AREA\nALLSEL,ALL\n")
            f.write("\nNUMSTR,DEFA\nALLSEL,ALL\n"
                    "*GET,natot,AREA,0,COUNT\n"
                    "*MSG,INFO,natot\ntotal areas after boolean = %I\n")

    def write_run(self, path=None):
        path = path or out_path("run.mac")
        nsq = len(self.xy)
        esz = float(np.median(self.half)) * 3.0
        with open(path, "w") as f:
            f.write(f"""/CLEAR,NOSTART
/PREP7
NSQ = {nsq}

*USE,bumps.mac
*USE,zones.mac          ! method = {self.method}

ALLSEL,ALL
*GET,nA,AREA,0,COUNT
CMSEL,S,SQ
*GET,nB,AREA,0,COUNT
ALLSEL,ALL
*MSG,INFO,nB,NSQ,nA
bump areas = %I / %I , total areas = %I

ET,1,PLANE182
KEYOPT,1,3,2            ! plane strain. 필요에 맞게 수정
SMRT,OFF
MOPT,TIMP,1

CMSEL,S,SQ
LSLA,S
LESIZE,ALL,,,{EDGE_DIV}
ALLSEL,ALL
MSHKEY,1
CMSEL,S,SQ
AMESH,ALL

ALLSEL,ALL
MSHKEY,0
MSHAPE,{1 if MESH_TRI else 0},2D
ESIZE,{esz:.4f}
CMSEL,S,ZDONE
AMESH,ALL

ALLSEL,ALL
NUMMRG,NODE
NUMCMP,NODE
*GET,nE,ELEM,0,COUNT
*MSG,INFO,nE
elements = %I
""")

    def save(self):
        if self.polys is None:
            log("[!] g 로 다각형 생성 먼저"); return
        np.savetxt(out_path("labels.txt"),
                   np.column_stack([np.arange(1, len(self.xy)+1),
                                    self.xy, self.lab]),
                   delimiter=",", fmt=["%d", "%.6f", "%.6f", "%d"],
                   header="idx,x,y,zone")
        self.snapshot()
        self.write_bumps()
        self.write_zones()
        self.write_run()
        self.fig.savefig(out_path("zones.png"), dpi=170, bbox_inches="tight")
        log(f"[save] method={self.method}  labels.txt / bumps.mac / "
            "zones.mac / run.mac / zones.png"
            + (f"  →  {os.path.abspath(OUT_DIR)}" if OUT_DIR else ""))

    # ---------- 키 ----------
    def on_key(self, ev):
        k = ev.key
        if k == "n":
            self.cur += 1
        elif k == "b":
            self.cur = max(0, self.cur-1)
        elif k and k.isdigit():
            self.cur = int(k)
        elif k == "l":
            self.rect.set_active(not self.rect.active)
            log(f"[rect] {'ON' if self.rect.active else 'OFF'}")
        elif k == "u":
            if self.undo:
                i, o = self.undo.pop(); self.lab[i] = o; self.polys = None
            else:
                log("[!] 취소할 동작 없음")
        elif k == "c":
            self.apply(np.flatnonzero(self.lab == self.cur), -1); return
        elif k == "a":
            self.autofill(); return
        elif k == "w":
            self.snapshot(); return
        elif k == "r":
            self.restore(); return
        elif k == "R":
            self.prev_slot(); return
        elif k == "A":
            self.restore_auto(); return
        elif k == "m":
            self.cycle_method(); return
        elif k == "g":
            self.generate(); return
        elif k == "G":
            self.compare(); return
        elif k == "]":
            self.bump_frac(True); return
        elif k == "[":
            self.bump_frac(False); return
        elif k == "s":
            self.save(); return
        elif k == "h":
            log(HELP); return
        else:
            return
        self.draw()

    # ---------- 표시 ----------
    def draw(self):
        for p in self.patches:
            p.remove()
        self.patches = []
        if self.polys:
            for z, loops in self.polys.items():
                for pts, hl in loops:
                    self.patches.append(self.ax.fill(
                        *zip(*pts), fc="white" if hl else self.cmap(z % 20),
                        alpha=0.35, ec="crimson", lw=1.3, zorder=1)[0])
        self.sc.set_facecolors(np.array(
            [self.cmap(v % 20) if v >= 0 else (.78, .78, .78, 1.)
             for v in self.lab]))
        nz = len(np.unique(self.lab[self.lab >= 0]))
        sl = f"  slot:{self.slot+1}" if self.slot is not None else ""
        self.ax.set_title(
            f"method: {self.method}   frac: {CLEAR_FRAC:.2f}   "
            f"zone: {self.cur}   zones: {nz}   "
            f"unassigned: {int((self.lab < 0).sum())}{sl}", fontsize=11)
        self.ax.set_autoscale_on(False)
        self.ax.set_xlim(X1, X2)
        self.ax.set_ylim(Y1, Y2)
        self.ax.set_aspect("equal", adjustable="box")
        if self.on_state is not None:
            try:
                self.on_state(self)
            except Exception:
                pass
        self.fig.canvas.draw_idle()


def main():
    """단독 실행: 모듈 상단 설정값으로 bump 파일을 읽어 창을 띄운다."""
    xy, half = load(BUMP_FILE, D_DEFAULT)
    log(f"bumps = {len(xy)}")
    App(xy, half)
    plt.show()


if __name__ == "__main__":
    main()
