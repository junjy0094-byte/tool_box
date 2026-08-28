"""Strain → CTE 변환 도구.

ANSYS APDL 의 열변형(THSX) mp 코드를 붙여넣으면 온도별 CTE 를 계산해
표 또는 APDL 코드 형태로 클립보드에 복사한다.

핵심 계산은 수치미분으로 CTE = dε/dT 를 구하는 것이다.
(첫 점은 전진 차분, 마지막 점은 후진 차분, 중간 점은 중심 차분)
"""

import platform
import re
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple

import numpy as np

from tools.base_tool import BaseTool

EXAMPLE_INPUT = """mptemp,1,-65$mpdata,thsx,cu,1,-0.001
mptemp,2,-40$mpdata,thsx,cu,2, 0.000
mptemp,3, 25$mpdata,thsx,cu,3, 0.001
mptemp,4, 60$mpdata,thsx,cu,4, 0.002
mptemp,5, 80$mpdata,thsx,cu,5, 0.003"""

# MPDATA 는 오타(mpada)로 적히는 경우가 잦아 함께 허용한다.
_MPTEMP_KEYS = {"mptemp"}
_MPDATA_KEYS = {"mpdata", "mpdat", "mpada", "mpdate"}


# ── 파싱 ─────────────────────────────────────────


def _to_float(token: str):
    """숫자로 변환되면 float, 아니면 None."""
    try:
        return float(token.strip())
    except (TypeError, ValueError):
        return None


def _to_index(token: str):
    """MPTEMP/MPDATA 의 STLOC(시작 위치)을 정수로 변환한다."""
    v = _to_float(token)
    return int(v) if v is not None else None


def parse_mp_block(text: str) -> Tuple[List[Tuple[float, float]], str, str]:
    """입력 텍스트에서 (온도, strain) 쌍을 뽑아낸다.

    지원 형식:
      - ``mptemp,1,-65$mpdata,thsx,cu,1,-0.001``  ($ 로 이어 붙인 한 줄)
      - ``mptemp,1,-65`` / ``mpdata,thsx,cu,1,-0.001``  (여러 줄로 분리)
      - ``mptemp,1,-65,-40,25`` 처럼 한 줄에 여러 값 (STLOC 부터 순서대로)
      - ``-65, -0.001`` 같은 온도/strain 2열 숫자 데이터

    Returns:
        (pairs, material, label) — pairs 는 [(temp, strain), ...],
        material/label 은 MPDATA 에서 읽은 재료명과 물성 라벨.
    """
    temps: Dict[int, float] = {}
    strains: Dict[int, float] = {}
    plain: List[Tuple[float, float]] = []
    material = ""
    label = ""

    for raw_line in text.splitlines():
        line = raw_line.split("!")[0]  # APDL 주석 제거
        for seg in line.split("$"):
            seg = seg.strip()
            if not seg:
                continue

            toks = [t.strip() for t in seg.split(",")]
            key = toks[0].lower()

            # MPTEMP, STLOC, T1, T2, ...
            if key in _MPTEMP_KEYS and len(toks) >= 3:
                stloc = _to_index(toks[1])
                if stloc is not None:
                    for off, tok in enumerate(toks[2:]):
                        v = _to_float(tok)
                        if v is not None:
                            temps[stloc + off] = v
                    continue

            # MPDATA, Lab, MAT, STLOC, C1, C2, ...
            if key in _MPDATA_KEYS and len(toks) >= 5:
                stloc = _to_index(toks[3])
                if stloc is not None:
                    label = label or toks[1]
                    material = material or toks[2]
                    for off, tok in enumerate(toks[4:]):
                        v = _to_float(tok)
                        if v is not None:
                            strains[stloc + off] = v
                    continue

            # 키워드가 없으면 숫자 2열(온도, strain)로 해석한다.
            nums = [_to_float(t) for t in re.split(r"[,\s]+", seg)]
            nums = [n for n in nums if n is not None]
            if len(nums) >= 2:
                plain.append((nums[0], nums[1]))

    common = sorted(set(temps) & set(strains))
    if common:
        pairs = [(temps[i], strains[i]) for i in common]
    else:
        pairs = plain

    return pairs, material, label


# ── 핵심 계산 ────────────────────────────────────


def strain_to_cte_derivative(temperatures, strains):
    """미분 방법: CTE = dε/dT — 각 온도점에서의 순간 CTE 를 계산한다.

    Returns:
        (temps, strains, cte) — 모두 온도 오름차순으로 정렬된 배열.
    """
    temps = np.asarray(temperatures, dtype=float)
    eps = np.asarray(strains, dtype=float)

    if temps.size < 2:
        raise ValueError("CTE 계산에는 온도점이 2개 이상 필요합니다.")

    # 온도 순서대로 정렬
    sort_idx = np.argsort(temps)
    temps = temps[sort_idx]
    eps = eps[sort_idx]

    dup = temps[:-1][np.diff(temps) == 0]
    if dup.size:
        raise ValueError(f"중복된 온도점이 있습니다: {dup[0]:g}")

    # CTE 계산 (수치미분)
    cte = np.zeros(len(temps))
    for i in range(len(temps)):
        if i == 0:
            # 첫 번째 점: 전진 차분
            cte[i] = (eps[i + 1] - eps[i]) / (temps[i + 1] - temps[i])
        elif i == len(temps) - 1:
            # 마지막 점: 후진 차분
            cte[i] = (eps[i] - eps[i - 1]) / (temps[i] - temps[i - 1])
        else:
            # 중간 점: 중심 차분
            cte[i] = (eps[i + 1] - eps[i - 1]) / (temps[i + 1] - temps[i - 1])

    return temps, eps, cte


def _fmt_temp(value: float) -> str:
    """온도는 정수면 정수로, 아니면 짧은 실수로 표기한다."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _fmt(value: float, spec: str) -> str:
    try:
        return format(float(value), spec)
    except (ValueError, TypeError):
        return f"{value:.3e}"


# ── GUI ──────────────────────────────────────────


class StrainToCteTool(BaseTool):
    """Strain mp 코드를 붙여넣어 온도별 CTE 로 변환하는 도구."""

    name = "Strain → CTE 변환"
    default_geometry = "980x860"
    min_size = (820, 620)

    _FORMATS = [".3e", ".4e", ".6e", ".6g", ".9f"]

    # ── UI 구성 ──────────────────────────────────────

    def build_ui(self, parent: tk.Frame) -> None:
        self._parent = parent
        self._rows: List[Tuple[int, float, float, float]] = []  # (no, temp, strain, cte)
        self._source_material = ""   # 그래프 제목에 표시할 입력 재료명
        self._source_label = ""      # 입력 물성 라벨 (thsx 등)

        mono = ("Consolas", 10) if platform.system() == "Windows" else "TkFixedFont"

        # ── 입력 ────────────────────────────────────
        in_lf = ttk.LabelFrame(parent, text="입력  (strain mp 코드를 붙여넣으세요)")
        in_lf.pack(fill="both", expand=False, padx=6, pady=(6, 3))

        in_btns = ttk.Frame(in_lf)
        in_btns.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Button(in_btns, text="클립보드에서 붙여넣기", command=self._paste).pack(
            side="left", padx=(0, 3)
        )
        ttk.Button(in_btns, text="지우기", command=self._clear_input).pack(
            side="left", padx=(0, 3)
        )
        ttk.Button(in_btns, text="예시 넣기", command=self._insert_example).pack(side="left")

        txt_row = ttk.Frame(in_lf)
        txt_row.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._input = tk.Text(txt_row, height=7, wrap="none", undo=True, font=mono)
        self._input.pack(side="left", fill="both", expand=True)
        in_vsb = ttk.Scrollbar(txt_row, orient="vertical", command=self._input.yview)
        in_vsb.pack(side="left", fill="y")
        self._input.configure(yscrollcommand=in_vsb.set)

        # ── 옵션 ────────────────────────────────────
        opt = ttk.Frame(parent)
        opt.pack(fill="x", padx=6, pady=(0, 3))

        ttk.Button(opt, text="변환", command=self._convert).pack(side="left", padx=(0, 10))

        ttk.Label(opt, text="CTE 단위:").pack(side="left")
        self._unit_var = tk.StringVar(value="1/K")
        unit_cb = ttk.Combobox(
            opt, textvariable=self._unit_var, values=["1/K", "ppm/K"],
            width=7, state="readonly",
        )
        unit_cb.pack(side="left", padx=(4, 10))
        unit_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_output())

        ttk.Label(opt, text="숫자 형식:").pack(side="left")
        self._fmt_var = tk.StringVar(value=".3e")
        fmt_cb = ttk.Combobox(
            opt, textvariable=self._fmt_var, values=self._FORMATS, width=7
        )
        fmt_cb.pack(side="left", padx=(4, 10))
        fmt_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_output())
        fmt_cb.bind("<Return>", lambda _e: self._refresh_output())

        self._autocopy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt, text="변환 후 표 자동 복사", variable=self._autocopy_var
        ).pack(side="left", padx=(0, 10))

        self._header_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="복사 시 헤더 포함", variable=self._header_var).pack(
            side="left"
        )

        # APDL 출력 옵션
        opt2 = ttk.Frame(parent)
        opt2.pack(fill="x", padx=6, pady=(0, 3))
        ttk.Label(opt2, text="APDL 출력 —  재료명:").pack(side="left")
        self._mat_var = tk.StringVar(value="1")
        ttk.Entry(opt2, textvariable=self._mat_var, width=10).pack(side="left", padx=(4, 10))
        ttk.Label(opt2, text="물성 라벨:").pack(side="left")
        self._label_var = tk.StringVar(value="ctex")
        ttk.Combobox(
            opt2, textvariable=self._label_var,
            values=["ctex", "ctey", "ctez", "alpx", "alpy", "alpz"], width=8,
        ).pack(side="left", padx=(4, 10))
        ttk.Label(
            opt2, text="(APDL 코드의 CTE 는 단위 설정과 무관하게 항상 1/K 절대값)",
            foreground="gray",
        ).pack(side="left")

        # ── 복사 / 상태 ─────────────────────────────
        # 창이 작아져도 잘리지 않도록 아래쪽에 먼저 고정한다.
        # (상태 바를 먼저 pack 해야 맨 아래에 놓이고, 복사 버튼이 그 위에 온다)
        self._status_var = tk.StringVar(
            value="mp 코드를 붙여넣고 변환 버튼을 누르세요."
        )
        ttk.Label(parent, textvariable=self._status_var, anchor="w").pack(
            side="bottom", fill="x", padx=6, pady=(0, 4)
        )

        bottom = ttk.Frame(parent)
        bottom.pack(side="bottom", fill="x", padx=6, pady=(0, 3))
        ttk.Button(bottom, text="표 복사", command=self._copy_table).pack(
            side="left", padx=(0, 3)
        )
        ttk.Button(bottom, text="APDL 코드 복사", command=self._copy_apdl).pack(side="left")

        # ── 결과 ────────────────────────────────────
        nb = ttk.Notebook(parent)

        table_tab = ttk.Frame(nb)
        nb.add(table_tab, text="표")

        cols = ("no", "temp", "strain", "cte")
        self._tree = ttk.Treeview(table_tab, columns=cols, show="headings", selectmode="browse")
        for cid, text_, width, anchor in (
            ("no", "No.", 50, "center"),
            ("temp", "Temperature (°C)", 140, "e"),
            ("strain", "Strain", 160, "e"),
            ("cte", "CTE (1/K)", 160, "e"),
        ):
            self._tree.heading(cid, text=text_, anchor=anchor)
            self._tree.column(cid, width=width, minwidth=50, anchor=anchor)

        tv_vsb = ttk.Scrollbar(table_tab, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=tv_vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        tv_vsb.grid(row=0, column=1, sticky="ns")
        table_tab.rowconfigure(0, weight=1)
        table_tab.columnconfigure(0, weight=1)

        plot_tab = ttk.Frame(nb)
        nb.add(plot_tab, text="그래프")
        self._build_plot_tab(plot_tab)

        apdl_tab = ttk.Frame(nb)
        nb.add(apdl_tab, text="APDL 코드")
        self._apdl = tk.Text(apdl_tab, wrap="none", font=mono)
        self._apdl.grid(row=0, column=0, sticky="nsew")
        ap_vsb = ttk.Scrollbar(apdl_tab, orient="vertical", command=self._apdl.yview)
        ap_vsb.grid(row=0, column=1, sticky="ns")
        self._apdl.configure(yscrollcommand=ap_vsb.set)
        apdl_tab.rowconfigure(0, weight=1)
        apdl_tab.columnconfigure(0, weight=1)

        # 노트북은 마지막에 pack 한다. pack 은 호출 순서대로 공간을 나눠주므로,
        # 하단 복사 버튼과 상태 바가 먼저 자리를 잡은 뒤 남은 공간을 모두 차지한다.
        nb.pack(fill="both", expand=True, padx=6, pady=(0, 3))

    # ── 입력 제어 ────────────────────────────────────

    def _paste(self) -> None:
        try:
            data = self._parent.clipboard_get()
        except tk.TclError:
            self._status_var.set("클립보드가 비어 있거나 텍스트가 아닙니다.")
            return
        self._input.delete("1.0", "end")
        self._input.insert("1.0", data)
        self._status_var.set("클립보드 내용을 붙여넣었습니다. 변환 버튼을 누르세요.")

    def _clear_input(self) -> None:
        self._input.delete("1.0", "end")
        self._status_var.set("입력을 지웠습니다.")

    def _insert_example(self) -> None:
        self._input.delete("1.0", "end")
        self._input.insert("1.0", EXAMPLE_INPUT)
        self._status_var.set("예시 데이터를 넣었습니다. 변환 버튼을 누르세요.")

    # ── 변환 ─────────────────────────────────────────

    def _convert(self) -> None:
        text = self._input.get("1.0", "end")
        pairs, material, label = parse_mp_block(text)

        if len(pairs) < 2:
            self._rows = []
            self._refresh_output()
            self._status_var.set(
                "온도/strain 쌍을 2개 이상 찾지 못했습니다. 입력 형식을 확인하세요."
            )
            return

        try:
            temps, strains, cte = strain_to_cte_derivative(
                [p[0] for p in pairs], [p[1] for p in pairs]
            )
        except ValueError as e:
            self._rows = []
            self._refresh_output()
            self._status_var.set(str(e))
            return

        self._rows = [
            (i + 1, float(t), float(s), float(c))
            for i, (t, s, c) in enumerate(zip(temps, strains, cte))
        ]

        # 입력에서 읽은 재료명은 APDL 출력 기본값으로 사용한다.
        self._source_material = material
        self._source_label = label
        if material:
            self._mat_var.set(material)

        self._refresh_output()

        mean_cte = float(np.mean(cte))
        src = f"{label} " if label else ""
        self._status_var.set(
            f"{src}데이터 {len(self._rows)}점 변환 완료 | "
            f"평균 CTE {self._scaled(mean_cte):.3e} {self._unit_var.get()}"
        )

        if self._autocopy_var.get():
            self._copy_table(quiet=True)
            self._status_var.set(self._status_var.get() + " | 표를 클립보드에 복사함")

    def _scaled(self, cte: float) -> float:
        """단위 설정에 맞춘 CTE 값 (ppm/K 이면 ×10^6)."""
        return cte * 1e6 if self._unit_var.get() == "ppm/K" else cte

    # ── 출력 갱신 ────────────────────────────────────

    def _refresh_output(self) -> None:
        spec = self._fmt_var.get().strip() or ".3e"
        unit = self._unit_var.get()

        self._tree.heading("cte", text=f"CTE ({unit})", anchor="e")
        self._tree.delete(*self._tree.get_children())
        for no, temp, strain, cte in self._rows:
            self._tree.insert(
                "", "end",
                values=(no, _fmt_temp(temp), _fmt(strain, spec),
                        _fmt(self._scaled(cte), spec)),
            )

        self._apdl.delete("1.0", "end")
        self._apdl.insert("1.0", self._apdl_text())

        self._refresh_plot()

    # ── 그래프 ───────────────────────────────────────

    def _build_plot_tab(self, tab: ttk.Frame) -> None:
        """온도-CTE 그래프 탭을 구성한다.

        matplotlib 이 없으면 안내 문구만 표시하고 나머지 기능은 그대로 쓴다.
        pyplot 을 쓰지 않고 Figure 를 직접 만들어, 창을 닫으면 함께 해제된다.
        """
        self._canvas = None
        self._ax2 = None
        self._auto_layout = False

        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import (
                FigureCanvasTkAgg, NavigationToolbar2Tk,
            )
        except Exception as e:  # matplotlib 미설치 등
            ttk.Label(
                tab, anchor="center", justify="center", foreground="gray",
                text=("그래프를 표시하려면 matplotlib 이 필요합니다.\n"
                      "pip install matplotlib\n\n"
                      f"({e})"),
            ).pack(fill="both", expand=True, padx=12, pady=12)
            return

        ctrl = ttk.Frame(tab)
        ctrl.pack(fill="x", padx=4, pady=(4, 0))
        self._plot_strain_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl, text="Strain 함께 표시 (오른쪽 축)",
            variable=self._plot_strain_var, command=self._refresh_plot,
        ).pack(side="left", padx=(0, 10))
        self._plot_grid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl, text="격자", variable=self._plot_grid_var,
            command=self._refresh_plot,
        ).pack(side="left")

        self._fig = Figure(figsize=(7.0, 3.6), dpi=100)
        try:
            # 자동 레이아웃: 창 크기를 줄여도 축 라벨이 잘리지 않도록
            # 그릴 때마다 여백을 다시 계산한다 (matplotlib 3.6+).
            self._fig.set_layout_engine("constrained")
            self._auto_layout = True
        except Exception:
            # 구버전에서는 갱신할 때 tight_layout 으로 대체한다.
            self._auto_layout = False
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvasTkAgg(self._fig, master=tab)

        # 툴바를 캔버스보다 먼저 아래쪽에 고정한다. 캔버스만 남은 공간을
        # 차지하므로 창을 줄여도 툴바가 잘리지 않는다.
        toolbar_frame = ttk.Frame(tab)
        toolbar_frame.pack(side="bottom", fill="x", padx=4, pady=(0, 4))
        NavigationToolbar2Tk(self._canvas, toolbar_frame).update()

        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=(2, 0))

        self._refresh_plot()

    def _apply_layout(self) -> None:
        """자동 레이아웃을 쓸 수 없는 matplotlib 버전에서만 여백을 정리한다."""
        if not self._auto_layout:
            self._fig.tight_layout()

    def _refresh_plot(self) -> None:
        """현재 결과로 온도-CTE 그래프를 다시 그린다."""
        if self._canvas is None:
            return

        ax = self._ax
        if self._ax2 is not None:
            self._ax2.remove()
            self._ax2 = None
        ax.clear()

        unit = self._unit_var.get()
        ax.set_xlabel("Temperature (\u00b0C)")
        ax.set_ylabel(f"CTE ({unit})", color="#c0392b")
        ax.tick_params(axis="y", labelcolor="#c0392b")
        # grid(False, alpha=...) 는 경고와 함께 오히려 격자를 켜버리므로 분기한다.
        if self._plot_grid_var.get():
            ax.grid(True, alpha=0.3)
        else:
            ax.grid(False)

        if not self._rows:
            ax.text(
                0.5, 0.5, "No data - run the conversion first",
                ha="center", va="center", transform=ax.transAxes, color="gray",
            )
            self._apply_layout()
            self._canvas.draw_idle()
            return

        temps = [r[1] for r in self._rows]
        strains = [r[2] for r in self._rows]
        cte = [self._scaled(r[3]) for r in self._rows]

        handles = ax.plot(
            temps, cte, marker="o", markersize=5, linewidth=1.8,
            color="#c0392b", label=f"CTE ({unit})",
        )

        if self._plot_strain_var.get():
            self._ax2 = ax.twinx()
            handles += self._ax2.plot(
                temps, strains, marker="s", markersize=4, linewidth=1.2,
                linestyle="--", color="#2c6fbb", alpha=0.75, label="Strain",
            )
            self._ax2.set_ylabel("Strain", color="#2c6fbb")
            self._ax2.tick_params(axis="y", labelcolor="#2c6fbb")

        ax.legend(handles, [h.get_label() for h in handles], loc="best", fontsize=9)

        title = "CTE vs Temperature"
        if self._source_material:
            title += f"  ({self._source_material}"
            title += f", {self._source_label})" if self._source_label else ")"
        ax.set_title(title, fontsize=10)

        self._apply_layout()
        self._canvas.draw_idle()

    def _table_text(self) -> str:
        """표를 탭 구분(TSV) 텍스트로 만든다 — 엑셀에 바로 붙여넣기 가능."""
        spec = self._fmt_var.get().strip() or ".3e"
        lines: List[str] = []
        if self._header_var.get():
            lines.append(
                f"Temperature (C)\tStrain\tCTE ({self._unit_var.get()})"
            )
        for _no, temp, strain, cte in self._rows:
            lines.append(
                f"{_fmt_temp(temp)}\t{_fmt(strain, spec)}\t"
                f"{_fmt(self._scaled(cte), spec)}"
            )
        return "\n".join(lines)

    def _apdl_text(self) -> str:
        """CTE 를 다시 APDL mp 코드로 만든다 (CTE 는 항상 1/K 절대값)."""
        spec = self._fmt_var.get().strip() or ".3e"
        mat = self._mat_var.get().strip() or "1"
        label = self._label_var.get().strip() or "ctex"
        return "\n".join(
            f"mptemp,{no},{_fmt_temp(temp)}$mpdata,{label},{mat},{no},{_fmt(cte, spec)}"
            for no, temp, _strain, cte in self._rows
        )

    # ── 클립보드 ─────────────────────────────────────

    def _copy(self, text: str) -> bool:
        if not text:
            self._status_var.set("복사할 결과가 없습니다. 먼저 변환하세요.")
            return False
        try:
            self._parent.clipboard_clear()
            self._parent.clipboard_append(text)
            self._parent.update_idletasks()
        except tk.TclError:
            self._status_var.set("클립보드 복사에 실패했습니다.")
            return False
        return True

    def _copy_table(self, quiet: bool = False) -> None:
        if self._copy(self._table_text()) and not quiet:
            self._status_var.set(f"표 {len(self._rows)}행을 클립보드에 복사했습니다.")

    def _copy_apdl(self) -> None:
        if self._copy(self._apdl_text()):
            self._status_var.set(
                f"APDL 코드 {len(self._rows)}줄을 클립보드에 복사했습니다."
            )
