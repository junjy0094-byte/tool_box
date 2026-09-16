# -*- coding: utf-8 -*-
"""Zone 분할기 설정 GUI.

원본 zone_draw.py 는 모듈 상단 상수를 직접 고쳐야 했다. 이 GUI 는 그 상수들을
입력받아 ``core.configure()`` 로 주입한 뒤, 그리기 화면(matplotlib)을 별도의
tkinter 창에 임베드해 띄운다. 그리기/스냅/APDL 출력 로직은 원본 그대로다.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

from config import get_tool_config, set_tool_config
from tools._dnd_helper import has_dnd, register_drop_target

TOOL_NAME = "zone_draw"

BUMP_FILETYPES = [
    ("범프 좌표 파일", "*.txt *.csv *.dat"),
    ("모든 파일", "*.*"),
]

# (속성명, 라벨, 기본값, 설명)
GEOM_FIELDS = [
    ("X1", "X 최소", "0.0"),
    ("X2", "X 최대", "16000.0"),
    ("Y1", "Y 최소", "0.0"),
    ("Y2", "Y 최대", "26000.0"),
]

SNAP_FIELDS = [
    ("GTOL_FRAC", "기하 톨러런스 비율 (GTOL = 최대변 × 값)", "1e-9"),
    ("GRID_FRAC", "격자 스냅 비율 (GRID = 최대변 × 값)", "0.001"),
    ("SNAP_PIX", "스냅 반응 반경 [픽셀]", "12"),
    ("EDGE_PIX", "외곽선 흡착 반경 [픽셀]", "14"),
    ("CELL", "여유중심 스냅 셀 크기 (비우면 자동)", ""),
]

MESH_FIELDS = [
    ("EDGE_DIV", "범프 한 변당 요소 분할수", "3"),
    ("ATOL_FRAC", "sliver 판정 비율 (범프 면적 대비)", "1e-4"),
]


class ZoneDrawGui(ttk.Frame):
    """설정 입력 폼 + 그리기 창 실행 버튼."""

    def __init__(self, master):
        super().__init__(master, padding=10)
        self.pack(fill="both", expand=True)

        self._draw_win = None          # 열려 있는 그리기 창 (동시 1개)
        self._log_widget = None

        cfg = get_tool_config(TOOL_NAME)
        self.var_bump = tk.StringVar(value=cfg.get("bump_file", "bump.txt"))
        self.var_out = tk.StringVar(value=cfg.get("out_dir", ""))
        self.var_poly = tk.StringVar(value=cfg.get("poly_file", "polys.npz"))
        self.var_dia = tk.StringVar(value=cfg.get("d_default", "0.25"))
        self.var_margin = tk.StringVar(value=cfg.get("margin_pct", "2"))
        self.var_ortho = tk.BooleanVar(value=cfg.get("ortho", False))
        self.var_tri = tk.BooleanVar(value=cfg.get("mesh_tri", True))

        self.vars = {}
        for key, _label, default in GEOM_FIELDS + SNAP_FIELDS + MESH_FIELDS:
            self.vars[key] = tk.StringVar(value=cfg.get(key, default))

        self._build()

    # ---------------- 폼 ----------------
    def _build(self):
        io = ttk.LabelFrame(
            self, text="입력 / 출력"
            + ("  (범프 파일 드래그 앤 드롭 지원)" if has_dnd() else ""),
            padding=8,
        )
        io.pack(fill="x")
        io.columnconfigure(1, weight=1)

        self._path_row(io, 0, "범프 좌표 파일", self.var_bump,
                       self._browse_bump)
        self._path_row(io, 1, "출력 폴더", self.var_out, self._browse_out)
        ttk.Label(io, text="폴리곤 파일").grid(row=2, column=0, sticky="w",
                                            pady=3)
        ttk.Entry(io, textvariable=self.var_poly).grid(
            row=2, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Label(io, text="(w/r 키로 저장·불러오기)", foreground="gray").grid(
            row=2, column=2, sticky="w")

        ttk.Label(io, text="기본 볼 지름 D").grid(row=3, column=0, sticky="w",
                                              pady=3)
        ttk.Entry(io, textvariable=self.var_dia, width=14).grid(
            row=3, column=1, sticky="w", pady=3, padx=(6, 6))
        ttk.Label(
            io, text="(파일에 4번째 열 D 가 있으면 그 값이 우선)",
            foreground="gray",
        ).grid(row=3, column=2, sticky="w")

        if has_dnd():
            register_drop_target(self, self._on_drop)

        geo = ttk.LabelFrame(self, text="패키지 외곽 (컨테이너 박스)", padding=8)
        geo.pack(fill="x", pady=(8, 0))
        for i, (key, label, _d) in enumerate(GEOM_FIELDS):
            ttk.Label(geo, text=label).grid(row=i // 2, column=(i % 2) * 2,
                                            sticky="w", pady=3, padx=(0, 6))
            ttk.Entry(geo, textvariable=self.vars[key], width=16).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w",
                pady=3, padx=(0, 16))
        est = ttk.Frame(geo)
        est.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(est, text="범프 좌표에서 자동 채우기",
                   command=self._estimate_bounds).pack(side="left")
        ttk.Label(est, text="여백 [%]").pack(side="left", padx=(10, 4))
        ttk.Entry(est, textvariable=self.var_margin, width=6).pack(side="left")

        snap = ttk.LabelFrame(self, text="스냅 / 톨러런스", padding=8)
        snap.pack(fill="x", pady=(8, 0))
        snap.columnconfigure(1, weight=1)
        for i, (key, label, _d) in enumerate(SNAP_FIELDS):
            ttk.Label(snap, text=label).grid(row=i, column=0, sticky="w",
                                             pady=3)
            ttk.Entry(snap, textvariable=self.vars[key], width=16).grid(
                row=i, column=1, sticky="w", pady=3, padx=(8, 0))
        ttk.Checkbutton(snap, text="직교모드로 시작 (o 키로 전환)",
                        variable=self.var_ortho).grid(
            row=len(SNAP_FIELDS), column=0, columnspan=2, sticky="w",
            pady=(4, 0))

        mesh = ttk.LabelFrame(self, text="메시 / APDL 출력", padding=8)
        mesh.pack(fill="x", pady=(8, 0))
        mesh.columnconfigure(1, weight=1)
        for i, (key, label, _d) in enumerate(MESH_FIELDS):
            ttk.Label(mesh, text=label).grid(row=i, column=0, sticky="w",
                                             pady=3)
            ttk.Entry(mesh, textvariable=self.vars[key], width=16).grid(
                row=i, column=1, sticky="w", pady=3, padx=(8, 0))
        ttk.Checkbutton(mesh, text="매트릭스를 삼각 요소로 메시 (MSHAPE,1)",
                        variable=self.var_tri).grid(
            row=len(MESH_FIELDS), column=0, columnspan=2, sticky="w",
            pady=(4, 0))

        run = ttk.Frame(self)
        run.pack(fill="x", pady=(10, 0))
        ttk.Button(run, text="그리기 창 열기", command=self._launch).pack(
            side="left", ipadx=10, ipady=4)
        ttk.Button(run, text="기본값 복원", command=self._reset).pack(
            side="left", padx=(8, 0))
        self.var_status = tk.StringVar(
            value="설정을 확인한 뒤 [그리기 창 열기] 를 누르세요.")
        ttk.Label(self, textvariable=self.var_status, foreground="gray",
                  wraplength=560, justify="left").pack(
            fill="x", pady=(8, 0), anchor="w")

    def _path_row(self, parent, row, label, var, cmd):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1,
                                                 sticky="ew", pady=3,
                                                 padx=(6, 6))
        ttk.Button(parent, text="찾아보기", command=cmd).grid(
            row=row, column=2, sticky="w")

    # ---------------- 입력 도우미 ----------------
    def _browse_bump(self):
        p = filedialog.askopenfilename(title="범프 좌표 파일 선택",
                                       filetypes=BUMP_FILETYPES)
        if p:
            self.var_bump.set(p)
            if not self.var_out.get().strip():
                self.var_out.set(os.path.dirname(p))

    def _browse_out(self):
        p = filedialog.askdirectory(title="출력 폴더 선택")
        if p:
            self.var_out.set(p)

    def _on_drop(self, paths):
        for p in paths:
            if os.path.isdir(p):
                self.var_out.set(p)
            else:
                self.var_bump.set(p)
                if not self.var_out.get().strip():
                    self.var_out.set(os.path.dirname(p))
            break

    def _reset(self):
        self.var_poly.set("polys.npz")
        self.var_dia.set("0.25")
        self.var_margin.set("2")
        self.var_ortho.set(False)
        self.var_tri.set(True)
        for key, _label, default in GEOM_FIELDS + SNAP_FIELDS + MESH_FIELDS:
            self.vars[key].set(default)
        self.var_status.set("기본값으로 되돌렸습니다.")

    def _estimate_bounds(self):
        """범프 좌표의 최소/최대 + 여백으로 패키지 외곽을 채운다."""
        from . import core
        path = self.var_bump.get().strip()
        if not os.path.isfile(path):
            messagebox.showwarning("범프 파일 없음",
                                   f"파일을 찾을 수 없습니다:\n{path}")
            return
        try:
            d = float(self.var_dia.get())
            xy, half = core.load(path, d)
            m = float(self.var_margin.get()) / 100.0
        except Exception as e:
            messagebox.showerror("읽기 실패", f"{type(e).__name__}: {e}")
            return
        x0 = float((xy[:, 0] - half).min()); x1 = float((xy[:, 0] + half).max())
        y0 = float((xy[:, 1] - half).min()); y1 = float((xy[:, 1] + half).max())
        mx, my = (x1 - x0) * m, (y1 - y0) * m
        for key, val in (("X1", x0 - mx), ("X2", x1 + mx),
                         ("Y1", y0 - my), ("Y2", y1 + my)):
            self.vars[key].set(f"{val:.6g}")
        self.var_status.set(
            f"범프 {len(xy)}개 기준으로 외곽을 채웠습니다 "
            f"(여백 {self.var_margin.get()}%).")

    # ---------------- 설정 수집 ----------------
    def _collect(self):
        """폼 값을 core.configure() 용 dict 로 변환한다. 오류는 ValueError."""
        def num(key, cast=float, allow_blank=False):
            raw = self.vars[key].get().strip()
            if not raw:
                if allow_blank:
                    return None
                raise ValueError(f"'{key}' 값이 비어 있습니다.")
            try:
                return cast(raw)
            except ValueError:
                raise ValueError(f"'{key}' 값이 숫자가 아닙니다: {raw}")

        bump = self.var_bump.get().strip()
        if not os.path.isfile(bump):
            raise ValueError(f"범프 좌표 파일을 찾을 수 없습니다:\n{bump}")

        try:
            d_default = float(self.var_dia.get())
        except ValueError:
            raise ValueError("기본 볼 지름 D 가 숫자가 아닙니다.")

        x1, x2 = num("X1"), num("X2")
        y1, y2 = num("Y1"), num("Y2")
        if x2 <= x1 or y2 <= y1:
            raise ValueError("패키지 외곽은 X 최대 > X 최소, "
                             "Y 최대 > Y 최소 여야 합니다.")

        gtol_frac, grid_frac = num("GTOL_FRAC"), num("GRID_FRAC")
        if gtol_frac <= 0:
            raise ValueError("기하 톨러런스 비율은 0 보다 커야 합니다.")
        if grid_frac < 0:
            raise ValueError("격자 스냅 비율은 0 이상이어야 합니다.")

        out_dir = self.var_out.get().strip()
        poly = self.var_poly.get().strip() or "polys.npz"

        return {
            "BUMP_FILE": bump,
            "POLY_FILE": poly,
            "OUT_DIR": out_dir,
            "D_DEFAULT": d_default,
            "X1": x1, "X2": x2, "Y1": y1, "Y2": y2,
            "GTOL_FRAC": gtol_frac,
            "GRID_FRAC": grid_frac,
            "SNAP_PIX": num("SNAP_PIX"),
            "EDGE_PIX": num("EDGE_PIX"),
            "CELL": num("CELL", allow_blank=True),
            "ORTHO": bool(self.var_ortho.get()),
            "EDGE_DIV": num("EDGE_DIV", int),
            "MESH_TRI": bool(self.var_tri.get()),
            "ATOL_FRAC": num("ATOL_FRAC"),
        }

    def _save_config(self):
        cfg = {
            "bump_file": self.var_bump.get(),
            "out_dir": self.var_out.get(),
            "poly_file": self.var_poly.get(),
            "d_default": self.var_dia.get(),
            "margin_pct": self.var_margin.get(),
            "ortho": bool(self.var_ortho.get()),
            "mesh_tri": bool(self.var_tri.get()),
        }
        for key in self.vars:
            cfg[key] = self.vars[key].get()
        try:
            set_tool_config(TOOL_NAME, cfg)
        except Exception:
            pass

    # ---------------- 그리기 창 ----------------
    def _launch(self):
        if self._draw_win is not None and self._draw_win.winfo_exists():
            self._draw_win.deiconify()
            self._draw_win.lift()
            self.var_status.set("그리기 창이 이미 열려 있습니다.")
            return

        try:
            cfg = self._collect()
        except ValueError as e:
            messagebox.showwarning("설정 확인", str(e))
            return

        try:
            from . import core
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except Exception as e:
            messagebox.showerror(
                "의존성 오류",
                "필요한 패키지를 불러오지 못했습니다.\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "pip install numpy scipy matplotlib shapely")
            return

        core.configure(**cfg)
        try:
            xy, half = core.load(cfg["BUMP_FILE"], cfg["D_DEFAULT"])
        except Exception as e:
            messagebox.showerror("범프 파일 읽기 실패",
                                 f"{type(e).__name__}: {e}\n\n"
                                 "형식: 헤더 1줄 + 'idx,x,y[,D]'")
            return
        if len(xy) == 0:
            messagebox.showwarning("범프 없음", "좌표가 하나도 없습니다.")
            return

        self._save_config()

        win = tk.Toplevel(self)
        win.title("Zone 그리기 ― " + os.path.basename(cfg["BUMP_FILE"]))
        win.geometry("1180x860")
        win.minsize(900, 640)
        self._draw_win = win

        paned = ttk.PanedWindow(win, orient="vertical")
        paned.pack(fill="both", expand=True)

        top = ttk.Frame(paned)
        paned.add(top, weight=4)
        bottom = ttk.Frame(paned)
        paned.add(bottom, weight=1)

        side = ttk.Frame(top, padding=(6, 6))
        side.pack(side="right", fill="y")
        plot = ttk.Frame(top)
        plot.pack(side="left", fill="both", expand=True)

        fig = Figure(figsize=(9.5, 8.5), dpi=100)
        ax = fig.add_subplot(111)
        canvas = FigureCanvasTkAgg(fig, master=plot)
        widget = canvas.get_tk_widget()
        widget.pack(fill="both", expand=True)

        # 로그 창
        ttk.Label(bottom, text="로그").pack(anchor="w", padx=6)
        log_box = tk.Text(bottom, height=8, wrap="none", state="disabled",
                          font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(bottom, orient="vertical",
                                   command=log_box.yview)
        log_box.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        log_box.pack(side="left", fill="both", expand=True, padx=(6, 0),
                     pady=(0, 6))
        self._log_widget = log_box
        core.set_log_hook(self._append_log)

        app = core.App(xy, half, fig=fig, ax=ax)

        def key(k):
            """버튼을 눌러도 단축키와 같은 동작을 하게 한다."""
            app.on_key(SimpleNamespace(key=k))
            widget.focus_set()

        ttk.Label(side, text="명령", font=("", 10, "bold")).pack(anchor="w")
        for label, k in (
            ("직선으로 닫기 (c)", "c"),
            ("외곽 따라 닫기 ↺ (e)", "e"),
            ("외곽 따라 닫기 ↻ (E)", "E"),
            ("직전 점 취소 (Backspace)", "backspace"),
            ("폴리라인 취소 (Esc)", "escape"),
            ("남은 영역 채우기 (f)", "f"),
            ("폴리곤 번호 삭제 (d)", "d"),
            ("마지막 폴리곤 삭제 (x)", "x"),
            ("전체 삭제 (X)", "X"),
            ("검증 (v)", "v"),
            ("진단 표시 (b)", "b"),
            ("직교모드 (o)", "o"),
            ("전체 보기 (z)", "z"),
            ("폴리곤 저장 (w)", "w"),
            ("폴리곤 불러오기 (r)", "r"),
            ("APDL 매크로 저장 (s)", "s"),
            ("도움말 (h)", "h"),
        ):
            ttk.Button(side, text=label, width=22,
                       command=lambda kk=k: key(kk)).pack(fill="x", pady=1)

        canvas.draw()
        widget.focus_set()
        widget.bind("<Enter>", lambda _e: widget.focus_set())
        widget.bind("<Button-1>", lambda _e: widget.focus_set(), add="+")

        def on_close():
            core.set_log_hook(None)
            self._log_widget = None
            try:
                for cid in getattr(app, "_cids", []):
                    fig.canvas.mpl_disconnect(cid)
            except Exception:
                pass
            self._draw_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self.var_status.set(
            f"그리기 창 실행 중 ― 범프 {len(xy)}개, 출력 폴더: "
            + (os.path.abspath(cfg["OUT_DIR"]) if cfg["OUT_DIR"]
               else os.path.abspath(os.getcwd())))

    def _append_log(self, msg):
        box = self._log_widget
        if box is None:
            return
        try:
            box.configure(state="normal")
            box.insert("end", msg + "\n")
            box.see("end")
            box.configure(state="disabled")
        except tk.TclError:
            self._log_widget = None


def build_gui(parent):
    """tool_box 런처가 넘겨주는 parent 프레임에 GUI 를 구성한다."""
    return ZoneDrawGui(parent)
