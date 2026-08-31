# -*- coding: utf-8 -*-
"""Ball Map Generator GUI (tkinter, 표준 라이브러리만 사용).

원본은 단독 실행 스크립트였으며, tool_box 런처가 넘겨주는 parent 프레임
안에 임베드할 수 있도록 ``build_gui(parent)`` 진입점을 추가했다.
"""

import os
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .core import generate_ballmap, estimate_count, write_indexed_txt

TYPES = ["in-line", "staggered-30", "staggered-45", "staggered-60"]
PAD_L, PAD_R, PAD_T, PAD_B = 54, 16, 16, 34
RASTER_MIN = 4000          # 이 개수 초과 시 래스터 이미지로 렌더링
WARN_LIMIT = 200000        # 진행 여부 확인
HARD_LIMIT = 5000000       # 생성 차단


def _nice_step(span, target=8):
    if span <= 0:
        return 1.0
    raw = span / float(target)
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        if raw <= m * mag * (1.0 + 1e-12):
            return m * mag
    return 10.0 * mag


class BallMapApp(ttk.Frame):
    def __init__(self, master):
        ttk.Frame.__init__(self, master, padding=10)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.coords = []
        self.pkg = (1.0, 1.0)
        self.dia = 0.25
        self._img = None
        self._resize_job = None

        self.var_type = tk.StringVar(value=TYPES[0])
        self.var_pitch = tk.StringVar(value="0.4")
        self.var_dia = tk.StringVar(value="0.25")
        self.var_px = tk.StringVar(value="20")
        self.var_py = tk.StringVar(value="20")
        self.var_margin = tk.StringVar(value="0.4")
        self.var_axis = tk.StringVar(value="x")
        self.var_corner = tk.BooleanVar(value=True)
        self.var_mode = tk.StringVar(value="circle")
        self.var_grid = tk.BooleanVar(value=True)
        self.var_dec = tk.StringVar(value="4")
        self.var_status = tk.StringVar(value="입력 후 [생성 / 미리보기]를 누르세요.")

        self._build_inputs()
        self._build_canvas()
        self.var_type.trace_add("write", lambda *a: self._sync_state())
        self.var_mode.trace_add("write", lambda *a: self._draw())
        self.var_grid.trace_add("write", lambda *a: self._draw())
        self._sync_state()

    # ---------------- 입력 패널 ----------------
    def _build_inputs(self):
        f = ttk.LabelFrame(self, text="입력", padding=8)
        f.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))

        r = 0
        ttk.Label(f, text="배열 타입").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.var_type, values=TYPES,
                     state="readonly", width=14).grid(row=r, column=1,
                                                      sticky="ew", pady=3)

        for label, var in (("Ball pitch", self.var_pitch),
                           ("Ball diameter", self.var_dia),
                           ("Pkg X size", self.var_px),
                           ("Pkg Y size", self.var_py),
                           ("Edge margin", self.var_margin)):
            r += 1
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(f, textvariable=var, width=16).grid(row=r, column=1,
                                                          sticky="ew", pady=3)

        r += 1
        self.lbl_axis = ttk.Label(f, text="각도 기준축")
        self.lbl_axis.grid(row=r, column=0, sticky="w", pady=3)
        fa = ttk.Frame(f)
        fa.grid(row=r, column=1, sticky="w")
        self.rb_x = ttk.Radiobutton(fa, text="X", variable=self.var_axis, value="x")
        self.rb_y = ttk.Radiobutton(fa, text="Y", variable=self.var_axis, value="y")
        self.rb_x.pack(side="left")
        self.rb_y.pack(side="left", padx=(8, 0))

        r += 1
        self.cb_corner = ttk.Checkbutton(f, text="코너에 볼 배치",
                                         variable=self.var_corner)
        self.cb_corner.grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        ttk.Separator(f, orient="horizontal").grid(row=r, column=0, columnspan=2,
                                                   sticky="ew", pady=8)

        r += 1
        ttk.Label(f, text="표시 방식").grid(row=r, column=0, sticky="w", pady=3)
        fm = ttk.Frame(f)
        fm.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(fm, text="원(실제 크기)", variable=self.var_mode,
                        value="circle").pack(anchor="w")
        ttk.Radiobutton(fm, text="점(scatter)", variable=self.var_mode,
                        value="point").pack(anchor="w")

        r += 1
        ttk.Checkbutton(f, text="그리드 표시", variable=self.var_grid
                        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        ttk.Label(f, text="소수점 자리").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.var_dec, width=16).grid(row=r, column=1,
                                                               sticky="ew", pady=3)

        r += 1
        ttk.Button(f, text="생성 / 미리보기", command=self.on_generate
                   ).grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 3))
        r += 1
        self.btn_save = ttk.Button(f, text="txt로 저장...", command=self.on_save,
                                   state="disabled")
        self.btn_save.grid(row=r, column=0, columnspan=2, sticky="ew", pady=3)

    def _build_canvas(self):
        self.canvas = tk.Canvas(self, bg="white", width=560, height=560,
                                highlightthickness=1, highlightbackground="#999")
        self.canvas.grid(row=0, column=1, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_resize)
        ttk.Label(self, textvariable=self.var_status, anchor="w"
                  ).grid(row=1, column=1, sticky="ew", pady=(6, 0))

    def _sync_state(self):
        state = "disabled" if self.var_type.get() == "in-line" else "normal"
        for w in (self.lbl_axis, self.rb_x, self.rb_y, self.cb_corner):
            w.configure(state=state)

    def _read_floats(self):
        try:
            p = float(self.var_pitch.get())
            d = float(self.var_dia.get())
            px = float(self.var_px.get())
            py = float(self.var_py.get())
            mg = float(self.var_margin.get())
        except ValueError:
            raise ValueError("pitch / diameter / 사이즈 / margin 은 숫자로 입력하세요.")
        if p <= 0 or d <= 0 or px <= 0 or py <= 0:
            raise ValueError("pitch, diameter, 패키지 사이즈는 0보다 커야 합니다.")
        if mg < 0:
            raise ValueError("margin 은 0 이상이어야 합니다.")
        return p, d, px, py, mg

    # ---------------- 동작 ----------------
    def on_generate(self):
        try:
            pitch, dia, px, py, mg = self._read_floats()
            n_est = estimate_count(self.var_type.get(), pitch, px, py, mg,
                                   self.var_axis.get(), self.var_corner.get())
        except Exception as e:
            messagebox.showerror("오류", str(e))
            return

        if n_est > HARD_LIMIT:
            messagebox.showerror(
                "입력 확인",
                "예상 볼 개수가 {:,}개입니다.\n\n"
                "pitch 와 패키지 사이즈의 단위가 서로 다른지 확인하세요.\n"
                "(예: pkg 를 um 로 넣었다면 pitch 도 um 로)".format(n_est))
            return
        if n_est > WARN_LIMIT:
            if not messagebox.askyesno(
                    "확인", "예상 볼 개수 {:,}개입니다. 진행할까요?".format(n_est)):
                return

        try:
            self.coords = generate_ballmap(self.var_type.get(), pitch, px, py,
                                           mg, self.var_axis.get(),
                                           self.var_corner.get())
        except Exception as e:
            messagebox.showerror("오류", str(e))
            return

        self.pkg = (px, py)
        self.dia = dia
        self.btn_save.configure(state=("normal" if self.coords else "disabled"))
        if not self.coords:
            self.var_status.set("조건상 생성된 볼이 없습니다. margin / pitch 를 확인하세요.")
        else:
            xs = sorted(set(round(c[0], 6) for c in self.coords))
            ys = sorted(set(round(c[1], 6) for c in self.coords))
            warn = "  [경고: diameter >= pitch, 볼 간섭]" if dia >= pitch else ""
            self.var_status.set(
                "%s | %s balls | 열 %d / 행 %d | X %.3f ~ %.3f, Y %.3f ~ %.3f%s"
                % (self.var_type.get(), "{:,}".format(len(self.coords)),
                   len(xs), len(ys), xs[0], xs[-1], ys[0], ys[-1], warn))
        self._draw()

    def on_save(self):
        if not self.coords:
            return
        try:
            dec = int(self.var_dec.get())
        except ValueError:
            messagebox.showerror("오류", "소수점 자리는 정수로 입력하세요.")
            return
        default = "ballmap_%s_p%s.txt" % (self.var_type.get().replace("-", ""),
                                          self.var_pitch.get())
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=default,
            filetypes=[("Text", "*.txt"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            write_indexed_txt(self.coords, path, decimals=dec)
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))
            return
        self.var_status.set("저장 완료: %s (%s balls)"
                            % (os.path.basename(path),
                               "{:,}".format(len(self.coords))))

    # ---------------- 미리보기 ----------------
    def _on_resize(self, event):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._draw)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        self._img = None
        if not self.coords:
            return

        W = max(c.winfo_width(), 200)
        H = max(c.winfo_height(), 200)
        px, py = self.pkg
        s = min((W - PAD_L - PAD_R) / px, (H - PAD_T - PAD_B) / py)
        cx = PAD_L + (W - PAD_L - PAD_R) / 2.0
        cy = PAD_T + (H - PAD_T - PAD_B) / 2.0
        x0, x1 = cx - px * s / 2, cx + px * s / 2
        y0, y1 = cy - py * s / 2, cy + py * s / 2

        if self.var_mode.get() == "circle":
            r, fill = max(0.7, self.dia / 2.0 * s), "#c0392b"
        else:
            r, fill = 1.8, "#1f4e9c"

        if len(self.coords) > RASTER_MIN:
            # 볼과 그리드 선을 이미지 1장으로 구워 캔버스 아이템 1개만 사용
            self._img = self._raster(W, H, cx, cy, s, x0, x1, y0, y1, r, fill)
            c.create_image(0, 0, image=self._img, anchor="nw")
            self._draw_grid(cx, cy, x0, x1, y0, y1, s, px, py,
                            lines=False, labels=True)
        else:
            self._draw_grid(cx, cy, x0, x1, y0, y1, s, px, py,
                            lines=True, labels=True)
            for x, y in self.coords:
                X = cx + x * s
                Y = cy - y * s
                c.create_oval(X - r, Y - r, X + r, Y + r, fill=fill, outline="")

        c.create_line(cx, y0, cx, y1, fill="#bbb")
        c.create_line(x0, cy, x1, cy, fill="#bbb")
        c.create_rectangle(x0, y0, x1, y1, outline="#666")

    def _grid_vals(self, span):
        step = _nice_step(span)
        dec = max(0, int(-math.floor(math.log10(step))))
        n = int(math.floor((span / 2.0) / step + 1e-9))
        return [i * step for i in range(-n, n + 1)], dec

    def _draw_grid(self, cx, cy, x0, x1, y0, y1, s, px, py,
                   lines=True, labels=True):
        if not self.var_grid.get():
            return
        c = self.canvas
        vals, dec = self._grid_vals(px)
        for val in vals:
            X = cx + val * s
            if lines:
                c.create_line(X, y0, X, y1, fill="#e8e8e8")
            if labels:
                c.create_text(X, y1 + 6, text=("%.*f" % (dec, val)), anchor="n",
                              font=("TkDefaultFont", 8), fill="#555")
        vals, dec = self._grid_vals(py)
        for val in vals:
            Y = cy - val * s
            if lines:
                c.create_line(x0, Y, x1, Y, fill="#e8e8e8")
            if labels:
                c.create_text(x0 - 6, Y, text=("%.*f" % (dec, val)), anchor="e",
                              font=("TkDefaultFont", 8), fill="#555")

    def _raster(self, W, H, cx, cy, s, x0, x1, y0, y1, r, fill):
        """볼이 많을 때: 픽셀 버퍼에 직접 찍어 PhotoImage 1장으로 반환.
        비용이 볼 개수가 아니라 캔버스 픽셀 수에 비례한다."""
        BG, GRID = "#ffffff", "#e8e8e8"
        buf = [[BG] * W for _ in range(H)]
        px, py = self.pkg
        ix0, ix1 = max(0, int(x0)), min(W, int(x1) + 1)
        iy0, iy1 = max(0, int(y0)), min(H, int(y1) + 1)

        if self.var_grid.get():
            vals, _ = self._grid_vals(px)
            for val in vals:
                X = int(cx + val * s)
                if 0 <= X < W:
                    for Y in range(iy0, iy1):
                        buf[Y][X] = GRID
            vals, _ = self._grid_vals(py)
            for val in vals:
                Y = int(cy - val * s)
                if 0 <= Y < H:
                    row = buf[Y]
                    for X in range(ix0, ix1):
                        row[X] = GRID

        rr = min(int(r), 3)
        if rr <= 0:
            for x, y in self.coords:
                X = int(cx + x * s)
                Y = int(cy - y * s)
                if 0 <= X < W and 0 <= Y < H:
                    buf[Y][X] = fill
        else:
            offs = [(dx, dy) for dy in range(-rr, rr + 1)
                    for dx in range(-rr, rr + 1) if dx * dx + dy * dy <= rr * rr]
            for x, y in self.coords:
                X = int(cx + x * s)
                Y = int(cy - y * s)
                for dx, dy in offs:
                    XX, YY = X + dx, Y + dy
                    if 0 <= XX < W and 0 <= YY < H:
                        buf[YY][XX] = fill

        img = tk.PhotoImage(master=self.canvas, width=W, height=H)
        img.put(" ".join("{" + " ".join(row) + "}" for row in buf))
        return img


def build_gui(parent):
    """tool_box 런처가 넘겨준 parent 프레임 안에 GUI 를 구성한다."""
    return BallMapApp(parent)


def main():
    """단독 실행용 (python -m tools.ball_map.gui)."""
    root = tk.Tk()
    root.title("Ball Map Generator")
    root.geometry("900x660")
    BallMapApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
