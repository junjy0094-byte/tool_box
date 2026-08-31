# -*- coding: utf-8 -*-
"""Ball Map 변환기 (0,1) GUI.

좌표 목록을 붙여넣으면 0/1 격자로 변환해 그림과 텍스트로 바로 보여주고,
txt 저장 또는 클립보드 복사를 지원한다.
"""

import platform
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .binary_map import (parse_input_string_to_array, make_grid_binary_array,
                         format_grid_with_index, save_grid_with_index_to_file)

TEXT_PREVIEW_ROWS = 300     # 텍스트 탭에 이만큼만 미리보기 (저장/복사는 전체)
CELL_GRIDLINE_MAX = 60      # 축당 이 개수 이하일 때만 칸 경계선을 그린다

EXAMPLE_INPUT = """-0.4\t-0.4
0.0\t-0.4
0.4\t-0.4
-0.4\t0.0
0.4\t0.0
-0.4\t0.4
0.0\t0.4
0.4\t0.4"""


class BinaryMapApp(ttk.Frame):
    """좌표 -> 0/1 격자 변환 GUI."""

    def __init__(self, master):
        ttk.Frame.__init__(self, master, padding=8)
        self.pack(fill="both", expand=True)

        self.grid_arr = None
        self.info = None
        self._canvas = None
        self._auto_layout = False

        mono = ("Consolas", 10) if platform.system() == "Windows" else "TkFixedFont"
        self._mono = mono

        self._build_bottom()      # 하단 바를 먼저 고정해 창이 작아져도 안 잘리게
        self._build_input(mono)
        self._build_output(mono)

    # ── 하단 (상태 / 저장) ───────────────────────────
    def _build_bottom(self):
        self.var_status = tk.StringVar(
            value="좌표를 붙여넣고 [변환] 을 누르세요.  (형식: x <탭> y, 한 줄에 한 점)")
        ttk.Label(self, textvariable=self.var_status, anchor="w").pack(
            side="bottom", fill="x", pady=(4, 0))

        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", pady=(4, 0))
        self.btn_save = ttk.Button(bar, text="txt로 저장...", command=self.on_save,
                                   state="disabled")
        self.btn_save.pack(side="left", padx=(0, 4))
        self.btn_copy = ttk.Button(bar, text="격자 텍스트 복사", command=self.on_copy,
                                   state="disabled")
        self.btn_copy.pack(side="left")

    # ── 입력 ────────────────────────────────────────
    def _build_input(self, mono):
        lf = ttk.LabelFrame(self, text="입력 좌표  (x <탭> y — 엑셀에서 그대로 붙여넣기)")
        lf.pack(fill="x", pady=(0, 4))

        btns = ttk.Frame(lf)
        btns.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Button(btns, text="클립보드에서 붙여넣기", command=self.on_paste).pack(
            side="left", padx=(0, 3))
        ttk.Button(btns, text="파일 열기...", command=self.on_open).pack(
            side="left", padx=(0, 3))
        ttk.Button(btns, text="지우기", command=self.on_clear).pack(
            side="left", padx=(0, 3))
        ttk.Button(btns, text="예시 넣기", command=self.on_example).pack(side="left")
        ttk.Button(btns, text="변환", command=self.on_convert).pack(
            side="right", padx=(6, 0))

        row = ttk.Frame(lf)
        row.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.txt_in = tk.Text(row, height=8, wrap="none", undo=True, font=mono)
        self.txt_in.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(row, orient="vertical", command=self.txt_in.yview)
        vsb.pack(side="left", fill="y")
        self.txt_in.configure(yscrollcommand=vsb.set)

    # ── 결과 ────────────────────────────────────────
    def _build_output(self, mono):
        nb = ttk.Notebook(self)

        map_tab = ttk.Frame(nb)
        nb.add(map_tab, text="격자 그림")
        self._build_map_tab(map_tab)

        txt_tab = ttk.Frame(nb)
        nb.add(txt_tab, text="격자 텍스트")
        self.txt_out = tk.Text(txt_tab, wrap="none", font=mono)
        self.txt_out.grid(row=0, column=0, sticky="nsew")
        ovsb = ttk.Scrollbar(txt_tab, orient="vertical", command=self.txt_out.yview)
        ovsb.grid(row=0, column=1, sticky="ns")
        ohsb = ttk.Scrollbar(txt_tab, orient="horizontal", command=self.txt_out.xview)
        ohsb.grid(row=1, column=0, sticky="ew")
        self.txt_out.configure(yscrollcommand=ovsb.set, xscrollcommand=ohsb.set)
        txt_tab.rowconfigure(0, weight=1)
        txt_tab.columnconfigure(0, weight=1)

        nb.pack(fill="both", expand=True)

    def _build_map_tab(self, tab):
        """0/1 격자를 그림으로 보여주는 탭. matplotlib 이 없으면 안내만 표시한다."""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import (
                FigureCanvasTkAgg, NavigationToolbar2Tk,
            )
        except Exception as e:
            ttk.Label(
                tab, anchor="center", justify="center", foreground="gray",
                text=("격자 그림을 보려면 matplotlib 이 필요합니다.\n"
                      "pip install matplotlib\n\n"
                      "( %s )\n\n"
                      "[격자 텍스트] 탭과 저장 기능은 그대로 쓸 수 있습니다." % e),
            ).pack(fill="both", expand=True, padx=12, pady=12)
            return

        self._fig = Figure(figsize=(6.4, 4.6), dpi=100)
        try:
            self._fig.set_layout_engine("constrained")
            self._auto_layout = True
        except Exception:
            self._auto_layout = False
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvasTkAgg(self._fig, master=tab)

        tb = ttk.Frame(tab)
        tb.pack(side="bottom", fill="x", padx=4, pady=(0, 4))
        NavigationToolbar2Tk(self._canvas, tb).update()

        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=(4, 0))
        self._draw_map()

    # ── 입력 동작 ────────────────────────────────────
    def on_paste(self):
        try:
            data = self.clipboard_get()
        except tk.TclError:
            self.var_status.set("클립보드가 비어 있거나 텍스트가 아닙니다.")
            return
        self.txt_in.delete("1.0", "end")
        self.txt_in.insert("1.0", data)
        self.var_status.set("클립보드 내용을 붙여넣었습니다. [변환] 을 누르세요.")

    def on_open(self):
        path = filedialog.askopenfilename(
            filetypes=[("Text / CSV", "*.txt *.csv"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                data = f.read()
        except OSError as e:
            messagebox.showerror("열기 실패", str(e))
            return
        self.txt_in.delete("1.0", "end")
        self.txt_in.insert("1.0", data)
        self.var_status.set("파일을 읽었습니다. [변환] 을 누르세요.")

    def on_clear(self):
        self.txt_in.delete("1.0", "end")
        self.var_status.set("입력을 지웠습니다.")

    def on_example(self):
        self.txt_in.delete("1.0", "end")
        self.txt_in.insert("1.0", EXAMPLE_INPUT)
        self.var_status.set("예시 데이터를 넣었습니다. [변환] 을 누르세요.")

    # ── 변환 ─────────────────────────────────────────
    def on_convert(self):
        raw = self.txt_in.get("1.0", "end")
        try:
            points = parse_input_string_to_array(raw)
            self.grid_arr, self.info = make_grid_binary_array(points)
        except ValueError as e:
            self.grid_arr = self.info = None
            self._refresh_output()
            self.var_status.set(str(e))
            return

        self._refresh_output()

        i = self.info
        msg = ("%d x %d 격자 (행 x 열) | 좌표 %s개 -> 1 이 %s칸 | "
               "pitch X %.6g / Y %.6g | X %.4g ~ %.4g, Y %.4g ~ %.4g"
               % (i["rows"], i["cols"], "{:,}".format(i["points"]),
                  "{:,}".format(i["ones"]), i["x_pitch"], i["y_pitch"],
                  i["x_range"][0], i["x_range"][1],
                  i["y_range"][0], i["y_range"][1]))
        if i["duplicates"]:
            msg += "  [같은 칸에 겹친 좌표 %d개]" % i["duplicates"]
        if i["off_grid"]:
            msg += "  [격자에서 벗어나 가장 가까운 칸에 넣은 좌표 %d개]" % i["off_grid"]
        self.var_status.set(msg)

    def _refresh_output(self):
        has = self.grid_arr is not None
        state = "normal" if has else "disabled"
        self.btn_save.configure(state=state)
        self.btn_copy.configure(state=state)

        self.txt_out.delete("1.0", "end")
        if has:
            rows = self.grid_arr.shape[0]
            if rows > TEXT_PREVIEW_ROWS:
                head = format_grid_with_index(self.grid_arr[:TEXT_PREVIEW_ROWS])
                self.txt_out.insert(
                    "1.0", head + "\n\n... 이하 %d행 생략 (저장/복사는 전체 %d행) ...\n"
                    % (rows - TEXT_PREVIEW_ROWS, rows))
            else:
                self.txt_out.insert("1.0", format_grid_with_index(self.grid_arr))
        self._draw_map()

    # ── 격자 그림 ────────────────────────────────────
    def _draw_map(self):
        if self._canvas is None:
            return
        ax = self._ax
        ax.clear()

        if self.grid_arr is None:
            ax.text(0.5, 0.5, "No data - press Convert first",
                    ha="center", va="center", transform=ax.transAxes, color="gray")
            ax.set_xticks([]); ax.set_yticks([])
            self._apply_layout()
            self._canvas.draw_idle()
            return

        from matplotlib.colors import ListedColormap
        g = self.grid_arr
        rows, cols = g.shape

        # origin='lower' : 행 0 = y 최소 = 아래쪽. 저장 파일의 행 순서와 같다.
        ax.imshow(g, origin="lower", interpolation="nearest", aspect="equal",
                  cmap=ListedColormap(["#f2f2f2", "#c0392b"]), vmin=0, vmax=1,
                  extent=(-0.5, cols - 0.5, -0.5, rows - 0.5))

        if max(rows, cols) <= CELL_GRIDLINE_MAX:
            ax.set_xticks([x - 0.5 for x in range(cols + 1)], minor=True)
            ax.set_yticks([y - 0.5 for y in range(rows + 1)], minor=True)
            ax.grid(which="minor", color="#bbbbbb", linewidth=0.5)
        ax.tick_params(which="minor", length=0)

        # 행/열 인덱스는 정수이므로 눈금도 정수로만 찍는다.
        from matplotlib.ticker import MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel("column index")
        ax.set_ylabel("row index")
        ax.set_title("%d x %d,  1 = %d cells" % (rows, cols, int(g.sum())),
                     fontsize=10)

        self._apply_layout()
        self._canvas.draw_idle()

    def _apply_layout(self):
        if not self._auto_layout:
            self._fig.tight_layout()

    # ── 출력 동작 ────────────────────────────────────
    def on_save(self):
        if self.grid_arr is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="ballmap_binary.txt",
            filetypes=[("Text", "*.txt"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            save_grid_with_index_to_file(self.grid_arr, path)
        except OSError as e:
            messagebox.showerror("저장 실패", str(e))
            return
        import os
        self.var_status.set("저장 완료: %s (%d x %d)"
                            % (os.path.basename(path), *self.grid_arr.shape))

    def on_copy(self):
        if self.grid_arr is None:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(format_grid_with_index(self.grid_arr))
            self.update_idletasks()
        except tk.TclError:
            self.var_status.set("클립보드 복사에 실패했습니다.")
            return
        self.var_status.set("격자 텍스트 %d행을 클립보드에 복사했습니다."
                            % self.grid_arr.shape[0])


def build_gui(parent):
    """tool_box 런처가 넘겨준 parent 프레임 안에 GUI 를 구성한다."""
    return BinaryMapApp(parent)


def main():
    """단독 실행용 (python -m tools.ball_map.binary_gui)."""
    root = tk.Tk()
    root.title("Ball Map 변환기 (0,1)")
    root.geometry("980x780")
    BinaryMapApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
