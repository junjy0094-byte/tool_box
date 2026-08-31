# -*- coding: utf-8 -*-
"""Leadframe 그리기 core ― 이미지 위에 라인을 따서 APDL area 매크로를 만드는
트레이싱 엔진.

원본 단독 스크립트(trace_gui.py)에서 바뀐 점
  1. 모듈 상단 상수를 ``configure(**kwargs)`` 로 주입할 수 있게 했다.
  2. 모듈 전역(fig/ax/state/artist)에 흩어져 있던 상태를 ``TraceApp`` 클래스로
     묶어, 외부에서 만든 Figure/Axes 를 받아 tkinter 창에 임베드할 수 있게 했다.
  3. ``print`` 대신 ``log`` 를 써서 GUI 로그 창으로도 메시지가 흐르게 하고,
     JSON 열기 대화상자는 ``ask_path`` 훅으로 GUI 가 제공한다.
작도/스냅/구속/편집/내보내기 로직은 원본 그대로다.
"""
import json
import math
import os

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.path import Path

# ============================================================
# 설정 ― GUI 가 configure() 로 덮어쓴다
# ============================================================
IMG_PATH     = "leadframe.png"
PKG_WIDTH_UM = 8000.0     # 이미지 가로 전체의 실제 폭 [µm]
GRID_UM      = 50.0       # 초기 그리드 피치 [µm]
MESH_UM      = 50.0       # 목표 요소 크기 [µm] — autofit 허용범위 기본값
ROUND_DEC    = 3          # 좌표 반올림 자리수 (-1 이면 반올림 안 함)
OFF_X_UM     = 0.0        # 이미지 중앙이 놓일 좌표 (패키지 중심 보정용)
OFF_Y_UM     = 0.0
SNAP_VERTEX  = True       # 기존 정점 스냅 사용
OUT_APDL     = "geom.mac"
OUT_JSON     = "polys.json"
OUT_DIR      = ""         # 결과 파일 폴더. ""이면 현재 폴더

_CONFIG_KEYS = (
    "IMG_PATH", "PKG_WIDTH_UM", "GRID_UM", "MESH_UM", "ROUND_DEC",
    "OFF_X_UM", "OFF_Y_UM", "SNAP_VERTEX", "OUT_APDL", "OUT_JSON", "OUT_DIR",
)


def configure(**kwargs) -> None:
    """모듈 설정을 덮어쓴다."""
    g = globals()
    for k, v in kwargs.items():
        if k not in _CONFIG_KEYS:
            raise KeyError(f"알 수 없는 설정 항목: {k}")
        g[k] = v


def current_config() -> dict:
    g = globals()
    return {k: g[k] for k in _CONFIG_KEYS}


# ============================================================
# 로그 ― stdout + (등록되어 있으면) GUI 로그 창
# ============================================================
_LOG_HOOK = None


def set_log_hook(fn) -> None:
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
    """결과 파일 경로. 절대 경로면 그대로, OUT_DIR 이 비면 현재 폴더."""
    if os.path.isabs(name) or not OUT_DIR:
        return name
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, name)


def disable_default_keymap() -> None:
    """matplotlib 기본 단축키를 꺼서 도구 단축키와 충돌하지 않게 한다."""
    for _k in ("keymap.save", "keymap.grid", "keymap.grid_minor", "keymap.home",
               "keymap.back", "keymap.forward", "keymap.pan", "keymap.zoom",
               "keymap.xscale", "keymap.yscale", "keymap.fullscreen",
               "keymap.copy"):
        if _k in plt.rcParams:
            plt.rcParams[_k] = []


def load_image(path):
    return mpimg.imread(path)


# ---------------- 기하 헬퍼 ----------------
def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def param_on(a, b, x, y):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    return 0.0 if L2 < 1e-18 else ((x - a[0]) * dx + (y - a[1]) * dy) / L2


def dist_pt_seg(x, y, a, b):
    t = max(0.0, min(1.0, param_on(a, b, x, y)))
    q = lerp(a, b, t)
    return math.hypot(x - q[0], y - q[1])


def seg_int(a, b, c, d):
    """세그먼트 ab 위의 교점 파라미터 t (없으면 None)"""
    x1, y1 = a; x2, y2 = b; x3, y3 = c; x4, y4 = d
    den = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(den) < 1e-12:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / den
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / den
    return t if (1e-9 < t < 1 - 1e-9 and -1e-9 <= u <= 1 + 1e-9) else None


HELP = r"""
================================================================
  LEADFRAME 그리기  --  단축키 (그림창에 포커스를 둔 상태에서 입력)
================================================================
[모드 전환]   현재 모드는 그림 상단 제목에 표시됩니다
  a            모델 <-> 보조선 모드 토글
  t            모델 <-> TRIM 모드 토글
  s            모델 <-> 선택(편집) 모드 토글
  r            레퍼런스 보조선 선택 (클릭 1회 후 모델 모드 복귀)

[작도]
  좌클릭       점 추가
  c            닫힌 도형으로 확정  (모델=외곽 루프 / 보조선=닫힌 도형)
  h            홀로 확정           (모델 모드 전용)
  x            열린 폴리라인으로 확정 (보조선 모드 전용)
  u / BkSp     마지막 점 취소
  * 시작점을 다시 클릭해 닫아도 중복 KP는 자동으로 제거됩니다

[구속]        셋 다 토글, 하나를 켜면 나머지는 꺼짐
  o            직교 구속 (수평/수직)
                + 현재 폴리곤의 기존 점과 정렬되는 위치에서 자동 정지
                + 정렬 시 초록 점선 추적선 표시
  p            레퍼런스 보조선과 평행 (+ 끝점 자동 구속)
  e            레퍼런스 보조선과 수직 (+ 끝점 자동 구속)
               p / e 는 r 로 레퍼런스를 먼저 지정해야 동작

[선택 / 편집]  s 로 선택 모드에 진입한 뒤 사용
  1st 클릭      폴리곤 선택만 (이동되지 않음)
  2nd 드래그    이미 선택된 폴리곤을 다시 눌러 끌면 이동
  Shift+클릭    다중 선택 토글
  빈 곳 클릭    선택 해제
  ESC           선택 해제 / 드래그 취소
  Ctrl+C        복사
  Ctrl+V        붙여넣기 (한 그리드 오프셋 위치, 자동 선택됨)
  Delete        선택 폴리곤 삭제
  . / ,         반시계 / 시계 회전
  n             회전 스텝 순환 (90 -> 45 -> 30 -> 15 -> 5 -> 1도)
  f / v         좌우 반전 / 상하 반전
  b             회전·반전 기준점 토글 (선택 영역 중심 <-> 원점)

[AUTOFIT]      드래그 이동 시 X축 / Y축을 각각 독립적으로 판정
  k            autofit on/off
  - / =        허용범위 1/2배 / 2배 (기본값 = 목표 요소 크기)
  * 선택 영역의 좌/우(하/상) 끝과 중심선이, 선택되지 않은 형상의
    좌표 또는 원점과 허용범위 안에서 만나면 그 값으로 자동 정렬
  * 정렬된 축은 마젠타 점선으로 표시

[좌표 반올림]
  1 / 2        자리수 감소 / 증가 (-1 = 반올림 안 함, 최대 6)
  3            현재 자리수를 전체 형상에 다시 적용
  * 자리수를 바꾸면 기존 형상 전체에 즉시 반영됩니다
  * 신규 작도, 이동, 회전, 반전, 불러오기에도 항상 적용됩니다
  * 반올림으로 겹친 점은 자동 제거됩니다

[삭제]
  d            마지막 모델 폴리곤 삭제
  z            마지막 보조선 세그먼트 삭제
  TRIM 모드 클릭  클릭한 조각만 잘라내기

[그리드 / 파일]
  g            그리드 스냅 on/off
  [ / ]        그리드 피치 1/2배 / 2배
  w            저장 (APDL 매크로 + JSON, 보조선 포함)
  l            JSON 불러오기 (현재 작업 내용을 대체)
  L (Shift+l)  JSON 불러오기 (현재 작업 내용에 추가)
  ?            이 도움말 다시 출력
  툴바          줌 / 팬 (이 모드에선 클릭이 점으로 들어가지 않음)

[스냅 우선순위]  자동 적용, 별도 키 없음
  기존 정점  ->  보조선 위 최근접점  ->  그리드

[색상]
  초록 실선 = 외곽 루프    빨강 실선 = 홀       노랑 = 선택/작도중
  하늘 점선 = 보조선       마젠타 = 레퍼런스/autofit 정렬선
  주황 실선 = 원점 축      흰 십자 = 회전/반전 기준점
================================================================
"""


class TraceApp:
    """이미지 트레이싱 창 하나의 상태와 동작."""

    def __init__(self, img, fig=None, ax=None):
        disable_default_keymap()
        self.img = img
        H, W = img.shape[:2]
        self.SCALE = PKG_WIDTH_UM / W
        self.X_UM, self.Y_UM = W * self.SCALE, H * self.SCALE
        self.XMIN = -self.X_UM / 2 + OFF_X_UM
        self.XMAX = self.X_UM / 2 + OFF_X_UM
        self.YMIN = -self.Y_UM / 2 + OFF_Y_UM
        self.YMAX = self.Y_UM / 2 + OFF_Y_UM
        self.pkg_width_um = PKG_WIDTH_UM
        self.off = (OFF_X_UM, OFF_Y_UM)
        self.snap_vertex = SNAP_VERTEX
        self.out_apdl = OUT_APDL
        self.out_json = OUT_JSON

        if fig is None or ax is None:
            self.fig, self.ax = plt.subplots(figsize=(13, 13))
        else:
            self.fig, self.ax = fig, ax
        self.fig._leadframe_trace_app = self          # GC 방지 앵커

        self.ax.imshow(img, extent=[self.XMIN, self.XMAX,
                                    self.YMIN, self.YMAX],
                       cmap="gray", zorder=0)
        self.ax.set_xlim(self.XMIN, self.XMAX)
        self.ax.set_ylim(self.YMIN, self.YMAX)
        self.ax.set_aspect("equal")
        self.ax.set_xlabel("X [um]")
        self.ax.set_ylabel("Y [um]")

        self.state = dict(
            grid=GRID_UM, snap=True, con="none", mode="model",
            cur=[], polys=[], aux=[], ref=None, align=None,
            sel=set(), clip=[], drag=None, rot=90.0, pivot="bbox",
            fit=True, fit_tol=MESH_UM, pool=None, fitx=None, fity=None,
            dec=ROUND_DEC,
        )
        # mode : model | aux | trim | pickref | select
        # con  : none | ortho | para | perp
        # aux  : [(p1, p2), ...] 세그먼트 평면 리스트

        self.grid_lines, self.poly_artists = [], []
        self.aux_artists, self.fit_artists = [], []
        self.cur_line = self.rubber = None
        self.align_artist = self.ref_artist = None

        self.ask_path = None        # GUI 가 파일 대화상자를 꽂는 자리
        self.on_state = None        # GUI 가 상태 표시를 갱신하는 자리

        c = self.fig.canvas
        self._cids = [
            c.mpl_connect("button_press_event", self.on_click),
            c.mpl_connect("motion_notify_event", self.on_move),
            c.mpl_connect("button_release_event", self.on_release),
            c.mpl_connect("key_press_event", self.on_key),
        ]
        try:
            c.setFocusPolicy(2); c.setFocus()
        except Exception:
            pass

        self.draw_grid()
        self.title()
        log(HELP)
        log(f"[i] 이미지 {W} x {H} px → {self.X_UM:.1f} x {self.Y_UM:.1f} um "
            f"(1px = {self.SCALE:.3f} um)")

    # ---------------- 기하 헬퍼 ----------------
    def dedup(self, pts, tol=None):
        """연속 중복점 제거 + 시작점과 겹치는 끝점 제거"""
        if tol is None:
            tol = self.X_UM * 1e-6
        out = []
        for p in pts:
            if not out or math.hypot(p[0] - out[-1][0],
                                     p[1] - out[-1][1]) > tol:
                out.append(tuple(p))
        while len(out) >= 2 and math.hypot(out[0][0] - out[-1][0],
                                           out[0][1] - out[-1][1]) <= tol:
            out.pop()
        return out

    # ---------------- 반올림 ----------------
    def rnd(self, v):
        d = self.state["dec"]
        return v if d < 0 else round(v, d)

    def rnd_pt(self, p):
        return (self.rnd(p[0]), self.rnd(p[1]))

    def round_all(self):
        """이미 만들어진 모든 형상에 현재 자리수를 일괄 적용"""
        st = self.state
        for p in st["polys"]:
            p["pts"] = self.dedup([self.rnd_pt(q) for q in p["pts"]])
        st["aux"] = [(self.rnd_pt(a), self.rnd_pt(b)) for a, b in st["aux"]]
        st["cur"] = [self.rnd_pt(q) for q in st["cur"]]
        if st["ref"]:
            st["ref"] = (self.rnd_pt(st["ref"][0]), self.rnd_pt(st["ref"][1]))
        self.redraw_cur(); self.redraw_polys(); self.draw_aux(); self.title()
        d = st["dec"]
        log("반올림 해제됨" if d < 0
            else f"전체 좌표를 소수점 {d}자리로 반올림했습니다.")

    # ---------------- 그리드 ----------------
    def draw_grid(self):
        for ln in self.grid_lines:
            ln.remove()
        self.grid_lines = []
        g = self.state["grid"]
        if g <= 0 or self.X_UM / g > 400:
            self.fig.canvas.draw_idle(); return

        i = int(self.XMIN // g)
        while i * g <= self.XMAX:
            self.grid_lines += self.ax.plot(
                [i * g, i * g], [self.YMIN, self.YMAX], lw=0.3,
                color="cyan", alpha=0.35, zorder=1)
            i += 1
        j = int(self.YMIN // g)
        while j * g <= self.YMAX:
            self.grid_lines += self.ax.plot(
                [self.XMIN, self.XMAX], [j * g, j * g], lw=0.3,
                color="cyan", alpha=0.35, zorder=1)
            j += 1

        self.grid_lines += self.ax.plot(
            [self.XMIN, self.XMAX], [0, 0], lw=0.9, color="orange",
            alpha=0.7, zorder=2)
        self.grid_lines += self.ax.plot(
            [0, 0], [self.YMIN, self.YMAX], lw=0.9, color="orange",
            alpha=0.7, zorder=2)
        self.fig.canvas.draw_idle()

    # ---------------- 보조선 ----------------
    def draw_aux(self):
        for a in self.aux_artists:
            a.remove()
        self.aux_artists = []
        for p, q in self.state["aux"]:
            self.aux_artists += self.ax.plot(
                [p[0], q[0]], [p[1], q[1]], "--", color="deepskyblue",
                lw=0.9, alpha=0.85, zorder=3)
        if self.ref_artist:
            self.ref_artist.remove(); self.ref_artist = None
        if self.state["ref"]:
            p, q = self.state["ref"]
            self.ref_artist, = self.ax.plot(
                [p[0], q[0]], [p[1], q[1]], "-", color="magenta",
                lw=2.2, alpha=0.9, zorder=3)
        self.fig.canvas.draw_idle()

    def pick_ref(self, x, y):
        best, bd = None, self.X_UM * 0.02
        for s in self.state["aux"]:
            d = dist_pt_seg(x, y, *s)
            if d < bd:
                best, bd = s, d
        if best:
            self.state["ref"] = best
            log("레퍼런스 보조선 지정됨")
        else:
            log("보조선 위를 클릭하세요.")
        self.draw_aux()

    def trim_at(self, x, y):
        """AutoCAD TRIM: 클릭한 조각을 교점 기준으로 잘라냄 (보조선 대상)"""
        st = self.state
        tgt, bd = None, self.X_UM * 0.02
        for i, s in enumerate(st["aux"]):
            d = dist_pt_seg(x, y, *s)
            if d < bd:
                tgt, bd = i, d
        if tgt is None:
            log("보조선 위를 클릭하세요."); return

        a, b = st["aux"][tgt]
        cuts = [0.0, 1.0]
        for j, s in enumerate(st["aux"]):
            if j != tgt:
                t = seg_int(a, b, *s)
                if t is not None:
                    cuts.append(t)
        for p in st["polys"]:
            pts, n = p["pts"], len(p["pts"])
            for k in range(n):
                t = seg_int(a, b, pts[k], pts[(k + 1) % n])
                if t is not None:
                    cuts.append(t)

        cuts = sorted(set(round(c, 9) for c in cuts))
        tc = param_on(a, b, x, y)
        hit = next((j for j in range(len(cuts) - 1)
                    if cuts[j] - 1e-9 <= tc <= cuts[j + 1] + 1e-9), None)
        if hit is None:
            return
        keep = [(self.rnd_pt(lerp(a, b, cuts[j])),
                 self.rnd_pt(lerp(a, b, cuts[j + 1])))
                for j in range(len(cuts) - 1) if j != hit]
        st["aux"].pop(tgt)
        st["aux"].extend(keep)
        self.draw_aux()

    # ---------------- 스냅 / 구속 ----------------
    def snap(self, x, y):
        st = self.state
        # 1순위: 기존 정점 (모델 + 진행중 + 보조선 끝점)
        if self.snap_vertex:
            tol = max(st["grid"] * 0.5, self.X_UM * 0.004)
            best, bd = None, tol
            cands = [v for p in st["polys"] for v in p["pts"]] + list(st["cur"])
            cands += [v for s in st["aux"] for v in s]
            for vx, vy in cands:
                d = math.hypot(vx - x, vy - y)
                if d < bd:
                    best, bd = (vx, vy), d
            if best:
                return best
        # 2순위: 보조선 위 최근접점
        tol2 = max(st["grid"] * 0.4, self.X_UM * 0.003)
        best, bd = None, tol2
        for s in st["aux"]:
            d = dist_pt_seg(x, y, *s)
            if d < bd:
                t = max(0.0, min(1.0, param_on(s[0], s[1], x, y)))
                best, bd = lerp(s[0], s[1], t), d
        if best:
            return best
        # 3순위: 그리드
        if st["snap"] and st["grid"] > 0:
            g = st["grid"]
            return (round(x / g) * g, round(y / g) * g)
        return (x, y)

    def apply_ortho(self, x, y):
        st = self.state
        st["align"] = None
        if not st["cur"]:
            return x, y
        px, py = st["cur"][-1]
        m = st["con"]
        tol = max(st["grid"] * 0.6, self.X_UM * 0.005)

        if m == "ortho":
            prev = st["cur"][:-1]
            if abs(x - px) >= abs(y - py):          # 수평 이동 → X 정렬 탐색
                best, bd = None, tol
                for q in prev:
                    d = abs(q[0] - x)
                    if d < bd:
                        best, bd = q, d
                if best:
                    st["align"] = (best, "v")
                    return best[0], py
                return x, py
            else:                                    # 수직 이동 → Y 정렬 탐색
                best, bd = None, tol
                for q in prev:
                    d = abs(q[1] - y)
                    if d < bd:
                        best, bd = q, d
                if best:
                    st["align"] = (best, "h")
                    return px, best[1]
                return px, y

        if m in ("para", "perp") and st["ref"]:
            (rx1, ry1), (rx2, ry2) = st["ref"]
            dx, dy = rx2 - rx1, ry2 - ry1
            L = math.hypot(dx, dy)
            if L < 1e-9:
                return x, y
            dx, dy = dx / L, dy / L
            if m == "perp":
                dx, dy = -dy, dx
            t = (x - px) * dx + (y - py) * dy
            for q in st["ref"]:                   # 끝점 자동 구속
                tq = (q[0] - px) * dx + (q[1] - py) * dy
                if abs(tq - t) < tol:
                    t = tq
                    break
            return px + t * dx, py + t * dy

        return x, y

    def place(self, xd, yd):
        """구속 → 정렬스냅 → 일반스냅 → 반올림 순으로 최종 좌표 결정"""
        st = self.state
        x, y = self.apply_ortho(xd, yd)
        if st["align"]:
            return self.rnd_pt((x, y))
        sx, sy = self.snap(x, y)
        if st["con"] == "ortho" and st["cur"]:
            px, py = st["cur"][-1]
            if abs(y - py) < 1e-9: sy = py
            if abs(x - px) < 1e-9: sx = px
        return self.rnd_pt((sx, sy))

    # ---------------- 화면 갱신 ----------------
    def redraw_cur(self):
        if self.cur_line:
            self.cur_line.remove(); self.cur_line = None
        if self.state["cur"]:
            xs = [p[0] for p in self.state["cur"]]
            ys = [p[1] for p in self.state["cur"]]
            self.cur_line, = self.ax.plot(xs, ys, "-o", color="yellow",
                                          ms=4, lw=1.2, zorder=5)
        self.fig.canvas.draw_idle()

    def redraw_polys(self):
        st = self.state
        for a in self.poly_artists:
            a.remove()
        self.poly_artists = []
        for i, p in enumerate(st["polys"]):
            xs = [q[0] for q in p["pts"]] + [p["pts"][0][0]]
            ys = [q[1] for q in p["pts"]] + [p["pts"][0][1]]
            if i in st["sel"]:
                c, lw, z = "yellow", 2.6, 7
            else:
                c, lw, z = ("red" if p["is_hole"] else "lime"), 1.4, 4
            self.poly_artists += self.ax.plot(xs, ys, "-", color=c,
                                              lw=lw, zorder=z)
        if st["sel"]:
            px, py = self.pivot_pt()
            self.poly_artists += self.ax.plot([px], [py], "+", color="white",
                                              ms=14, mew=1.8, zorder=8)
        self.fig.canvas.draw_idle()

    def clear_fit(self):
        for a in self.fit_artists:
            a.remove()
        self.fit_artists = []
        self.state["fitx"] = self.state["fity"] = None

    def draw_fit(self):
        for a in self.fit_artists:
            a.remove()
        self.fit_artists = []
        if self.state["fitx"] is not None:
            self.fit_artists += self.ax.plot(
                [self.state["fitx"]] * 2, [self.YMIN, self.YMAX], ":",
                color="magenta", lw=1.2, alpha=0.9, zorder=9)
        if self.state["fity"] is not None:
            self.fit_artists += self.ax.plot(
                [self.XMIN, self.XMAX], [self.state["fity"]] * 2, ":",
                color="magenta", lw=1.2, alpha=0.9, zorder=9)

    def title(self):
        st = self.state
        self.ax.set_title(
            f"[{st['mode'].upper()}] con={st['con']} "
            f"ref={'Y' if st['ref'] else '-'} | grid {st['grid']:.0f}um "
            f"snap {'ON' if st['snap'] else 'OFF'} | "
            f"fit {'ON' if st['fit'] else 'OFF'}({st['fit_tol']:.0f}um) "
            f"dec={st['dec']} | "
            f"rot {st['rot']:.0f}deg pivot={st['pivot']} sel {len(st['sel'])} | "
            f"polys {len(st['polys'])} aux {len(st['aux'])} pts {len(st['cur'])}",
            fontsize=8.5)
        if self.on_state is not None:
            try:
                self.on_state(self)
            except Exception:
                pass
        self.fig.canvas.draw_idle()

    # ---------------- 폴리곤 확정 ----------------
    def close_poly(self, is_hole, closed=True):
        st = self.state
        pts = st["cur"]
        if st["mode"] == "aux":
            if len(pts) < 2:
                log("점이 2개 이상 필요합니다."); return
            n = len(pts)
            m = n if (closed and n >= 3) else n - 1
            st["aux"] += [(self.rnd_pt(pts[i]), self.rnd_pt(pts[(i + 1) % n]))
                          for i in range(m)]
            st["cur"] = []
            self.redraw_cur(); self.draw_aux(); self.title(); return

        pts = self.dedup([self.rnd_pt(q) for q in pts])  # 반올림 + 중복 KP 제거
        if len(pts) < 3:
            log("유효한 점이 3개 미만입니다."); return
        st["polys"].append({"pts": pts, "is_hole": is_hole})
        st["cur"] = []
        self.redraw_cur(); self.redraw_polys(); self.title()

    # ---------------- 선택 / 편집 ----------------
    def hit_poly(self, x, y):
        st = self.state
        for i in reversed(range(len(st["polys"]))):
            if Path(st["polys"][i]["pts"]).contains_point((x, y)):
                return i
        best, bd = None, self.X_UM * 0.01
        for i, p in enumerate(st["polys"]):
            pts, n = p["pts"], len(p["pts"])
            for k in range(n):
                d = dist_pt_seg(x, y, pts[k], pts[(k + 1) % n])
                if d < bd:
                    best, bd = i, d
        return best

    def pivot_pt(self):
        st = self.state
        if st["pivot"] == "origin" or not st["sel"]:
            return (0.0, 0.0)
        xs = [q[0] for i in st["sel"] for q in st["polys"][i]["pts"]]
        ys = [q[1] for i in st["sel"] for q in st["polys"][i]["pts"]]
        return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def sel_bbox(self):
        st = self.state
        xs = [q[0] for i in st["sel"] for q in st["polys"][i]["pts"]]
        ys = [q[1] for i in st["sel"] for q in st["polys"][i]["pts"]]
        return min(xs), max(xs), min(ys), max(ys)

    def build_pool(self):
        """선택되지 않은 형상들의 X / Y 좌표 후보 (드래그 시작 시 1회 계산)"""
        st = self.state
        px, py = {0.0}, {0.0}
        for j, p in enumerate(st["polys"]):
            if j in st["sel"]:
                continue
            for q in p["pts"]:
                px.add(q[0]); py.add(q[1])
        for s in st["aux"]:
            for q in s:
                px.add(q[0]); py.add(q[1])
        st["pool"] = (sorted(px), sorted(py))

    def fit_axis(self, axis, d):
        """이동량 d 에 대해 해당 축의 autofit 보정량과 타깃 좌표를 반환"""
        st = self.state
        if not st["sel"] or not st["pool"]:
            return 0.0, None
        x0, x1, y0, y1 = self.sel_bbox()
        lo, hi = (x0, x1) if axis == 0 else (y0, y1)
        cands = (lo + d, hi + d, (lo + hi) / 2 + d)     # 좌/우(하/상)/중심
        tol = st["fit_tol"]
        bd, bdelta, btgt = tol, 0.0, None
        for c in cands:
            for t in st["pool"][axis]:
                e = abs(t - c)
                if e < bd:
                    bd, bdelta, btgt = e, t - c, t
        return bdelta, btgt

    def xf_sel(self, fn):
        st = self.state
        for i in st["sel"]:
            st["polys"][i]["pts"] = [self.rnd_pt(fn(q))
                                     for q in st["polys"][i]["pts"]]
        self.redraw_polys(); self.title()

    def rotate_sel(self, deg):
        if not self.state["sel"]:
            return
        cx, cy = self.pivot_pt()
        a = math.radians(deg); ca, sa = math.cos(a), math.sin(a)
        self.xf_sel(lambda q: (cx + (q[0] - cx) * ca - (q[1] - cy) * sa,
                               cy + (q[0] - cx) * sa + (q[1] - cy) * ca))

    def flip_sel(self, axis):
        if not self.state["sel"]:
            return
        cx, cy = self.pivot_pt()
        if axis == "x":
            self.xf_sel(lambda q: (2 * cx - q[0], q[1]))
        else:
            self.xf_sel(lambda q: (q[0], 2 * cy - q[1]))

    def copy_sel(self):
        st = self.state
        st["clip"] = [{"pts": st["polys"][i]["pts"][:],
                       "is_hole": st["polys"][i]["is_hole"]}
                      for i in sorted(st["sel"])]
        log(f"복사: {len(st['clip'])}개")

    def paste_clip(self):
        st = self.state
        if not st["clip"]:
            log("클립보드가 비어 있습니다."); return
        g = st["grid"] if st["grid"] > 0 else 0.0
        new = set()
        for p in st["clip"]:
            new.add(len(st["polys"]))
            st["polys"].append({"pts": [self.rnd_pt((q[0] + g, q[1] - g))
                                        for q in p["pts"]],
                                "is_hole": p["is_hole"]})
        st["sel"] = new
        self.redraw_polys(); self.title()

    def delete_sel(self):
        st = self.state
        for i in sorted(st["sel"], reverse=True):
            st["polys"].pop(i)
        st["sel"] = set()
        self.redraw_polys(); self.title()

    # ---------------- 불러오기 ----------------
    def _ask_path(self):
        """파일 선택 대화상자. GUI 가 훅을 꽂지 않았으면 OUT_JSON 사용"""
        if self.ask_path is not None:
            try:
                return self.ask_path()
            except Exception:
                return None
        return out_path(self.out_json)

    def load_json(self, path=None, merge=False):
        st = self.state
        if path is None:
            path = self._ask_path()
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            log("불러오기 실패:", e); return

        if isinstance(data, dict):                 # 신형식
            polys = data.get("polys", [])
            aux = data.get("aux", [])
            meta = data.get("meta", {})
        else:                                      # 구형식 (폴리곤 리스트만)
            polys, aux, meta = data, [], {}

        if meta and abs(meta.get("pkg_width_um", self.pkg_width_um)
                        - self.pkg_width_um) > 1e-6:
            log(f"주의: 저장 당시 PKG_WIDTH_UM={meta['pkg_width_um']}, "
                f"현재={self.pkg_width_um} — 배경 이미지와 어긋날 수 있습니다.")

        P = [{"pts": self.dedup([self.rnd_pt((float(a), float(b)))
                                 for a, b in p["pts"]]),
              "is_hole": bool(p.get("is_hole", False))} for p in polys]
        A = [(self.rnd_pt(tuple(map(float, s[0]))),
              self.rnd_pt(tuple(map(float, s[1])))) for s in aux]

        if merge:
            st["polys"] += P
            st["aux"] += A
        else:
            st["polys"] = P
            st["aux"] = A
            st["sel"] = set()
            st["ref"] = None
        st["cur"] = []
        self.redraw_cur(); self.redraw_polys(); self.draw_aux(); self.title()
        log(f"{'추가' if merge else '불러오기'}: 폴리곤 {len(P)}개, "
            f"보조선 {len(A)}개  <- {path}")

    # ---------------- 내보내기 ----------------
    def export(self):
        st = self.state
        if not st["polys"]:
            log("내보낼 폴리곤이 없습니다."); return

        json_path = out_path(self.out_json)
        apdl_path = out_path(self.out_apdl)

        with open(json_path, "w") as f:
            json.dump({"polys": st["polys"],
                       "aux": st["aux"],
                       "meta": {"pkg_width_um": self.pkg_width_um,
                                "off": list(self.off),
                                "grid": st["grid"],
                                "dec": st["dec"]}}, f, indent=1)

        clean = [{"pts": self.dedup(p["pts"]), "is_hole": p["is_hole"]}
                 for p in st["polys"]]
        nd = 4 if st["dec"] < 0 else max(st["dec"], 0)

        L = ["/PREP7", "! auto-generated from Leadframe 그리기"]
        for i, p in enumerate(clean, 1):
            pts, n = p["pts"], len(p["pts"])
            L += ["", f"! ---- poly {i} "
                      f"({'hole' if p['is_hole'] else 'outer'}) ----",
                  "*GET,K0,KP,,NUM,MAX", "*GET,L0,LINE,,NUM,MAX"]
            for j, (x, y) in enumerate(pts, 1):
                L.append(f"K,K0+{j},{x:.{nd}f},{y:.{nd}f},0")
            for j in range(1, n + 1):
                L.append(f"LSTR,K0+{j},K0+{j % n + 1}")
            L += [f"LSEL,S,LINE,,L0+1,L0+{n}", "AL,ALL", "ALLSEL,ALL",
                  f"*GET,AR_{i},AREA,,NUM,MAX"]

        L.append("\n! ---- subtract holes ----")
        for i, p in enumerate(clean, 1):
            if not p["is_hole"]:
                continue
            cx = sum(q[0] for q in p["pts"]) / len(p["pts"])
            cy = sum(q[1] for q in p["pts"]) / len(p["pts"])
            for j, q in enumerate(clean, 1):
                if q["is_hole"] or j == i:
                    continue
                if Path(q["pts"]).contains_point((cx, cy)):
                    L.append(f"ASBA,AR_{j},AR_{i}")
                    L.append(f"*GET,AR_{j},AREA,,NUM,MAX")
                    break

        with open(apdl_path, "w") as f:
            f.write("\n".join(L) + "\n")
        log(f"저장 완료: {apdl_path} / {json_path}  (폴리곤 {len(clean)}개)")

    # ---------------- 이벤트 ----------------
    def _toolbar_active(self):
        tb = getattr(self.fig.canvas, "toolbar", None)
        return bool(getattr(tb, "mode", ""))

    def on_click(self, ev):
        st = self.state
        if ev.inaxes != self.ax or ev.button != 1 or self._toolbar_active():
            return

        if st["mode"] == "select":
            shift = bool(ev.key) and "shift" in ev.key
            i = self.hit_poly(ev.xdata, ev.ydata)
            if i is None:
                if not shift:
                    st["sel"] = set()
            elif shift:
                st["sel"] ^= {i}
            elif i in st["sel"]:
                # 이미 선택된 것을 다시 눌렀을 때만 이동 시작
                st["drag"] = (ev.xdata, ev.ydata)
                self.build_pool()
            else:
                st["sel"] = {i}          # 선택만, 이동은 다음 클릭부터
            self.redraw_polys(); self.title(); return

        if st["mode"] == "trim":
            self.trim_at(ev.xdata, ev.ydata); return
        if st["mode"] == "pickref":
            self.pick_ref(ev.xdata, ev.ydata)
            st["mode"] = "model"; self.title(); return

        st["cur"].append(self.place(ev.xdata, ev.ydata))
        self.redraw_cur(); self.title()

    def on_move(self, ev):
        st = self.state
        if st["mode"] == "select":
            if st["drag"] and ev.inaxes == self.ax:
                x0, y0 = st["drag"]
                dx, dy = ev.xdata - x0, ev.ydata - y0
                if st["snap"] and st["grid"] > 0:
                    g = st["grid"]
                    dx, dy = round(dx / g) * g, round(dy / g) * g
                if st["fit"]:                       # X / Y 축 독립 autofit
                    ddx, tx = self.fit_axis(0, dx)
                    ddy, ty = self.fit_axis(1, dy)
                    dx += ddx; dy += ddy
                    st["fitx"], st["fity"] = tx, ty
                else:
                    st["fitx"] = st["fity"] = None
                if dx or dy:
                    for i in st["sel"]:
                        st["polys"][i]["pts"] = [
                            self.rnd_pt((q[0] + dx, q[1] + dy))
                            for q in st["polys"][i]["pts"]]
                    st["drag"] = (x0 + dx, y0 + dy)
                self.redraw_polys(); self.draw_fit()
                self.fig.canvas.draw_idle()
            return

        if self.rubber:
            self.rubber.remove(); self.rubber = None
        if self.align_artist:
            self.align_artist.remove(); self.align_artist = None

        if ev.inaxes == self.ax and st["cur"]:
            x, y = self.place(ev.xdata, ev.ydata)
            px, py = st["cur"][-1]
            self.rubber, = self.ax.plot([px, x], [py, y], "--",
                                        color="orange", lw=0.9, zorder=6)
            if st["align"]:
                q, _kind = st["align"]
                self.align_artist, = self.ax.plot(
                    [q[0], x], [q[1], y], ":", color="lime",
                    lw=0.9, alpha=0.9, zorder=6)
        self.fig.canvas.draw_idle()

    def on_release(self, ev):
        if self.state["drag"]:
            self.state["drag"] = None
            self.state["pool"] = None
            self.clear_fit()
            self.fig.canvas.draw_idle()

    def on_key(self, ev):
        st = self.state
        k = ev.key
        if   k == "c": self.close_poly(False)
        elif k == "h": self.close_poly(True)
        elif k == "x": self.close_poly(False, closed=False)
        elif k in ("u", "backspace"):
            if st["cur"]: st["cur"].pop()
            self.redraw_cur(); self.title()
        elif k == "d":
            if st["polys"]: st["polys"].pop()
            self.redraw_polys(); self.title()
        elif k == "a":
            st["mode"] = "model" if st["mode"] == "aux" else "aux"
            st["cur"] = []; self.redraw_cur(); self.title()
        elif k == "t":
            st["mode"] = "model" if st["mode"] == "trim" else "trim"
            st["cur"] = []; self.redraw_cur(); self.title()
        elif k == "s":
            st["mode"] = "model" if st["mode"] == "select" else "select"
            st["cur"] = []; st["sel"] = set(); st["drag"] = None
            self.clear_fit(); self.redraw_cur(); self.redraw_polys()
            self.title()
        elif k == "escape":
            st["sel"] = set(); st["drag"] = None
            self.clear_fit(); self.redraw_polys(); self.title()
        elif k == "r": st["mode"] = "pickref"; self.title()
        elif k == "o":
            st["con"] = "none" if st["con"] == "ortho" else "ortho"; self.title()
        elif k == "p":
            st["con"] = "none" if st["con"] == "para" else "para"; self.title()
        elif k == "e":
            st["con"] = "none" if st["con"] == "perp" else "perp"; self.title()
        elif k == "ctrl+c": self.copy_sel()
        elif k == "ctrl+v": self.paste_clip()
        elif k == "delete": self.delete_sel()
        elif k == ".": self.rotate_sel(+st["rot"])
        elif k == ",": self.rotate_sel(-st["rot"])
        elif k == "n":
            seq = [90.0, 45.0, 30.0, 15.0, 5.0, 1.0]
            st["rot"] = seq[(seq.index(st["rot"]) + 1) % len(seq)]
            self.title()
        elif k == "b":
            st["pivot"] = "origin" if st["pivot"] == "bbox" else "bbox"
            self.redraw_polys(); self.title()
        elif k == "f": self.flip_sel("x")
        elif k == "v": self.flip_sel("y")
        elif k == "k":
            st["fit"] = not st["fit"]; self.clear_fit(); self.title()
        elif k == "-":
            st["fit_tol"] = max(st["fit_tol"] / 2, 1e-3); self.title()
        elif k == "=":
            st["fit_tol"] *= 2; self.title()
        elif k == "1": st["dec"] = max(st["dec"] - 1, -1); self.round_all()
        elif k == "2": st["dec"] = min(st["dec"] + 1, 6); self.round_all()
        elif k == "3": self.round_all()
        elif k == "z":
            if st["aux"]: st["aux"].pop(); self.draw_aux()
        elif k == "g": st["snap"] = not st["snap"]; self.title()
        elif k == "]": st["grid"] *= 2; self.draw_grid(); self.title()
        elif k == "[": st["grid"] /= 2; self.draw_grid(); self.title()
        elif k == "w": self.export()
        elif k == "l": self.load_json(merge=False)
        elif k == "L": self.load_json(merge=True)
        elif k == "?": log(HELP)


def main():
    """단독 실행: 모듈 상단 설정값으로 이미지를 읽어 창을 띄운다."""
    TraceApp(load_image(IMG_PATH))
    plt.show()


if __name__ == "__main__":
    main()
