#!/usr/bin/env python3
"""Tool Box – 기능별 도구를 탭으로 모아 관리하는 GUI.

새 도구를 추가하려면:
  1. tools/ 아래에 BaseTool을 상속한 클래스를 만든다.
  2. 아래 TOOLS 리스트에 해당 클래스를 추가한다.
"""

import ctypes
import platform
import sys
import tkinter as tk
from tkinter import ttk


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

TOOLS = [
    ScreenshotTool,
    VariableCompareTool,
    # 새 도구 클래스를 여기에 추가하세요.
]
# ─────────────────────────────────────────────────


def main() -> None:
    root = tk.Tk()
    root.title("Tool Box")
    root.geometry("800x600")
    root.minsize(600, 400)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    for tool_cls in TOOLS:
        tool = tool_cls()
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tool.name)
        tool.build_ui(frame)

    root.mainloop()


if __name__ == "__main__":
    main()
