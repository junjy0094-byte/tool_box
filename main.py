#!/usr/bin/env python3
"""Tool Box – 도구를 런처에서 골라 개별 창으로 여는 GUI.

메인 창(런처)에는 도구 이름만 나열된다. 도구를 클릭하면 해당 도구의 GUI가
별도의 창으로 열린다. 쓰지 않는 도구는 메모리에 올라가지 않으며, 창을 닫으면
위젯과 인스턴스가 모두 해제된다.

새 도구 추가:
  1. tools/ 아래에 BaseTool 을 상속한 클래스를 만든다.
  2. 아래 TOOLS 리스트에 클래스를 추가한다.
"""

import ctypes
import platform
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Type

from tools.base_tool import BaseTool


def _enable_dpi_awareness() -> None:
    """DPI 인식을 프로그램 시작 시 활성화하여 해상도 불일치를 방지합니다."""
    if platform.system() == "Windows":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


_enable_dpi_awareness()

# ── 등록할 도구 목록 ─────────────────────────────
from tools.screenshot_tool import ScreenshotTool
from tools.variable_compare_tool import VariableCompareTool
from tools.file_compare_tool import FileCompareTool
from tools.trace_mapping import TraceMappingTool
from tools.strain_to_cte_tool import StrainToCteTool
from tools.ball_map import BallMapTool, BallMapBinaryTool
from tools.db_to_inp import DbToInpTool
from tools.zone_draw import ZoneDrawTool
from tools.zone_paint import ZonePaintTool

TOOLS: list[Type[BaseTool]] = [
    ScreenshotTool,
    VariableCompareTool,
    FileCompareTool,
    TraceMappingTool,
    StrainToCteTool,
    BallMapTool,
    BallMapBinaryTool,
    DbToInpTool,
    ZoneDrawTool,
    ZonePaintTool,
    # 새 도구 클래스를 여기에 추가하세요.
]
# ─────────────────────────────────────────────────


def _make_root() -> tk.Tk:
    """tkinterdnd2 가 있으면 TkinterDnD.Tk() 를 루트로 사용한다 (DnD 활성화)."""
    try:
        from tkinterdnd2 import TkinterDnD  # type: ignore
        return TkinterDnD.Tk()
    except Exception:
        return tk.Tk()


class ToolLauncher:
    """도구 이름을 버튼으로 나열하고, 클릭 시 개별 Toplevel 창으로 여는 런처."""

    def __init__(self, root: tk.Tk, tools: list[Type[BaseTool]]) -> None:
        self.root = root
        self.tools = tools
        self._open_windows: Dict[Type[BaseTool], tk.Toplevel] = {}

        root.title("Tool Box")
        root.geometry("380x700")
        root.minsize(300, 360)

        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        header.pack(fill="x")
        ttk.Label(header, text="Tool Box", font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="도구를 클릭하면 새 창으로 열립니다.",
            foreground="gray",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=12)

        # 스크롤 가능한 버튼 컨테이너 (도구가 많아져도 대응)
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=12, pady=(8, 8))

        canvas = tk.Canvas(body, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfigure(inner_id, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # 마우스 휠 스크롤: 런처 위에 포인터가 있을 때만 바인딩해
        # 도구 창의 휠 이벤트를 가로채지 않는다.
        def _on_mousewheel(event: tk.Event) -> None:
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_wheel(_e: tk.Event) -> None:
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_wheel(_e: tk.Event) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        for tool_cls in self.tools:
            display_name = getattr(tool_cls, "name", "") or tool_cls.__name__
            btn = ttk.Button(
                inner, text=display_name,
                command=lambda c=tool_cls: self._open_tool(c),
            )
            btn.pack(fill="x", pady=3, ipady=6)

        # 상태 표시줄
        self._status_var = tk.StringVar(value=f"등록된 도구 {len(self.tools)}개")
        ttk.Label(
            self.root, textvariable=self._status_var,
            anchor="w", foreground="gray",
        ).pack(fill="x", padx=12, pady=(0, 8))

    # ── 도구 창 제어 ──────────────────────────────────

    def _open_tool(self, tool_cls: Type[BaseTool]) -> None:
        # 이미 열린 창이 있다면 포커스만 이동
        existing = self._open_windows.get(tool_cls)
        if existing is not None and existing.winfo_exists():
            try:
                existing.deiconify()
                existing.lift()
                existing.focus_force()
            except tk.TclError:
                pass
            return

        try:
            instance = tool_cls()
        except Exception as e:
            messagebox.showerror("도구 실행 실패", f"{tool_cls.__name__} 초기화 중 오류:\n{e}")
            return

        win = tk.Toplevel(self.root)
        win.title(getattr(instance, "name", tool_cls.__name__))
        win.geometry(getattr(instance, "default_geometry", "900x650"))
        min_w, min_h = getattr(instance, "min_size", (480, 360))
        win.minsize(min_w, min_h)

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True)

        try:
            instance.build_ui(frame)
        except Exception as e:
            win.destroy()
            messagebox.showerror("도구 실행 실패", f"{tool_cls.__name__} UI 구성 중 오류:\n{e}")
            return

        self._open_windows[tool_cls] = win
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_tool(tool_cls))
        self._update_status()

    def _close_tool(self, tool_cls: Type[BaseTool]) -> None:
        win = self._open_windows.pop(tool_cls, None)
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
        self._update_status()

    def _update_status(self) -> None:
        open_count = len(self._open_windows)
        msg = f"등록된 도구 {len(self.tools)}개"
        if open_count:
            msg += f"  |  열린 도구 {open_count}개"
        self._status_var.set(msg)


def main() -> None:
    root = _make_root()
    ToolLauncher(root, TOOLS)
    root.mainloop()


if __name__ == "__main__":
    main()
