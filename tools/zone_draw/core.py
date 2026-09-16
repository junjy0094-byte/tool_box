# -*- coding: utf-8 -*-
"""zone_draw core ― AutoCAD 방식으로 zone 폴리곤을 직접 그리는 엔진.

  · 좌클릭으로 점을 찍으면 직선이 이어짐. 첫 점을 다시 클릭하면 폴리곤 완성
  · 스냅: 정점 / 범프 사각형 / 라인 위(중점·수선) / 여유중심 / 격자 / 외곽선
  · 직교모드, 러버밴드 미리보기, 길이·각도 표시
  · 범프는 실제 변 길이를 가진 사각형으로 표시
  · 최외곽에 닿는 폴리곤은 박스 둘레를 따라 자동 fit, 남은 영역 자동 채우기
  · APDL 출력 시 존 간 공유 KP/LINE 을 명시 생성하고, 범프 접점에서 라인을 분할
  · 모든 기하 톨러런스는 패키지 스케일(GTOL)에 비례 ― mm/um 단위 무관

출력: labels.txt / bumps.mac / zones.mac / run.mac / zones.png / polys.npz
필요: numpy, scipy, matplotlib, shapely

원본 단독 스크립트에서 바뀐 점은 두 가지뿐이다.
  1. 모듈 상단 상수를 ``configure(**kwargs)`` 로 주입할 수 있게 했다.
     (GUI 가 설정값을 넘겨준 뒤 엔진을 띄우는 구조)
  2. ``print`` 대신 ``log`` 를 써서 GUI 로그 창으로도 메시지가 흐르게 했다.
     ``App`` 은 외부에서 만든 Figure/Axes 를 받아 tkinter 창에 임베드할 수 있다.
"""
import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as MplPolygon, Rectangle
from matplotlib.path import Path
from scipy.spatial import cKDTree
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree

# ============================================================
# 설정 ― GUI 가 configure() 로 덮어쓴다
# ============================================================
BUMP_FILE = "bump.txt"          # 헤더 1줄 + "idx,x,y[,D]"
POLY_FILE = "polys.npz"
OUT_DIR   = ""                  # 결과 파일이 저장될 폴더. ""이면 현재 폴더
D_DEFAULT = 0.25
X1, X2 = 0.0, 16000.0           # 패키지 외곽
Y1, Y2 = 0.0, 26000.0

GTOL_FRAC = 1e-9                # GTOL = SCALE * GTOL_FRAC
GRID_FRAC = 0.001               # GRID = SCALE * GRID_FRAC

SNAP_PIX  = 12                  # 스냅 반응 반경 (픽셀)
EDGE_PIX  = 14                  # 외곽선 흡착 반경 (픽셀)
ORTHO     = False
CELL      = None                # 여유중심 스냅용 거리장 셀. None이면 자동

EDGE_DIV  = 3                   # 범프 한 변당 요소 분할수
MESH_TRI  = True
ATOL_FRAC = 1e-4                # sliver 판정: 범프 면적 대비 비율

# ---- 파생값 (configure() 가 다시 계산한다) ----
W_, H_ = X2 - X1, Y2 - Y1
PERIM  = 2 * (W_ + H_)
SCALE  = max(W_, H_)
GTOL   = SCALE * GTOL_FRAC      # 기하 스냅/양자화 톨러런스
GRID   = SCALE * GRID_FRAC      # 격자 스냅 간격

_CONFIG_KEYS = (
    "BUMP_FILE", "POLY_FILE", "OUT_DIR", "D_DEFAULT",
    "X1", "X2", "Y1", "Y2", "GTOL_FRAC", "GRID_FRAC",
    "SNAP_PIX", "EDGE_PIX", "ORTHO", "CELL",
    "EDGE_DIV", "MESH_TRI", "ATOL_FRAC",
)


def _update_derived() -> None:
    g = globals()
    g["W_"] = X2 - X1
    g["H_"] = Y2 - Y1
    g["PERIM"] = 2 * (g["W_"] + g["H_"])
    g["SCALE"] = max(g["W_"], g["H_"])
    g["GTOL"] = g["SCALE"] * GTOL_FRAC
    g["GRID"] = g["SCALE"] * GRID_FRAC


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


def poly_path() -> str:
    """폴리곤 저장 파일 경로 (절대 경로면 그대로, 아니면 OUT_DIR 기준)."""
    return POLY_FILE if os.path.isabs(POLY_FILE) else out_path(POLY_FILE)


def disable_default_keymap() -> None:
    """matplotlib 기본 단축키를 꺼서 도구 단축키와 충돌하지 않게 한다."""
    for _k in list(plt.rcParams):
        if _k.startswith("keymap."):
            plt.rcParams[_k] = []


HELP = """
[ 마우스 ]
  좌클릭      점 찍기 (스냅 적용). 첫 점을 다시 클릭하면 폴리곤 완성
  우클릭      현재 폴리라인 취소
  휠          확대·축소            휠드래그  화면 이동
[ 그리기 ]
  Backspace   직전 점 취소         Esc  폴리라인 취소
  c           첫 점과 직선으로 닫기
  e / E       양 끝이 외곽선에 있을 때 박스 둘레를 따라 닫기 (반시계 / 시계)
  o           직교모드 on/off
[ 스냅 토글 ]
  1 정점  2 범프  3 여유중심  4 격자  5 외곽선  6 라인 위  0 전부 끄기
[ 폴리곤 ]
  f           남은 영역을 자동으로 폴리곤화
  d           번호를 입력해 특정 폴리곤 삭제 (Enter 확정 / Esc 취소)
  x           마지막 폴리곤 삭제   X  전체 삭제
  v           검증                 z  화면 전체 보기
  b           진단 표시 on/off (빨강=가로지름, 주황=경계접촉)
[ 화면 ]
  방향키      이동 (Shift+방향키 = 크게 이동)
[ 파일 ]
  w 폴리곤 저장   r 폴리곤 불러오기   s APDL 매크로 저장   h 도움말
"""


def load(path, d):
    dat = np.loadtxt(path, delimiter=",", skiprows=1)
    dat = np.atleast_2d(dat)
    xy = dat[:, 1:3].astype(float)
    D = dat[:, 3].astype(float) if dat.shape[1] >= 4 \
        else np.full(len(xy), d, float)
    return xy, D * np.sqrt(np.pi) / 4.0      # 등가 사각볼 반변


def qz(c):
    """GTOL 격자로 좌표 양자화 ― 인접 폴리곤이 같은 값을 갖게 함"""
    return (round(float(c[0]) / GTOL) * GTOL,
            round(float(c[1]) / GTOL) * GTOL)


# ============================================================
# 박스 둘레 파라미터 (CCW, t=0 이 좌하단)
# ============================================================
def on_box(p, tol=None):
    tol = GTOL * 10 if tol is None else tol
    return (abs(p[0]-X1) < tol or abs(p[0]-X2) < tol or
            abs(p[1]-Y1) < tol or abs(p[1]-Y2) < tol)


def t_of(p):
    tol = GTOL * 10
    x, y = p
    if abs(y - Y1) < tol and abs(x - X2) >= tol:  return x - X1
    if abs(x - X2) < tol and abs(y - Y2) >= tol:  return W_ + (y - Y1)
    if abs(y - Y2) < tol and abs(x - X1) >= tol:  return W_ + H_ + (X2 - x)
    if abs(x - X1) < tol:                         return 2*W_ + H_ + (Y2 - y)
    return 0.0


def p_of(t):
    t = t % PERIM
    if t <= W_:        return (X1 + t, Y1)
    if t <= W_ + H_:   return (X2, Y1 + (t - W_))
    if t <= 2*W_ + H_: return (X2 - (t - W_ - H_), Y2)
    return (X1, Y2 - (t - 2*W_ - H_))


def arc_points(ta, tb, ccw):
    """ta → tb 로 박스 둘레를 따라갈 때 지나는 코너들"""
    cor = [0.0, W_, W_ + H_, 2*W_ + H_]
    out = []
    if ccw:
        span = (tb - ta) % PERIM
        while True:
            nxt = None
            for c in cor:
                dd = (c - ta) % PERIM
                if 1e-9 < dd < span - 1e-9 and (nxt is None or dd < nxt[0]):
                    nxt = (dd, c)
            if nxt is None:
                break
            out.append(p_of(nxt[1]))
            ta = nxt[1]
            span = (tb - ta) % PERIM
            if len(out) > 8:
                break
    else:
        span = (ta - tb) % PERIM
        while True:
            nxt = None
            for c in cor:
                dd = (ta - c) % PERIM
                if 1e-9 < dd < span - 1e-9 and (nxt is None or dd < nxt[0]):
                    nxt = (dd, c)
            if nxt is None:
                break
            out.append(p_of(nxt[1]))
            ta = nxt[1]
            span = (ta - tb) % PERIM
            if len(out) > 8:
                break
    return out


def snap_to_box(p, tol):
    x, y = p
    if abs(x - X1) < tol: x = X1
    elif abs(x - X2) < tol: x = X2
    if abs(y - Y1) < tol: y = Y1
    elif abs(y - Y2) < tol: y = Y2
    return (min(max(x, X1), X2), min(max(y, Y1), Y2))


def area_of(pts):
    n = len(pts)
    return 0.5 * abs(sum(pts[k][0]*pts[(k+1) % n][1] -
                         pts[(k+1) % n][0]*pts[k][1] for k in range(n)))


def qidx(tree, geoms, g):
    r = np.asarray(tree.query(g))
    if r.size == 0:
        return []
    if np.issubdtype(r.dtype, np.integer):
        return r.tolist()
    return [geoms.index(x) for x in r]


def runs(v):
    v = sorted(set(int(q) for q in v))
    out, s, p = [], v[0], v[0]
    for q in v[1:] + [None]:
        if q == p + 1:
            p = q; continue
        out.append((s, p))
        if q is not None:
            s = p = q
    return out


# ============================================================
# 스냅 엔진
# ============================================================
class Snapper:
    def __init__(self, xy, half, cell):
        pts = []
        for (x, y), h in zip(xy, half):
            pts += [(x-h, y-h), (x+h, y-h), (x+h, y+h), (x-h, y+h),
                    (x, y-h), (x+h, y), (x, y+h), (x-h, y), (x, y)]
        self.bpts = np.asarray(pts)
        self.btree = cKDTree(self.bpts)

        nx = max(1, int(np.ceil(W_ / cell)))
        ny = max(1, int(np.ceil(H_ / cell)))
        self.dx, self.dy, self.nx, self.ny = W_/nx, H_/ny, nx, ny
        m = np.zeros((ny, nx), bool)
        for (x, y), h in zip(xy, half):
            i0 = int(np.clip(np.floor((x-h-X1)/self.dx + 1e-9), 0, nx-1))
            i1 = int(np.clip(np.floor((x+h-X1)/self.dx - 1e-9), 0, nx-1))
            j0 = int(np.clip(np.floor((y-h-Y1)/self.dy + 1e-9), 0, ny-1))
            j1 = int(np.clip(np.floor((y+h-Y1)/self.dy - 1e-9), 0, ny-1))
            m[j0:j1+1, i0:i1+1] = True
        self.dist = distance_transform_edt(~m, sampling=(self.dy, self.dx))

    def clearance(self, p, rad):
        i = int(np.clip((p[0]-X1)/self.dx, 0, self.nx-1))
        j = int(np.clip((p[1]-Y1)/self.dy, 0, self.ny-1))
        ri = max(1, int(rad/self.dx)); rj = max(1, int(rad/self.dy))
        i0, i1 = max(0, i-ri), min(self.nx, i+ri+1)
        j0, j1 = max(0, j-rj), min(self.ny, j+rj+1)
        w = self.dist[j0:j1, i0:i1]
        if w.size == 0:
            return None
        k = np.unravel_index(int(np.argmax(w)), w.shape)
        return (X1 + (i0+k[1]+0.5)*self.dx, Y1 + (j0+k[0]+0.5)*self.dy)


# ============================================================
# 메인
# ============================================================
class App:
    def __init__(self, xy, half, fig=None, ax=None):
        disable_default_keymap()
        self.xy, self.half = xy, half
        self.polys = []
        self.chain = []
        self.ortho = ORTHO
        self.snapmode = {1: True, 2: True, 3: True, 4: True, 5: True, 6: True}
        self.lab = np.full(len(xy), -1, int)
        self.snap = Snapper(xy, half, CELL if CELL else half.min()/2.5)
        self.sqgeom = [box(x-h, y-h, x+h, y+h)
                       for (x, y), h in zip(xy, half)]
        self.sqtree = STRtree(self.sqgeom)
        self.cmap = plt.get_cmap("tab20")
        self.pan = None
        self.cursor = None
        self.stype = ""
        self.delbuf = None
        self.diag = False               # 진단 표시 on/off
        self.dpatch = []                # 진단 아티스트
        self.pan_step = 0.12

        if fig is None or ax is None:
            self.fig, self.ax = plt.subplots(figsize=(11.5, 10.5))
        else:
            self.fig, self.ax = fig, ax
        self.fig._zone_draw_app = self          # GC 방지 앵커
        self.ax.set_aspect("equal", adjustable="box")
        self.cx, self.cy, self.hw = 0.5*(X1+X2), 0.5*(Y1+Y2), 0.55*W_
        self.apply_view()

        verts = np.empty((len(xy), 4, 2))
        verts[:, 0] = xy - half[:, None]
        verts[:, 1] = np.c_[xy[:, 0]+half, xy[:, 1]-half]
        verts[:, 2] = xy + half[:, None]
        verts[:, 3] = np.c_[xy[:, 0]-half, xy[:, 1]+half]
        self.bumps = PolyCollection(verts, facecolors="0.80",
                                    edgecolors="0.45", linewidths=0.35,
                                    zorder=2, rasterized=True)
        self.ax.add_collection(self.bumps)
        self.ax.add_patch(Rectangle((X1, Y1), W_, H_, fill=False,
                                    ec="k", lw=1.6, zorder=6))

        self.zpatch = []
        self.pl = Line2D([], [], color="crimson", lw=1.8, marker="o",
                         ms=4, zorder=7)
        self.rb = Line2D([], [], color="crimson", lw=1.0, ls="--", zorder=7)
        self.mk = Line2D([], [], color="lime", marker="+", ms=16,
                         mew=2.0, ls="none", zorder=8)
        for a in (self.pl, self.rb, self.mk):
            self.ax.add_line(a)
        self.txt = self.ax.text(0.01, 0.99, "", transform=self.ax.transAxes,
                                va="top", ha="left", fontsize=9, zorder=9,
                                family="monospace",
                                bbox=dict(fc="w", alpha=.8, lw=0))

        c = self.fig.canvas
        self._cids = [
            c.mpl_connect("button_press_event", self.on_press),
            c.mpl_connect("button_release_event", self.on_release),
            c.mpl_connect("motion_notify_event", self.on_move),
            c.mpl_connect("scroll_event", self.on_scroll),
            c.mpl_connect("key_press_event", self.on_key),
        ]
        try:
            c.setFocusPolicy(2); c.setFocus()
        except Exception:
            pass
        log(HELP)
        log(f"[i] SCALE={SCALE:g}  GTOL={GTOL:g}  GRID={GRID:g}")
        log(f"[i] 범프 {len(xy)}개, 반변 중앙값 {float(np.median(half)):g}")
        if os.path.exists(poly_path()):
            log(f"[i] {poly_path()} 있음 ― r 로 불러올 수 있다")
        self.redraw()

    # ---------- 화면 ----------
    def apply_view(self):
        bb = self.ax.get_window_extent()
        r = (bb.height / bb.width) if bb.width > 0 else 1.0
        self.ax.set_xlim(self.cx - self.hw, self.cx + self.hw)
        self.ax.set_ylim(self.cy - self.hw*r, self.cy + self.hw*r)

    def zoom_all(self):
        self.cx, self.cy, self.hw = 0.5*(X1+X2), 0.5*(Y1+Y2), 0.55*W_
        self.apply_view()
        self.fig.canvas.draw_idle()

    def pix(self, n):
        inv = self.ax.transData.inverted()
        a = inv.transform((0, 0)); b = inv.transform((n, 0))
        return abs(b[0] - a[0])

    def pan_by(self, dx, dy):
        bb = self.ax.get_window_extent()
        r = (bb.height / bb.width) if bb.width > 0 else 1.0
        self.cx += dx * self.hw * self.pan_step * 2
        self.cy += dy * self.hw * r * self.pan_step * 2
        self.apply_view()
        self.fig.canvas.draw_idle()

    def on_scroll(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        s = 1/1.25 if ev.button == "up" else 1.25
        self.cx = ev.xdata + (self.cx - ev.xdata) * s
        self.cy = ev.ydata + (self.cy - ev.ydata) * s
        self.hw = float(np.clip(self.hw * s, 1e-6*W_, 5*W_))
        self.apply_view()
        self.fig.canvas.draw_idle()

    # ---------- 스냅 ----------
    def _segments(self):
        segs = []
        for pg in self.polys:
            n = len(pg)
            for i in range(n):
                segs.append((pg[i], pg[(i+1) % n]))
        for i in range(len(self.chain)-1):
            segs.append((self.chain[i], self.chain[i+1]))
        return segs

    def snap_line(self, x, y, tol):
        segs = self._segments()
        if not segs:
            return None, 1e18, ""
        A = np.asarray([s[0] for s in segs], float)
        B = np.asarray([s[1] for s in segs], float)
        M = 0.5 * (A + B)
        d = np.hypot(M[:, 0]-x, M[:, 1]-y)
        k = int(d.argmin())
        if d[k] < tol:
            return tuple(M[k]), d[k], "midpoint"
        AB = B - A
        L2 = (AB*AB).sum(1)
        L2[L2 < 1e-24] = 1e-24
        t = np.clip(((np.array([x, y]) - A) * AB).sum(1) / L2, 0.0, 1.0)
        Q = A + AB * t[:, None]
        d = np.hypot(Q[:, 0]-x, Q[:, 1]-y)
        k = int(d.argmin())
        if d[k] < tol:
            return tuple(Q[k]), d[k], "on-line"
        return None, 1e18, ""

    def do_snap(self, x, y):
        tol = self.pix(SNAP_PIX)
        etol = self.pix(EDGE_PIX)
        best, bd, tag = (x, y), 1e18, "free"

        if self.snapmode[1] and (self.polys or self.chain):
            v = np.asarray([p for pg in self.polys for p in pg] + self.chain,
                           float)
            d = np.hypot(v[:, 0]-x, v[:, 1]-y)
            k = int(d.argmin())
            if d[k] < tol:
                best, bd, tag = tuple(v[k]), d[k], "vertex"

        if self.snapmode[2] and bd > 1e17:
            d, k = self.snap.btree.query([x, y])
            if d < tol:
                best, bd, tag = tuple(self.snap.bpts[k]), d, "bump"

        if self.snapmode[6] and bd > 1e17:
            q, d, nm = self.snap_line(x, y, tol)
            if q is not None:
                best, bd, tag = q, d, nm

        if self.snapmode[3] and bd > 1e17:
            q = self.snap.clearance((x, y), tol)
            if q is not None:
                d = np.hypot(q[0]-x, q[1]-y)
                if d < tol:
                    best, bd, tag = q, d, "clearance"

        if self.snapmode[4] and bd > 1e17 and GRID > 0:
            q = (round(x/GRID)*GRID, round(y/GRID)*GRID)
            if np.hypot(q[0]-x, q[1]-y) < tol:
                best, tag = q, "grid"

        if self.snapmode[5]:
            q = snap_to_box(best, etol)
            if q != best:
                best = q
                tag = "box" if tag == "free" else tag + "+box"
            else:
                best = (min(max(best[0], X1), X2), min(max(best[1], Y1), Y2))

        if self.ortho and self.chain and tag in ("free", "grid"):
            px, py = self.chain[-1]
            best = (best[0], py) if abs(best[0]-px) >= abs(best[1]-py) \
                else (px, best[1])
            tag += "|ortho"
        self.stype = tag
        return best

    # ---------- 마우스 ----------
    def on_press(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        if ev.button == 2:
            self.pan = (ev.xdata, ev.ydata, self.cx, self.cy)
            return
        if ev.button == 3:
            self.chain = []
            self.redraw(); return
        if ev.button != 1:
            return
        p = self.do_snap(ev.xdata, ev.ydata)
        if len(self.chain) >= 3:
            d = np.hypot(p[0]-self.chain[0][0], p[1]-self.chain[0][1])
            if d < self.pix(SNAP_PIX):
                self.close_direct(); return
        if self.chain and np.hypot(p[0]-self.chain[-1][0],
                                   p[1]-self.chain[-1][1]) < GTOL:
            return
        self.chain.append(p)
        self.redraw()

    def on_release(self, ev):
        if ev.button == 2:
            self.pan = None

    def on_move(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        if self.pan is not None:
            x0, y0, cx0, cy0 = self.pan
            self.cx = cx0 - (ev.xdata - x0)
            self.cy = cy0 - (ev.ydata - y0)
            self.apply_view()
            self.fig.canvas.draw_idle()
            return
        p = self.do_snap(ev.xdata, ev.ydata)
        self.cursor = p
        self.mk.set_data([p[0]], [p[1]])
        if self.chain:
            a = self.chain[-1]
            self.rb.set_data([a[0], p[0]], [a[1], p[1]])
        else:
            self.rb.set_data([], [])
        self.status()
        self.fig.canvas.draw_idle()

    # ---------- 폴리곤 ----------
    def commit(self, pts):
        pts = [p for i, p in enumerate(pts)
               if i == 0 or np.hypot(p[0]-pts[i-1][0],
                                     p[1]-pts[i-1][1]) > GTOL]
        if len(pts) >= 2 and np.hypot(pts[0][0]-pts[-1][0],
                                      pts[0][1]-pts[-1][1]) < GTOL:
            pts = pts[:-1]
        if len(pts) < 3 or area_of(pts) < (SCALE*GTOL):
            log("[!] 유효한 폴리곤이 아니다"); return
        self.polys.append([tuple(map(float, p)) for p in pts])
        self.chain = []
        log(f"[polygon {len(self.polys)-1}] 정점 {len(pts)}, "
            f"면적 {area_of(pts):.4f}")
        self.assign()
        self.redraw()

    def close_direct(self):
        if len(self.chain) < 3:
            log("[!] 점이 3개 이상 필요하다"); return
        self.commit(list(self.chain))

    def close_box(self, ccw):
        if len(self.chain) < 2:
            log("[!] 점이 2개 이상 필요하다"); return
        a, b = self.chain[0], self.chain[-1]
        if not (on_box(a) and on_box(b)):
            log("[!] 시작점과 끝점이 모두 외곽선 위에 있어야 한다"); return
        self.commit(list(self.chain) + arc_points(t_of(b), t_of(a), ccw))

    def autofill(self):
        if not self.polys:
            log("[!] 폴리곤이 없다"); return
        bx = box(X1, Y1, X2, Y2)
        u = unary_union([Polygon(p).buffer(0) for p in self.polys])
        rest = bx.difference(u)
        if rest.is_empty:
            log("[fill] 남은 영역 없음"); return
        parts = rest.geoms if rest.geom_type == "MultiPolygon" else [rest]
        n = 0
        for g in parts:
            if g.area < (W_*H_) * 1e-9:
                continue
            pts = [tuple(c) for c in g.exterior.coords[:-1]]
            if len(pts) >= 3:
                self.polys.append(pts); n += 1
            if list(g.interiors):
                log("[!] 구멍이 있는 조각 ― 수동 분할이 필요할 수 있다")
        log(f"[fill] {n}개 폴리곤 추가 (총 {len(self.polys)})")
        self.assign()
        self.redraw()

    def delete_poly(self, z):
        if not (0 <= z < len(self.polys)):
            log(f"[!] 범위는 0~{len(self.polys)-1}"); return
        self.polys.pop(z)
        self.assign()
        log(f"[del] polygon {z} 삭제 → 남은 {len(self.polys)}개 (번호 재부여)")
        self.redraw()

    def del_input(self, k):
        if k in ("escape", "d"):
            self.delbuf = None
            log("[del] 취소")
        elif k in ("enter", "return"):
            if self.delbuf:
                self.delete_poly(int(self.delbuf))
            self.delbuf = None
        elif k == "backspace":
            self.delbuf = self.delbuf[:-1]
        elif k and k.isdigit():
            self.delbuf += k
        if self.delbuf is not None:
            log(f"[del] 번호: {self.delbuf or '_'}  (Enter 확정 / Esc 취소)")
        self.status()
        self.fig.canvas.draw_idle()

    # ---------- 범프 귀속 / 검증 ----------
    def assign(self):
        self.lab[:] = -1
        for z, pg in enumerate(self.polys):
            m = Path(np.asarray(pg)).contains_points(self.xy)
            self.lab[(self.lab < 0) & m] = z

    def zone_polys(self):
        out = []
        for p in self.polys:
            g = Polygon(p)
            out.append(g if g.is_valid else g.buffer(0))
        return out

    def tangent_bumps(self, pgs):
        """존 경계와 변/점을 공유(tangent)하는 범프 / 실제로 내부를 지나는 범프"""
        tang, cross = set(), set()
        inset = GTOL * 100
        for g in pgs:
            bnd = g.boundary
            for k in qidx(self.sqtree, self.sqgeom, bnd):
                s = self.sqgeom[k]
                if not s.intersects(bnd):
                    continue
                tang.add(int(k))
                if s.buffer(-inset).intersects(bnd):
                    cross.add(int(k))
        return tang, cross

    def validate(self):
        self.assign()
        pgs = self.zone_polys()
        ov = 0.0
        for i in range(len(pgs)):
            for j in range(i+1, len(pgs)):
                a = pgs[i].intersection(pgs[j]).area
                if a > (W_*H_) * 1e-9:
                    ov += a
                    log(f"[!] zone {i} 와 {j} 가 {a:.6f} 겹친다")
        tang, cross = self.tangent_bumps(pgs)
        tot = sum(g.area for g in pgs)
        log(f"[check] 폴리곤 {len(pgs)}, 존간 겹침 {ov:.6f}, "
            f"경계 접촉 범프 {len(tang)}, 가로지름 {len(cross)}, "
            f"미할당 {int((self.lab<0).sum())}, "
            f"면적합 {tot:.4f} / {W_*H_:.4f} (차 {tot-W_*H_:+.4f})")
        if cross:
            log(f"        가로지름 예: {sorted(cross)[:10]}")
        return tang, cross

    # ---------- 파일 ----------
    def save_polys(self):
        if not self.polys:
            log("[!] 저장할 폴리곤이 없다"); return
        path = poly_path()
        np.savez(path, n=len(self.polys),
                 **{f"p{i}": np.asarray(p) for i, p in enumerate(self.polys)})
        log(f"[save] {path}  ({len(self.polys)} polygons)")

    def load_polys(self):
        path = poly_path()
        if not os.path.exists(path):
            log(f"[!] {path} 없음"); return
        d = np.load(path)
        self.polys = [[tuple(c) for c in d[f"p{i}"]]
                      for i in range(int(d["n"]))]
        self.chain = []
        log(f"[load] {len(self.polys)} polygons")
        self.assign()
        self.redraw()

    # ============================================================
    # APDL 출력
    # ============================================================
    def build_faces(self, pgs):
        """존 경계 + 박스를 노딩해 면으로 재구성. 미소속 조각은 최근접 존에 흡수"""
        lines = [box(X1, Y1, X2, Y2).boundary] + [g.boundary for g in pgs]
        try:
            noded = unary_union(lines, grid_size=GTOL)
        except TypeError:                       # shapely < 2.0
            noded = unary_union(lines)

        amin = (W_ * H_) * 1e-10
        faces = [f for f in polygonize(noded) if f.area > amin]

        per, orphan_area, orphan_n = {}, 0.0, 0
        for f in faces:
            p = f.representative_point()
            z = next((i for i, g in enumerate(pgs) if g.covers(p)), None)
            if z is None:
                z = int(np.argmin([g.distance(p) for g in pgs]))
                orphan_area += f.area
                orphan_n += 1
            per.setdefault(z, []).append(f)

        if orphan_n:
            log(f"[faces] 미소속 조각 {orphan_n}개, 면적 {orphan_area:.4f} "
                f"({100*orphan_area/(W_*H_):.6f}%) → 최근접 존에 흡수")

        out = []
        for z in sorted(per):
            g = unary_union(per[z])
            out.append((z, g if g.is_valid else g.buffer(0)))
        return out

    def split_ring(self, coords):
        """범프 사각형과 만나는 지점에서 링을 추가 분할"""
        out = []
        n = len(coords)
        for i in range(n):
            a = np.asarray(coords[i], float)
            b = np.asarray(coords[(i+1) % n], float)
            seg = LineString([a, b])
            L = np.hypot(*(b-a))
            if L < GTOL:
                continue
            ts = []
            for k in qidx(self.sqtree, self.sqgeom, seg):
                inter = self.sqgeom[k].boundary.intersection(seg)
                if inter.is_empty:
                    continue
                gs = inter.geoms if hasattr(inter, "geoms") else [inter]
                for g in gs:
                    cs = [(g.x, g.y)] if g.geom_type == "Point" \
                        else list(g.coords)
                    for c in cs:
                        t = float(np.dot(np.asarray(c) - a, b - a) / (L*L))
                        if 1e-9 < t < 1 - 1e-9:
                            ts.append(t)
            out.append(tuple(a))
            for t in sorted(set(round(v, 12) for v in ts)):
                out.append(tuple(a + (b - a) * t))
        res = []
        for p in out:
            q = qz(p)
            if not res or q != res[-1]:
                res.append(q)
        if len(res) > 1 and res[0] == res[-1]:
            res = res[:-1]
        return res

    def topology(self, zpolys):
        kp, edge, kl, rings = {}, {}, [], {}

        def kid(c):
            q = qz(c)
            if q not in kp:
                kp[q] = len(kp) + 1
            return kp[q]

        for z, g in zpolys:
            parts = g.geoms if g.geom_type == "MultiPolygon" else [g]
            rr = []
            for pg in parts:
                # pg.exterior 는 접근마다 새 객체를 반환하므로 is 비교 금지.
                # 리스트의 첫 원소가 외곽 링이라는 사실을 인덱스로 판정한다.
                rlist = [pg.exterior] + list(pg.interiors)
                for ri, ring in enumerate(rlist):
                    pts = self.split_ring(list(ring.coords[:-1]))
                    ids = [kid(c) for c in pts]
                    ids = [v for i, v in enumerate(ids)
                           if i == 0 or v != ids[i-1]]
                    if len(ids) > 1 and ids[0] == ids[-1]:
                        ids = ids[:-1]
                    if len(ids) < 3:
                        continue
                    ln = []
                    for i in range(len(ids)):
                        a, b = ids[i], ids[(i+1) % len(ids)]
                        if a == b:
                            continue
                        key = frozenset((a, b))
                        if key not in edge:
                            edge[key] = len(edge) + 1
                            kl.append((a, b))
                        ln.append(edge[key])
                    rr.append((ri == 0, ln))
            rings[z] = rr
        pts = [None] * len(kp)
        for q, i in kp.items():
            pts[i-1] = q
        return pts, kl, rings

    # ---------- 진단 표시 ----------
    def draw_diag(self):
        """경계 접촉 / 가로지름 범프를 화면에 표시 (b 키로 토글)"""
        if not self.diag or not self.polys:
            return
        pgs = self.zone_polys()
        tang, cross = self.tangent_bumps(pgs)
        for k in sorted(tang - cross):
            x, y = self.xy[k]; h = self.half[k]
            self.dpatch.append(self.ax.add_patch(Rectangle(
                (x-h, y-h), 2*h, 2*h, fill=False, ec="darkorange",
                lw=1.6, zorder=9)))
        show_txt = len(cross) <= 200
        for k in sorted(cross):
            x, y = self.xy[k]; h = self.half[k]
            self.dpatch.append(self.ax.add_patch(Rectangle(
                (x-h, y-h), 2*h, 2*h, fill=False, ec="red",
                lw=2.4, zorder=10)))
            if show_txt:
                self.dpatch.append(self.ax.text(
                    x, y+h, str(k+1), color="red", fontsize=8,
                    ha="center", va="bottom", zorder=10,
                    bbox=dict(fc="w", alpha=.7, pad=0.5, lw=0)))

    # ---------- 화면 갱신 ----------
    def redraw(self):
        for a in self.zpatch + self.dpatch:
            try:
                a.remove()
            except Exception:
                pass
        self.zpatch, self.dpatch = [], []

        for z, pg in enumerate(self.polys):
            col = self.cmap(z % 20)
            arr = np.asarray(pg, float)
            self.zpatch.append(self.ax.add_patch(MplPolygon(
                arr, closed=True, fc=col, ec=col, alpha=0.28,
                lw=1.6, zorder=3)))
            c = arr.mean(0)
            self.zpatch.append(self.ax.text(
                c[0], c[1], str(z), color="k", fontsize=11, fontweight="bold",
                ha="center", va="center", zorder=5,
                bbox=dict(fc="w", alpha=.6, pad=1.0, lw=0)))

        cols = np.tile(np.asarray(to_rgba("0.80")), (len(self.xy), 1))
        for z in range(len(self.polys)):
            m = self.lab == z
            if m.any():
                cols[m] = self.cmap(z % 20)
        self.bumps.set_facecolors(cols)

        if self.chain:
            xs = [p[0] for p in self.chain]
            ys = [p[1] for p in self.chain]
            self.pl.set_data(xs, ys)
        else:
            self.pl.set_data([], [])
            self.rb.set_data([], [])

        self.draw_diag()
        self.status()
        self.fig.canvas.draw_idle()

    def status(self):
        on = "".join(str(i) for i in sorted(self.snapmode) if self.snapmode[i])
        lines = [f"polygons {len(self.polys)}   chain {len(self.chain)}   "
                 f"ortho {'ON' if self.ortho else 'OFF'}   "
                 f"snap [{on or '-'}]   diag {'ON' if self.diag else 'OFF'}"]
        if self.cursor is not None:
            x, y = self.cursor
            s = f"x {x:.3f}  y {y:.3f}  ({self.stype})"
            if self.chain:
                ax_, ay = self.chain[-1]
                dx, dy = x - ax_, y - ay
                s += (f"   L {np.hypot(dx, dy):.3f}"
                      f"  A {np.degrees(np.arctan2(dy, dx)):+.2f}deg")
            lines.append(s)
        if self.delbuf is not None:
            lines.append(f"삭제할 폴리곤 번호: {self.delbuf or '_'}"
                         "   (Enter 확정 / Esc 취소)")
        self.txt.set_text("\n".join(lines))

    # ---------- APDL ----------
    def save_apdl(self):
        if not self.polys:
            log("[!] 폴리곤이 없다"); return
        self.assign()
        bad = np.flatnonzero(self.lab < 0)
        if len(bad):
            pgs0 = self.zone_polys()
            for b in bad:
                self.lab[b] = int(np.argmin(
                    [g.distance(Point(self.xy[b])) for g in pgs0]))
            log(f"[fit] 미할당 범프 {len(bad)}개를 최근접 존에 귀속")

        pgs = self.zone_polys()
        zp = self.build_faces(pgs)                      # [(z, geom), ...]
        zp_geoms = [g for _, g in zp]
        tang, cross = self.tangent_bumps(zp_geoms)
        log(f"[fit] 경계 걸침 범프 {len(tang)}개(교차 {len(cross)}개 포함) "
            "→ 컨테이너 외곽에서 직접 절개, ASBA 대상에서 제외")

        # ---- 경계에 걸친 범프는 ASBA 가 아니라, 컨테이너 폴리곤 자체에서
        #      shapely.difference 로 미리 도려낸다. 즉 zone 외곽 Line 을
        #      처음부터 그 범프를 피해가도록 만들어 저장한다 ----
        if tang:
            carve = unary_union([self.sqgeom[k] for k in tang])
            zp2 = []
            for z, g in zp:
                gc = g.difference(carve)
                if gc.is_empty:
                    log(f"[!] zone {z}: 경계 범프 절개 후 영역이 사라짐 "
                        "― 원본 유지, 수동 확인 필요")
                    gc = g
                zp2.append((z, gc if gc.is_valid else gc.buffer(0)))
            self.diag = True
            self.redraw()
        else:
            zp2 = zp

        pts, kl, rings = self.topology(zp2)
        log(f"[topo] KP {len(pts)}, LINE {len(kl)}, zones {len(zp2)}")

        nsq = len(self.xy)
        np.savetxt(out_path("labels.txt"),
                   np.column_stack([np.arange(1, nsq+1), self.xy, self.lab]),
                   delimiter=",", fmt=["%d", "%.6f", "%.6f", "%d"],
                   header="idx,x,y,zone")

        with open(out_path("bumps.mac"), "w") as f:
            f.write("/PREP7\n/NOPR\nNUMSTR,DEFA\nBOPTN,NUMB,OFF\n")
            for (x, y), h in zip(self.xy, self.half):
                f.write(f"RECTNG,{x-h:.6f},{x+h:.6f},{y-h:.6f},{y+h:.6f}\n")
            f.write("/GOPR\nALLSEL,ALL\nCM,SQ,AREA\n")

        # ---- zones.mac : 컨테이너 생성(범프 절개 반영) → 홀 차감
        #      → 경계 미접촉 범프만 ASBA 차감 ----
        with open(out_path("zones.mac"), "w") as f:
            f.write(f"/PREP7\nNSQ = {nsq}\nBOPTN,NUMB,OFF\nBOPTN,KEEP,NO\n")
            f.write("*GET,KB,KP,0,NUM,MAX\n*GET,LB,LINE,0,NUM,MAX\n"
                    "KB1 = KB+1\nLB1 = LB+1\n"
                    "NUMSTR,KP,KB1\nNUMSTR,LINE,LB1\n")
            f.write(f"\n! ---- shared keypoints : {len(pts)} ----\n")
            for x, y in pts:
                f.write(f"K,,{x:.6f},{y:.6f},0\n")
            f.write(f"\n! ---- shared lines : {len(kl)} ----\n")
            for a, b in kl:
                f.write(f"L,KB+{a},KB+{b}\n")
            f.write("NUMSTR,DEFA\nALLSEL,ALL\n")

            zids = sorted(z for z, rr in rings.items()
                          if any(isout for isout, _ in rr))
            ndim = max(zids) + 1 if zids else 1
            f.write(f"\n*DEL,AZN,,NOPR\n*DIM,AZN,ARRAY,{ndim}"
                    "   ! zone별 컨테이너 area 번호\n")

            # ---- pass 1 : zone 외곽 loop → 컨테이너 area 생성 (전부 먼저)
            #      경계에 걸친 범프는 zp2 단계에서 이미 도려내져
            #      이 loop 자체가 범프를 피해가는 형태다 ----
            for z in zids:
                outer = [ln for isout, ln in rings[z] if isout][0]
                f.write(f"\n! ---- zone {z} container : lines={len(outer)} ----\n")
                f.write("*GET,ZA,AREA,0,NUM,MAX\nZA1 = ZA+1\n"
                        "NUMSTR,AREA,ZA1\nLSEL,NONE\n")
                for a, b in runs(outer):
                    f.write(f"LSEL,A,LINE,,LB+{a},LB+{b}\n")
                f.write(f"AL,ALL\nALLSEL,ALL\nNUMSTR,DEFA\nAZN({z+1}) = ZA1\n")

            # ---- pass 2 : 내곽 loop(홀) 차감 ― 경계걸침 범프 절개로
            #      생긴 hole 도 여기서 함께 처리된다 ----
            for z in zids:
                holes = [ln for isout, ln in rings[z] if not isout]
                for hl in holes:
                    f.write(f"\n! ---- zone {z} hole : lines={len(hl)} ----\n")
                    f.write("*GET,ZA,AREA,0,NUM,MAX\nZA1 = ZA+1\n"
                            "NUMSTR,AREA,ZA1\nLSEL,NONE\n")
                    for a, b in runs(hl):
                        f.write(f"LSEL,A,LINE,,LB+{a},LB+{b}\n")
                    f.write("AL,ALL\nALLSEL,ALL\nNUMSTR,DEFA\nAHOLE = ZA1\n"
                            "ALLSEL,ALL\nCM,_PREA,AREA\n"
                            f"ASBA,AZN({z+1}),AHOLE,,DELETE,DELETE\n"
                            "ALLSEL,ALL\nCMSEL,U,_PREA\n"
                            f"*GET,AZN({z+1}),AREA,0,NUM,MIN\n"
                            "CMDELE,_PREA\nALLSEL,ALL\n")

            # ---- pass 3 : 경계에 걸치지 않은 범프만 ASBA 로 차감.
            #      SQ{z} 는 재질/후처리 라벨용으로 zone 전체 범프를 담고,
            #      boolean 대상(asba_nums)은 그 중 경계 미접촉 범프만이다 ----
            for z in zids:
                all_b  = np.flatnonzero(self.lab == z)
                bnd_b  = [b for b in all_b if b in tang]
                asba_b = [b for b in all_b if b not in tang]
                all_nums  = sorted(int(b) + 1 for b in all_b)
                asba_nums = sorted(int(b) + 1 for b in asba_b)

                f.write(f"\n! ========== zone {z}: bumps={len(all_nums)} "
                        f"(경계걸침 {len(bnd_b)}은 컨테이너에서 이미 절개) "
                        "==========\n")

                if all_nums:
                    f.write("ALLSEL,ALL\nASEL,NONE\n")
                    for a, b in runs(all_nums):
                        f.write(f"ASEL,A,AREA,,{a},{b}\n")
                    f.write(f"CM,SQ{z},AREA\nALLSEL,ALL\n")
                else:
                    log(f"[i] zone {z}: 범프 없음 ― SQ{z} 미생성, "
                        f"ZN{z} = 컨테이너 그대로")

                if asba_nums:
                    f.write("ALLSEL,ALL\nCM,_PREZ,AREA\nASEL,NONE\n")
                    for a, b in runs(asba_nums):
                        f.write(f"ASEL,A,AREA,,{a},{b}\n")
                    f.write(f"ASEL,A,AREA,,AZN({z+1})\n"
                            f"ASBA,AZN({z+1}),ALL,,DELETE,KEEP\n"
                            "ALLSEL,ALL\nCMSEL,U,_PREZ\n"
                            f"CM,ZN{z},AREA\nCMDELE,_PREZ\nALLSEL,ALL\n")
                else:
                    if all_nums:
                        log(f"[i] zone {z}: 범프 {len(all_nums)}개 전부 "
                            f"경계걸침 ― ASBA 없이 ZN{z} = 컨테이너(이미 절개됨)")
                    f.write(f"ALLSEL,ALL\nASEL,S,AREA,,AZN({z+1})\n"
                            f"CM,ZN{z},AREA\nALLSEL,ALL\n")

            f.write("\nNUMSTR,DEFA\nALLSEL,ALL\n"
                    "*GET,natot,AREA,0,COUNT\n"
                    "*MSG,INFO,natot\ntotal areas after boolean = %I\n")

        self.write_run(nsq)
        self.fig.savefig(out_path("zones.png"), dpi=170, bbox_inches="tight")
        log("[save] labels.txt / bumps.mac / zones.mac / run.mac / zones.png"
            + (f"  →  {os.path.abspath(OUT_DIR)}" if OUT_DIR else ""))

    def write_run(self, nsq):
        esz = float(np.median(self.half)) * 3.0
        atol = float(np.median(self.half))**2 * 4.0 * ATOL_FRAC
        with open(out_path("run.mac"), "w") as f:
            f.write(f"""/CLEAR,NOSTART
/PREP7
NSQ = {nsq}
ATOL = {atol:.6e}

*USE,bumps.mac
*USE,zones.mac

! ---------- 위상 정리 : 메시 전에 반드시 ----------
ALLSEL,ALL
NUMMRG,KP,,,,LOW
NUMMRG,LINE
NUMCMP,KP
NUMCMP,LINE

! ---------- 검증 : 범프 보존 ----------
ALLSEL,ALL
*GET,nA,AREA,0,COUNT
CMSEL,S,SQ
*GET,nB,AREA,0,COUNT
ALLSEL,ALL
*MSG,INFO,nB,NSQ,nA
bump areas = %I / %I , total areas = %I

! ---------- 검증 : sliver 탐지 ----------
ALLSEL,ALL
ASEL,S,AREA,,1,NSQ
ASEL,INVE
CM,_MAT,AREA
*GET,nmt,AREA,0,COUNT
nsl = 0
*IF,nmt,GT,0,THEN
  *GET,ai,AREA,0,NUM,MIN
  *DO,ii,1,nmt
    *GET,aa,AREA,ai,AREA
    *IF,aa,LT,ATOL,THEN
      nsl = nsl+1
    *ENDIF
    CMSEL,S,_MAT
    *GET,ai,AREA,ai,NXTH
  *ENDDO
*ENDIF
CMDELE,_MAT
ALLSEL,ALL
*MSG,INFO,nsl,nmt
sliver areas = %I / %I matrix areas

! ---------- 요소 ----------
ET,1,PLANE182
KEYOPT,1,3,2            ! plane strain. 필요에 맞게 수정
SMRT,OFF
MOPT,TIMP,1

! 범프 : 매핑 메시로 공유 라인 분할수 고정
CMSEL,S,SQ
LSLA,S
LESIZE,ALL,,,{EDGE_DIV}
ALLSEL,ALL
MSHKEY,1
CMSEL,S,SQ
AMESH,ALL

! 매트릭스 : 컴포넌트 의존 없이 전체-범프 로 직접 선택
ALLSEL,ALL
MSHKEY,0
MSHAPE,{1 if MESH_TRI else 0},2D
ESIZE,{esz:.4f}
ASEL,S,AREA,,1,NSQ
ASEL,INVE
AMESH,ALL

ALLSEL,ALL
NUMMRG,NODE
NUMCMP,NODE
*GET,nE,ELEM,0,COUNT
*MSG,INFO,nE
elements = %I
""")

    # ---------- 키 ----------
    def on_key(self, ev):
        k = ev.key
        if self.delbuf is not None:
            self.del_input(k); return
        if k in ("left", "right", "up", "down"):
            self.pan_by({"left": -1, "right": 1}.get(k, 0),
                        {"down": -1, "up": 1}.get(k, 0)); return
        if k in ("shift+left", "shift+right", "shift+up", "shift+down"):
            self.pan_by(3.0*{"shift+left": -1, "shift+right": 1}.get(k, 0),
                        3.0*{"shift+down": -1, "shift+up": 1}.get(k, 0)); return
        if k == "d":
            if not self.polys:
                log("[!] 폴리곤이 없다"); return
            self.delbuf = ""
            log(f"[del] 삭제할 번호 (0~{len(self.polys)-1}), "
                "Enter 확정 / Esc 취소")
            self.status(); self.fig.canvas.draw_idle(); return

        if k == "escape":
            self.chain = []
        elif k == "backspace":
            if self.chain:
                self.chain.pop()
        elif k == "c":
            self.close_direct(); return
        elif k == "e":
            self.close_box(True); return
        elif k == "E":
            self.close_box(False); return
        elif k == "o":
            self.ortho = not self.ortho
            log(f"[ortho] {'ON' if self.ortho else 'OFF'}")
        elif k in "123456":
            i = int(k)
            self.snapmode[i] = not self.snapmode[i]
            nm = {1: "정점", 2: "범프", 3: "여유중심", 4: "격자",
                  5: "외곽선", 6: "라인 위"}
            log(f"[snap] {nm[i]} {'ON' if self.snapmode[i] else 'OFF'}")
        elif k == "0":
            for i in self.snapmode:
                self.snapmode[i] = False
            log("[snap] 전부 OFF")
        elif k == "f":
            self.autofill(); return
        elif k == "x":
            if self.polys:
                self.polys.pop(); self.assign()
                log(f"[del] 남은 폴리곤 {len(self.polys)}")
        elif k == "X":
            self.polys = []; self.assign()
            log("[del] 전체 삭제")
        elif k == "b":
            self.diag = not self.diag
            log(f"[diag] {'ON' if self.diag else 'OFF'}")
        elif k == "v":
            self.validate(); return
        elif k == "z":
            self.zoom_all(); return
        elif k == "w":
            self.save_polys(); return
        elif k == "r":
            self.load_polys(); return
        elif k == "s":
            self.save_apdl(); return
        elif k == "h":
            log(HELP); return
        else:
            return
        self.redraw()


def main():
    """단독 실행: 모듈 상단 설정값으로 bump 파일을 읽어 창을 띄운다."""
    xy, half = load(BUMP_FILE, D_DEFAULT)
    App(xy, half)
    plt.show()


if __name__ == "__main__":
    main()
