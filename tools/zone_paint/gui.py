# -*- coding: utf-8 -*-
"""Zone 페인터 설정 GUI.

원본 zone_paint.py 는 모듈 상단 상수를 직접 고쳐야 했다. 이 GUI 는 그 상수들을
입력받아 ``core.configure()`` 로 주입한 뒤, 칠하기 화면(matplotlib)을 별도의
tkinter 창에 임베드해 띄운다. 칠하기/경계 생성/검증/APDL 출력 로직은 원본
그대로이며, 단축키와 같은 동작을 하는 명령 버튼과 로그 창을 함께 제공한다.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

from config import get_tool_config, set_tool_config
from tools._dnd_helper import has_dnd, register_drop_target

TOOL_NAME = "zone_paint"

BUMP_FILETYPES = [
    ("범프 좌표 파일", "*.txt *.csv *.dat"),
    ("모든 파일", "*.*"),
]

METHOD_HELP = {
    "ortho":   "거리장 경계 + min-link, 수평·수직 변만",
    "minlink": "거리장 경계 + min-link, 각도 제한 없음",
    "voronoi": "사각형 외곽선 샘플 Voronoi (이격 최대)",
    "convex":  "존 쌍마다 최대마진 직선 1개 (볼록 존 한정)",
}

GEOM_FIELDS = [
    ("X1", "X 최소", "-12.5"),
    ("X2", "X 최대", "12.5"),
    ("Y1", "Y 최소", "-12.5"),
    ("Y2", "Y 최대", "12.5"),
]

GEN_FIELDS = [
    ("CELL", "래스터/거리장 셀 크기 (비우면 자동)", ""),
    ("CLEAR", "절대 최소 여유 [형상 단위]", "0.0"),
    ("CLEAR_FRAC", "통로 반폭 대비 여유 비율 (0~0.9)", "0.40"),
    ("SAMPLE_SIDE", "voronoi: 사각형 한 변당 샘플 수", "2"),
    ("SNAP", "좌표 반올림 자릿수", "9"),
    ("EDGE_TOL", "외곽 판정 톨러런스", "1e-7"),
]

MESH_FIELDS = [
    ("EDGE_DIV", "범프 한 변당 요소 분할수", "3"),
]


class ZonePaintGui(ttk.Frame):
    """설정 입력 폼 + 칠하기 창 실행 버튼."""

    def __init__(self, master):
        super().__init__(master, padding=10)
        self.pack(fill="both", expand=True)

        self._draw_win = None          # 열려 있는 칠하기 창 (동시 1개)
        self._log_widget = None
        self._app = None

        cfg = get_tool_config(TOOL_NAME)
        self.var_bump = tk.StringVar(value=cfg.get("bump_file", "bump.txt"))
        self.var_out = tk.StringVar(value=cfg.get("out_dir", ""))
        self.var_seed = tk.StringVar(value=cfg.get("seed_dir", "zone_sets"))
        self.var_auto_file = tk.StringVar(
            value=cfg.get("auto_file", "_autosave.npz"))
        self.var_autosave = tk.BooleanVar(value=cfg.get("autosave", True))
        self.var_dia = tk.StringVar(value=cfg.get("d_default", "0.25"))
        self.var_margin = tk.StringVar(value=cfg.get("margin_pct", "2"))
        self.var_method = tk.StringVar(value=cfg.get("method", "minlink"))
        self.var_recenter = tk.BooleanVar(value=cfg.get("recenter", True))
        self.var_relax = tk.BooleanVar(value=cfg.get("relax_end", True))
        self.var_bool = tk.StringVar(value=cfg.get("bool_op", "ASBA"))
        self.var_tri = tk.BooleanVar(value=cfg.get("mesh_tri", True))

        self.vars = {}
        for key, _label, default in GEOM_FIELDS + GEN_FIELDS + MESH_FIELDS:
            self.vars[key] = tk.StringVar(value=cfg.get(key, default))

        self._build()

    # ---------------- 폼 ----------------
    def _build(self):
        io = ttk.LabelFrame(
            self, text="입력 / 출력"
            + ("  (범프 파일 드래그 앤 드롭 지원)" if has_dnd() else ""),
            padding=8)
        io.pack(fill="x")
        io.columnconfigure(1, weight=1)

        self._path_row(io, 0, "범프 좌표 파일", self.var_bump, self._browse_bump)
        self._path_row(io, 1, "출력 폴더", self.var_out, self._browse_out)

        ttk.Label(io, text="스냅샷 폴더").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(io, textvariable=self.var_seed).grid(
            row=2, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Label(io, text="(w/r/R 키)", foreground="gray").grid(
            row=2, column=2, sticky="w")

        ttk.Label(io, text="자동저장 파일").grid(row=3, column=0, sticky="w",
                                            pady=3)
        ttk.Entry(io, textvariable=self.var_auto_file).grid(
            row=3, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Checkbutton(io, text="자동저장", variable=self.var_autosave).grid(
            row=3, column=2, sticky="w")

        ttk.Label(io, text="기본 볼 지름 D").grid(row=4, column=0, sticky="w",
                                              pady=3)
        ttk.Entry(io, textvariable=self.var_dia, width=14).grid(
            row=4, column=1, sticky="w", pady=3, padx=(6, 6))
        ttk.Label(io, text="(파일에 4번째 열 D 가 있으면 그 값이 우선)",
                  foreground="gray").grid(row=4, column=2, sticky="w")

        if has_dnd():
            register_drop_target(self, self._on_drop)

        geo = ttk.LabelFrame(self, text="패키지 외곽", padding=8)
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

        gen = ttk.LabelFrame(self, text="경계 생성", padding=8)
        gen.pack(fill="x", pady=(8, 0))
        gen.columnconfigure(1, weight=1)

        ttk.Label(gen, text="생성 방법").grid(row=0, column=0, sticky="w", pady=3)
        mrow = ttk.Frame(gen)
        mrow.grid(row=0, column=1, sticky="ew", pady=3, padx=(8, 0))
        cb = ttk.Combobox(mrow, textvariable=self.var_method, width=12,
                          state="readonly", values=list(METHOD_HELP))
        cb.pack(side="left")
        self._method_lbl = ttk.Label(mrow, foreground="gray")
        self._method_lbl.pack(side="left", padx=(8, 0))
        self.var_method.trace_add("write", lambda *_a: self._sync_method())
        self._sync_method()

        for i, (key, label, _d) in enumerate(GEN_FIELDS, start=1):
            ttk.Label(gen, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(gen, textvariable=self.vars[key], width=16).grid(
                row=i, column=1, sticky="w", pady=3, padx=(8, 0))
        row = len(GEN_FIELDS) + 1
        ttk.Checkbutton(gen, text="분기점을 통로 중앙으로 재배치 (RECENTER)",
                        variable=self.var_recenter).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(gen, text="외곽 끝점 완화로 마지막 변 꺾임 제거 (RELAX_END)",
                        variable=self.var_relax).grid(
            row=row + 1, column=0, columnspan=2, sticky="w")

        mesh = ttk.LabelFrame(self, text="메시 / APDL 출력", padding=8)
        mesh.pack(fill="x", pady=(8, 0))
        mesh.columnconfigure(1, weight=1)
        ttk.Label(mesh, text="부울 연산").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(mesh, textvariable=self.var_bool, width=12,
                     state="readonly", values=["ASBA", "AOVLAP"]).grid(
            row=0, column=1, sticky="w", pady=3, padx=(8, 0))
        for i, (key, label, _d) in enumerate(MESH_FIELDS, start=1):
            ttk.Label(mesh, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(mesh, textvariable=self.vars[key], width=16).grid(
                row=i, column=1, sticky="w", pady=3, padx=(8, 0))
        ttk.Checkbutton(mesh, text="매트릭스를 삼각 요소로 메시 (MSHAPE,1)",
                        variable=self.var_tri).grid(
            row=len(MESH_FIELDS) + 1, column=0, columnspan=2, sticky="w",
            pady=(4, 0))

        run = ttk.Frame(self)
        run.pack(fill="x", pady=(10, 0))
        ttk.Button(run, text="칠하기 창 열기", command=self._launch).pack(
            side="left", ipadx=10, ipady=4)
        ttk.Button(run, text="기본값 복원", command=self._reset).pack(
            side="left", padx=(8, 0))
        self.var_status = tk.StringVar(
            value="설정을 확인한 뒤 [칠하기 창 열기] 를 누르세요.")
        ttk.Label(self, textvariable=self.var_status, foreground="gray",
                  wraplength=580, justify="left").pack(
            fill="x", pady=(8, 0), anchor="w")

    def _path_row(self, parent, row, label, var, cmd):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=var).grid(
            row=row, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Button(parent, text="찾아보기", command=cmd).grid(
            row=row, column=2, sticky="w")

    def _sync_method(self):
        self._method_lbl.configure(
            text=METHOD_HELP.get(self.var_method.get(), ""))

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
        self.var_seed.set("zone_sets")
        self.var_auto_file.set("_autosave.npz")
        self.var_autosave.set(True)
        self.var_dia.set("0.25")
        self.var_margin.set("2")
        self.var_method.set("minlink")
        self.var_recenter.set(True)
        self.var_relax.set(True)
        self.var_bool.set("ASBA")
        self.var_tri.set(True)
        for key, _label, default in GEOM_FIELDS + GEN_FIELDS + MESH_FIELDS:
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
            xy, half = core.load(path, float(self.var_dia.get()))
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

        frac = num("CLEAR_FRAC")
        if not (0.0 <= frac <= 0.9):
            raise ValueError("통로 반폭 대비 여유 비율은 0 ~ 0.9 여야 합니다.")
        cell = num("CELL", allow_blank=True)
        if cell is not None and cell <= 0:
            raise ValueError("셀 크기는 0 보다 커야 합니다.")
        side = num("SAMPLE_SIDE", int)
        if side < 1:
            raise ValueError("voronoi 샘플 수는 1 이상이어야 합니다.")

        return {
            "BUMP_FILE": bump,
            "SEED_DIR": self.var_seed.get().strip() or "zone_sets",
            "AUTO_FILE": self.var_auto_file.get().strip() or "_autosave.npz",
            "OUT_DIR": self.var_out.get().strip(),
            "AUTOSAVE": bool(self.var_autosave.get()),
            "D_DEFAULT": d_default,
            "X1": x1, "X2": x2, "Y1": y1, "Y2": y2,
            "METHOD": self.var_method.get(),
            "CELL": cell,
            "CLEAR": num("CLEAR"),
            "CLEAR_FRAC": frac,
            "RECENTER": bool(self.var_recenter.get()),
            "SAMPLE_SIDE": side,
            "SNAP": num("SNAP", int),
            "RELAX_END": bool(self.var_relax.get()),
            "EDGE_TOL": num("EDGE_TOL"),
            "BOOL_OP": self.var_bool.get(),
            "EDGE_DIV": num("EDGE_DIV", int),
            "MESH_TRI": bool(self.var_tri.get()),
        }

    def _save_config(self):
        cfg = {
            "bump_file": self.var_bump.get(),
            "out_dir": self.var_out.get(),
            "seed_dir": self.var_seed.get(),
            "auto_file": self.var_auto_file.get(),
            "autosave": bool(self.var_autosave.get()),
            "d_default": self.var_dia.get(),
            "margin_pct": self.var_margin.get(),
            "method": self.var_method.get(),
            "recenter": bool(self.var_recenter.get()),
            "relax_end": bool(self.var_relax.get()),
            "bool_op": self.var_bool.get(),
            "mesh_tri": bool(self.var_tri.get()),
        }
        for key in self.vars:
            cfg[key] = self.vars[key].get()
        try:
            set_tool_config(TOOL_NAME, cfg)
        except Exception:
            pass

    # ---------------- 칠하기 창 ----------------
    def _launch(self):
        if self._draw_win is not None and self._draw_win.winfo_exists():
            self._draw_win.deiconify()
            self._draw_win.lift()
            self.var_status.set("칠하기 창이 이미 열려 있습니다.")
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
        win.title("Zone 칠하기 ― " + os.path.basename(cfg["BUMP_FILE"]))
        win.geometry("1220x880")
        win.minsize(940, 660)
        self._draw_win = win

        paned = ttk.PanedWindow(win, orient="vertical")
        paned.pack(fill="both", expand=True)
        top = ttk.Frame(paned); paned.add(top, weight=4)
        bottom = ttk.Frame(paned); paned.add(bottom, weight=1)

        side = ttk.Frame(top, padding=(6, 6))
        side.pack(side="right", fill="y")
        plot = ttk.Frame(top)
        plot.pack(side="left", fill="both", expand=True)

        fig = Figure(figsize=(9.5, 8.5), dpi=100)
        ax = fig.add_subplot(111)
        canvas = FigureCanvasTkAgg(fig, master=plot)
        widget = canvas.get_tk_widget()
        widget.pack(fill="both", expand=True)

        ttk.Label(bottom, text="로그").pack(anchor="w", padx=6)
        log_box = tk.Text(bottom, height=9, wrap="none", state="disabled",
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
        self._app = app

        def key(k):
            """버튼을 눌러도 단축키와 같은 동작을 하게 한다."""
            app.on_key(SimpleNamespace(key=k))
            widget.focus_set()

        # ---- 현재 구역 번호 ----
        zf = ttk.LabelFrame(side, text="현재 구역", padding=6)
        zf.pack(fill="x", pady=(0, 6))
        zone_var = tk.IntVar(value=app.cur)
        sb = ttk.Spinbox(zf, from_=0, to=999, width=6, textvariable=zone_var)
        sb.pack(side="left")

        def set_zone():
            try:
                app.cur = max(0, int(zone_var.get()))
            except (tk.TclError, ValueError):
                return
            app.draw()
            widget.focus_set()

        sb.configure(command=set_zone)
        sb.bind("<Return>", lambda _e: set_zone())
        ttk.Button(zf, text="이전 (b)", width=8,
                   command=lambda: key("b")).pack(side="left", padx=(6, 2))
        ttk.Button(zf, text="다음 (n)", width=8,
                   command=lambda: key("n")).pack(side="left")

        # ---- 생성 방법 ----
        mf = ttk.LabelFrame(side, text="생성 방법", padding=6)
        mf.pack(fill="x", pady=(0, 6))
        method_var = tk.StringVar(value=app.method)
        ttk.Combobox(mf, textvariable=method_var, width=12, state="readonly",
                     values=list(METHOD_HELP)).pack(fill="x")

        def on_method_pick(*_a):
            # sync_state() 가 같은 값을 되쓸 때도 trace 는 발동한다.
            # 값이 실제로 바뀐 경우에만 반영해야 set_method() 가 생성해 둔
            # 다각형(app.polys)을 지우는 되먹임 고리가 생기지 않는다.
            if method_var.get() != app.method:
                app.set_method(method_var.get())
                widget.focus_set()

        method_var.trace_add("write", on_method_pick)

        # 엔진이 다시 그릴 때 구역 번호·방법 표시가 따라오게 한다
        def sync_state(a):
            try:
                if zone_var.get() != a.cur:
                    zone_var.set(a.cur)
                if method_var.get() != a.method:
                    method_var.set(a.method)
            except tk.TclError:
                pass

        app.on_state = sync_state

        ttk.Label(side, text="명령", font=("", 10, "bold")).pack(anchor="w")
        for label, k in (
            ("사각선택 on/off (l)", "l"),
            ("직전 동작 취소 (u)", "u"),
            ("현재 구역 해제 (c)", "c"),
            ("미지정 자동 흡수 (a)", "a"),
            ("스냅샷 저장 (w)", "w"),
            ("최근 스냅샷 (r)", "r"),
            ("이전 스냅샷 (R)", "R"),
            ("자동저장본 복구 (A)", "A"),
            ("다각형 생성 (g)", "g"),
            ("네 방법 비교 (G)", "G"),
            ("여유 비율 - ([)", "["),
            ("여유 비율 + (])", "]"),
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
            app.on_state = None
            try:
                for cid in getattr(app, "_cids", []):
                    fig.canvas.mpl_disconnect(cid)
            except Exception:
                pass
            self._app = None
            self._draw_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self.var_status.set(
            f"칠하기 창 실행 중 ― 범프 {len(xy)}개, 출력 폴더: "
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
    return ZonePaintGui(parent)
