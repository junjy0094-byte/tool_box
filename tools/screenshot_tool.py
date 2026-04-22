import io
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image
import mss

from config import get_tool_config, set_tool_config
from tools.base_tool import BaseTool

TOOL_NAME = "screenshot"


def _get_full_screen_bbox() -> tuple[int, int, int, int]:
    """mss를 통해 전체 가상 화면의 (left, top, width, height)를 반환합니다."""
    with mss.mss() as sct:
        m = sct.monitors[0]  # 전체 가상 화면 (모든 모니터 합산)
        return m["left"], m["top"], m["width"], m["height"]


class RegionSelector(tk.Toplevel):
    """전체 화면 오버레이 위에서 드래그하여 영역을 선택합니다."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.start_x = self.start_y = 0
        self.rect_id = None

        # mss에서 실제 물리 해상도를 가져와 오버레이 크기 설정
        scr_left, scr_top, scr_w, scr_h = _get_full_screen_bbox()
        self.scr_offset_x = scr_left
        self.scr_offset_y = scr_top

        self.overrideredirect(True)
        self.geometry(f"{scr_w}x{scr_h}+{scr_left}+{scr_top}")
        self.attributes("-alpha", 0.3)
        self.configure(bg="black")
        self.lift()
        self.attributes("-topmost", True)

        self.canvas = tk.Canvas(
            self, cursor="cross", bg="black", highlightthickness=0,
            width=scr_w, height=scr_h,
        )
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2,
        )

    def _on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        x1 = min(self.start_x, event.x) + self.scr_offset_x
        y1 = min(self.start_y, event.y) + self.scr_offset_y
        x2 = max(self.start_x, event.x) + self.scr_offset_x
        y2 = max(self.start_y, event.y) + self.scr_offset_y
        self.destroy()
        if x2 - x1 > 5 and y2 - y1 > 5:
            self.callback((x1, y1, x2, y2))


def _capture_region(bbox: tuple[int, int, int, int]) -> Image.Image:
    """mss를 사용하여 화면 영역을 캡처합니다."""
    x1, y1, x2, y2 = bbox
    with mss.mss() as sct:
        monitor = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _copy_image_to_clipboard(img: Image.Image, scale: float) -> None:
    """이미지를 클립보드에 복사합니다.

    픽셀은 원본 그대로 유지하고, DPI를 96/scale로 설정하여
    붙여넣기 시 표시 크기만 줄입니다 (화질 손실 없음).
    """
    target_dpi = int(96 / scale)

    system = platform.system()
    if system == "Windows":
        import win32clipboard
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="BMP", dpi=(target_dpi, target_dpi))
        dib_data = buf.getvalue()[14:]  # BMP 파일 헤더 14바이트 제거 → DIB
        buf.close()
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
        win32clipboard.CloseClipboard()
    elif system == "Linux":
        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(target_dpi, target_dpi))
        proc = subprocess.Popen(
            ["xclip", "-selection", "clipboard", "-t", "image/png"],
            stdin=subprocess.PIPE,
        )
        proc.communicate(buf.getvalue())
    elif system == "Darwin":
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp, format="PNG", dpi=(target_dpi, target_dpi))
        tmp.close()
        subprocess.run([
            "osascript", "-e",
            f'set the clipboard to (read (POSIX file "{tmp.name}") as «class PNGf»)',
        ])
        os.unlink(tmp.name)


class ScreenshotTool(BaseTool):
    name = "스크린샷"
    default_geometry = "520x620"

    def __init__(self):
        cfg = get_tool_config(TOOL_NAME)
        self.bbox: tuple[int, int, int, int] | None = cfg.get("bbox")
        self.scale: float = cfg.get("scale", 1.0)

    def _save_config(self) -> None:
        set_tool_config(TOOL_NAME, {
            "bbox": self.bbox,
            "scale": self.scale,
        })

    def build_ui(self, parent: tk.Frame) -> None:
        self.parent = parent

        # ── 좌표 표시 ──
        coord_frame = ttk.LabelFrame(parent, text="저장된 좌표")
        coord_frame.pack(fill="x", padx=10, pady=(10, 5))

        self.coord_label = ttk.Label(coord_frame, text=self._coord_text())
        self.coord_label.pack(padx=10, pady=5)

        # ── 버튼 ──
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(
            btn_frame, text="새 영역 스크린샷", command=self._new_capture,
        ).pack(side="left", expand=True, fill="x", padx=(0, 5))

        ttk.Button(
            btn_frame, text="기존 영역 스크린샷", command=self._repeat_capture,
        ).pack(side="left", expand=True, fill="x", padx=(5, 0))

        # ── 스케일 설정 ──
        scale_frame = ttk.LabelFrame(parent, text="크기 배율 (0.1 ~ 1.0)")
        scale_frame.pack(fill="x", padx=10, pady=(5, 10))

        inner = ttk.Frame(scale_frame)
        inner.pack(padx=10, pady=5, fill="x")

        self.scale_var = tk.DoubleVar(value=self.scale)
        self.scale_slider = ttk.Scale(
            inner, from_=0.1, to=1.0, variable=self.scale_var,
            orient="horizontal", command=self._on_scale_slider_change,
        )
        self.scale_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.scale_entry = ttk.Entry(inner, width=6, justify="center")
        self.scale_entry.insert(0, f"{self.scale:.2f}")
        self.scale_entry.pack(side="left")
        self.scale_entry.bind("<Return>", self._on_scale_entry_change)
        self.scale_entry.bind("<FocusOut>", self._on_scale_entry_change)

        # ── 상태 표시줄 ──
        self.status_label = ttk.Label(parent, text="", foreground="gray")
        self.status_label.pack(padx=10, pady=(0, 5))

        # ── 이미지 미리보기 ──
        preview_lf = ttk.LabelFrame(parent, text="미리보기")
        preview_lf.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._preview_label = ttk.Label(preview_lf, anchor="center")
        self._preview_label.pack(fill="both", expand=True, padx=4, pady=4)
        self._preview_photo = None  # PhotoImage 참조 유지용

    def _coord_text(self) -> str:
        if self.bbox:
            x1, y1, x2, y2 = self.bbox
            return f"({x1}, {y1}) → ({x2}, {y2})  |  {x2 - x1}×{y2 - y1}px"
        return "저장된 좌표 없음"

    def _apply_scale(self, val: float) -> None:
        val = max(0.1, min(1.0, round(val, 2)))
        self.scale = val
        self.scale_var.set(val)
        self.scale_entry.delete(0, tk.END)
        self.scale_entry.insert(0, f"{val:.2f}")
        self._save_config()

    def _on_scale_slider_change(self, _=None) -> None:
        self._apply_scale(self.scale_var.get())

    def _on_scale_entry_change(self, _=None) -> None:
        try:
            val = float(self.scale_entry.get())
        except ValueError:
            return
        self._apply_scale(val)

    def _new_capture(self) -> None:
        # 메인 윈도우 숨기기
        top = self.parent.winfo_toplevel()
        top.withdraw()
        top.update()

        def on_region_selected(bbox):
            top.deiconify()
            self.bbox = bbox
            self._save_config()
            self.coord_label.config(text=self._coord_text())
            self._do_capture()

        def on_selector_destroyed():
            # 선택 안 하고 ESC로 닫았을 때
            if not top.winfo_viewable():
                top.deiconify()

        selector = RegionSelector(on_region_selected)
        selector.bind("<Destroy>", lambda e: on_selector_destroyed())

    def _repeat_capture(self) -> None:
        if not self.bbox:
            messagebox.showwarning("경고", "저장된 좌표가 없습니다.\n먼저 '새 영역 스크린샷'을 사용하세요.")
            return
        self._do_capture()

    def _do_capture(self) -> None:
        img = _capture_region(self.bbox)
        _copy_image_to_clipboard(img, self.scale)
        w, h = img.size
        display_pct = int(self.scale * 100)
        self.status_label.config(
            text=f"✓ 클립보드 복사 ({w}×{h}px, 표시 {display_pct}%)"
        )
        self._show_preview(img)

    def _show_preview(self, img: Image.Image) -> None:
        """캡처된 이미지를 미리보기 영역에 축소하여 표시한다."""
        self._preview_label.update_idletasks()
        max_w = max(self._preview_label.winfo_width(), 200)
        max_h = max(self._preview_label.winfo_height(), 150)

        img_w, img_h = img.size
        ratio = min(max_w / img_w, max_h / img_h, 1.0)
        new_w = max(1, int(img_w * ratio))
        new_h = max(1, int(img_h * ratio))
        thumb = img.resize((new_w, new_h), Image.LANCZOS)

        from PIL import ImageTk
        self._preview_photo = ImageTk.PhotoImage(thumb)
        self._preview_label.config(
            image=self._preview_photo,
            text=f"  {img_w}×{img_h}px → 표시 {int(self.scale*100)}%  ",
            compound="top",
        )
