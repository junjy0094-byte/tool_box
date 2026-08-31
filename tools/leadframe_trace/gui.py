# -*- coding: utf-8 -*-
"""Leadframe 그리기 설정 GUI.

원본 trace_gui.py 는 모듈 상단 상수를 직접 고쳐야 했다. 이 GUI 는 그 상수들을
입력받아 ``core.configure()`` 로 주입한 뒤, 트레이싱 화면(matplotlib)을 별도의
tkinter 창에 임베드해 띄운다. 작도/스냅/구속/편집/내보내기 로직은 원본 그대로이며,
단축키와 같은 동작을 하는 명령 버튼과 로그 창을 함께 제공한다.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

from config import get_tool_config, set_tool_config
from tools._dnd_helper import has_dnd, register_drop_target

TOOL_NAME = "leadframe_trace"

IMG_FILETYPES = [
    ("이미지", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
    ("모든 파일", "*.*"),
]

SCALE_FIELDS = [
    ("PKG_WIDTH_UM", "이미지 가로 전체의 실제 폭 [um]", "8000.0"),
    ("OFF_X_UM", "이미지 중심 X 오프셋 [um]", "0.0"),
    ("OFF_Y_UM", "이미지 중심 Y 오프셋 [um]", "0.0"),
]

DRAW_FIELDS = [
    ("GRID_UM", "초기 그리드 피치 [um]", "50.0"),
    ("MESH_UM", "목표 요소 크기 [um] (autofit 허용범위)", "50.0"),
    ("ROUND_DEC", "좌표 반올림 자리수 (-1 = 반올림 안 함)", "3"),
]

# (버튼 라벨, 단축키) — 그룹별
CMD_GROUPS = [
    ("모드", [
        ("모델 / 보조선 (a)", "a"),
        ("모델 / TRIM (t)", "t"),
        ("모델 / 선택 (s)", "s"),
        ("레퍼런스 지정 (r)", "r"),
    ]),
    ("작도", [
        ("닫힌 도형 확정 (c)", "c"),
        ("홀로 확정 (h)", "h"),
        ("열린 폴리라인 (x)", "x"),
        ("마지막 점 취소 (u)", "u"),
        ("마지막 폴리곤 삭제 (d)", "d"),
        ("마지막 보조선 삭제 (z)", "z"),
    ]),
    ("구속", [
        ("직교 (o)", "o"),
        ("레퍼런스 평행 (p)", "p"),
        ("레퍼런스 수직 (e)", "e"),
    ]),
    ("편집 (선택 모드)", [
        ("복사 (Ctrl+C)", "ctrl+c"),
        ("붙여넣기 (Ctrl+V)", "ctrl+v"),
        ("삭제 (Delete)", "delete"),
        ("반시계 회전 (.)", "."),
        ("시계 회전 (,)", ","),
        ("회전 스텝 순환 (n)", "n"),
        ("좌우 반전 (f)", "f"),
        ("상하 반전 (v)", "v"),
        ("기준점 토글 (b)", "b"),
        ("선택 해제 (Esc)", "escape"),
    ]),
    ("스냅 / AUTOFIT", [
        ("그리드 스냅 (g)", "g"),
        ("그리드 1/2 ([)", "["),
        ("그리드 2배 (])", "]"),
        ("autofit on/off (k)", "k"),
        ("허용범위 1/2 (-)", "-"),
        ("허용범위 2배 (=)", "="),
    ]),
    ("좌표 / 파일", [
        ("자리수 - (1)", "1"),
        ("자리수 + (2)", "2"),
        ("자리수 재적용 (3)", "3"),
        ("저장: APDL+JSON (w)", "w"),
        ("JSON 불러오기 (l)", "l"),
        ("JSON 추가 (L)", "L"),
        ("도움말 (?)", "?"),
    ]),
]


class LeadframeTraceGui(ttk.Frame):
    """설정 입력 폼 + 트레이싱 창 실행 버튼."""

    def __init__(self, master):
        super().__init__(master, padding=10)
        self.pack(fill="both", expand=True)

        self._draw_win = None          # 열려 있는 트레이싱 창 (동시 1개)
        self._log_widget = None
        self._app = None

        cfg = get_tool_config(TOOL_NAME)
        self.var_img = tk.StringVar(value=cfg.get("img_path", "leadframe.png"))
        self.var_out = tk.StringVar(value=cfg.get("out_dir", ""))
        self.var_apdl = tk.StringVar(value=cfg.get("out_apdl", "geom.mac"))
        self.var_json = tk.StringVar(value=cfg.get("out_json", "polys.json"))
        self.var_snapv = tk.BooleanVar(value=cfg.get("snap_vertex", True))

        self.vars = {}
        for key, _label, default in SCALE_FIELDS + DRAW_FIELDS:
            self.vars[key] = tk.StringVar(value=cfg.get(key, default))

        self._build()

    # ---------------- 폼 ----------------
    def _build(self):
        io = ttk.LabelFrame(
            self, text="입력 / 출력"
            + ("  (이미지 드래그 앤 드롭 지원)" if has_dnd() else ""),
            padding=8)
        io.pack(fill="x")
        io.columnconfigure(1, weight=1)

        ttk.Label(io, text="배경 이미지").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(io, textvariable=self.var_img).grid(
            row=0, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Button(io, text="찾아보기", command=self._browse_img).grid(
            row=0, column=2, sticky="w")

        ttk.Label(io, text="출력 폴더").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(io, textvariable=self.var_out).grid(
            row=1, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Button(io, text="찾아보기", command=self._browse_out).grid(
            row=1, column=2, sticky="w")

        ttk.Label(io, text="APDL 매크로 파일").grid(row=2, column=0, sticky="w",
                                              pady=3)
        ttk.Entry(io, textvariable=self.var_apdl).grid(
            row=2, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Label(io, text="(w 키로 저장)", foreground="gray").grid(
            row=2, column=2, sticky="w")

        ttk.Label(io, text="폴리곤 JSON 파일").grid(row=3, column=0, sticky="w",
                                              pady=3)
        ttk.Entry(io, textvariable=self.var_json).grid(
            row=3, column=1, sticky="ew", pady=3, padx=(6, 6))
        ttk.Label(io, text="(l / L 키로 불러오기)", foreground="gray").grid(
            row=3, column=2, sticky="w")

        if has_dnd():
            register_drop_target(self, self._on_drop)

        sc = ttk.LabelFrame(self, text="이미지 축척", padding=8)
        sc.pack(fill="x", pady=(8, 0))
        sc.columnconfigure(1, weight=1)
        for i, (key, label, _d) in enumerate(SCALE_FIELDS):
            ttk.Label(sc, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(sc, textvariable=self.vars[key], width=16).grid(
                row=i, column=1, sticky="w", pady=3, padx=(8, 0))
        self._px_lbl = ttk.Label(sc, foreground="gray")
        self._px_lbl.grid(row=len(SCALE_FIELDS), column=0, columnspan=2,
                          sticky="w", pady=(4, 0))
        ttk.Button(sc, text="이미지 크기 확인",
                   command=self._probe_image).grid(
            row=len(SCALE_FIELDS) + 1, column=0, sticky="w", pady=(4, 0))

        dr = ttk.LabelFrame(self, text="작도 기본값", padding=8)
        dr.pack(fill="x", pady=(8, 0))
        dr.columnconfigure(1, weight=1)
        for i, (key, label, _d) in enumerate(DRAW_FIELDS):
            ttk.Label(dr, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(dr, textvariable=self.vars[key], width=16).grid(
                row=i, column=1, sticky="w", pady=3, padx=(8, 0))
        ttk.Checkbutton(dr, text="기존 정점 스냅 사용 (SNAP_VERTEX)",
                        variable=self.var_snapv).grid(
            row=len(DRAW_FIELDS), column=0, columnspan=2, sticky="w",
            pady=(4, 0))

        run = ttk.Frame(self)
        run.pack(fill="x", pady=(10, 0))
        ttk.Button(run, text="그리기 창 열기", command=self._launch).pack(
            side="left", ipadx=10, ipady=4)
        ttk.Button(run, text="기본값 복원", command=self._reset).pack(
            side="left", padx=(8, 0))
        self.var_status = tk.StringVar(
            value="이미지와 축척을 확인한 뒤 [그리기 창 열기] 를 누르세요.")
        ttk.Label(self, textvariable=self.var_status, foreground="gray",
                  wraplength=580, justify="left").pack(
            fill="x", pady=(8, 0), anchor="w")

    # ---------------- 입력 도우미 ----------------
    def _browse_img(self):
        p = filedialog.askopenfilename(title="배경 이미지 선택",
                                       filetypes=IMG_FILETYPES)
        if p:
            self.var_img.set(p)
            if not self.var_out.get().strip():
                self.var_out.set(os.path.dirname(p))
            self._probe_image()

    def _browse_out(self):
        p = filedialog.askdirectory(title="출력 폴더 선택")
        if p:
            self.var_out.set(p)

    def _on_drop(self, paths):
        for p in paths:
            if os.path.isdir(p):
                self.var_out.set(p)
            else:
                self.var_img.set(p)
                if not self.var_out.get().strip():
                    self.var_out.set(os.path.dirname(p))
                self._probe_image()
            break

    def _probe_image(self):
        """이미지 픽셀 크기를 읽어 um 환산값을 미리 보여 준다."""
        path = self.var_img.get().strip()
        if not os.path.isfile(path):
            self._px_lbl.configure(text="이미지 파일을 찾을 수 없습니다.")
            return
        try:
            from . import core
            img = core.load_image(path)
            h, w = img.shape[:2]
            pw = float(self.vars["PKG_WIDTH_UM"].get())
        except Exception as e:
            self._px_lbl.configure(text=f"{type(e).__name__}: {e}")
            return
        s = pw / w
        self._px_lbl.configure(
            text=f"{w} x {h} px  →  {w*s:.1f} x {h*s:.1f} um "
                 f"(1 px = {s:.3f} um)")

    def _reset(self):
        self.var_apdl.set("geom.mac")
        self.var_json.set("polys.json")
        self.var_snapv.set(True)
        for key, _label, default in SCALE_FIELDS + DRAW_FIELDS:
            self.vars[key].set(default)
        self.var_status.set("기본값으로 되돌렸습니다.")

    # ---------------- 설정 수집 ----------------
    def _collect(self):
        """폼 값을 core.configure() 용 dict 로 변환한다. 오류는 ValueError."""
        def num(key, cast=float):
            raw = self.vars[key].get().strip()
            if not raw:
                raise ValueError(f"'{key}' 값이 비어 있습니다.")
            try:
                return cast(raw)
            except ValueError:
                raise ValueError(f"'{key}' 값이 숫자가 아닙니다: {raw}")

        img = self.var_img.get().strip()
        if not os.path.isfile(img):
            raise ValueError(f"배경 이미지를 찾을 수 없습니다:\n{img}")

        pw = num("PKG_WIDTH_UM")
        if pw <= 0:
            raise ValueError("이미지 실제 폭은 0 보다 커야 합니다.")
        grid = num("GRID_UM")
        if grid <= 0:
            raise ValueError("그리드 피치는 0 보다 커야 합니다.")
        mesh = num("MESH_UM")
        if mesh <= 0:
            raise ValueError("목표 요소 크기는 0 보다 커야 합니다.")
        dec = num("ROUND_DEC", int)
        if not (-1 <= dec <= 6):
            raise ValueError("반올림 자리수는 -1 ~ 6 이어야 합니다.")

        return {
            "IMG_PATH": img,
            "PKG_WIDTH_UM": pw,
            "GRID_UM": grid,
            "MESH_UM": mesh,
            "ROUND_DEC": dec,
            "OFF_X_UM": num("OFF_X_UM"),
            "OFF_Y_UM": num("OFF_Y_UM"),
            "SNAP_VERTEX": bool(self.var_snapv.get()),
            "OUT_APDL": self.var_apdl.get().strip() or "geom.mac",
            "OUT_JSON": self.var_json.get().strip() or "polys.json",
            "OUT_DIR": self.var_out.get().strip(),
        }

    def _save_config(self):
        cfg = {
            "img_path": self.var_img.get(),
            "out_dir": self.var_out.get(),
            "out_apdl": self.var_apdl.get(),
            "out_json": self.var_json.get(),
            "snap_vertex": bool(self.var_snapv.get()),
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
            from matplotlib.backends.backend_tkagg import (
                FigureCanvasTkAgg, NavigationToolbar2Tk)
        except Exception as e:
            messagebox.showerror(
                "의존성 오류",
                "필요한 패키지를 불러오지 못했습니다.\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "pip install matplotlib pillow")
            return

        core.configure(**cfg)
        try:
            img = core.load_image(cfg["IMG_PATH"])
        except Exception as e:
            messagebox.showerror("이미지 읽기 실패",
                                 f"{type(e).__name__}: {e}")
            return

        self._save_config()

        win = tk.Toplevel(self)
        win.title("Leadframe 그리기 ― " + os.path.basename(cfg["IMG_PATH"]))
        win.geometry("1280x900")
        win.minsize(980, 680)
        self._draw_win = win

        paned = ttk.PanedWindow(win, orient="vertical")
        paned.pack(fill="both", expand=True)
        top = ttk.Frame(paned); paned.add(top, weight=5)
        bottom = ttk.Frame(paned); paned.add(bottom, weight=1)

        # 명령 패널은 항목이 많아 스크롤 가능한 컨테이너에 담는다
        side_holder = ttk.Frame(top)
        side_holder.pack(side="right", fill="y")
        side_canvas = tk.Canvas(side_holder, width=210, borderwidth=0,
                                highlightthickness=0)
        side_sb = ttk.Scrollbar(side_holder, orient="vertical",
                                command=side_canvas.yview)
        side_canvas.configure(yscrollcommand=side_sb.set)
        side_canvas.pack(side="left", fill="y", expand=True)
        side_sb.pack(side="right", fill="y")
        side = ttk.Frame(side_canvas, padding=(4, 4))
        side_canvas.create_window((0, 0), window=side, anchor="nw")
        side.bind("<Configure>",
                  lambda _e: side_canvas.configure(
                      scrollregion=side_canvas.bbox("all")))

        plot = ttk.Frame(top)
        plot.pack(side="left", fill="both", expand=True)

        fig = Figure(figsize=(9.5, 8.5), dpi=100)
        ax = fig.add_subplot(111)
        canvas = FigureCanvasTkAgg(fig, master=plot)
        widget = canvas.get_tk_widget()
        tb_frame = ttk.Frame(plot)
        tb_frame.pack(side="bottom", fill="x")
        widget.pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, tb_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="left", fill="x")

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

        app = core.TraceApp(img, fig=fig, ax=ax)
        self._app = app
        app.ask_path = lambda: filedialog.askopenfilename(
            parent=win, title="폴리곤 JSON 열기",
            initialdir=(cfg["OUT_DIR"] or os.getcwd()),
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")])

        def key(k):
            """버튼을 눌러도 단축키와 같은 동작을 하게 한다."""
            app.on_key(SimpleNamespace(key=k))
            widget.focus_set()

        for group, items in CMD_GROUPS:
            lf = ttk.LabelFrame(side, text=group, padding=4)
            lf.pack(fill="x", pady=(0, 4))
            for label, k in items:
                ttk.Button(lf, text=label, width=20,
                           command=lambda kk=k: key(kk)).pack(fill="x", pady=1)

        canvas.draw()
        widget.focus_set()
        widget.bind("<Enter>", lambda _e: widget.focus_set())
        widget.bind("<Button-1>", lambda _e: widget.focus_set(), add="+")

        def on_close():
            core.set_log_hook(None)
            self._log_widget = None
            app.ask_path = None
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
            f"그리기 창 실행 중 ― {os.path.basename(cfg['IMG_PATH'])}, "
            "출력 폴더: "
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
    return LeadframeTraceGui(parent)
