"""Ball Map Generator 도구 패키지 (tool_box 연동).

- ``core``: 볼 좌표 생성 로직 (표준 라이브러리만 사용, CLI 포함)
- ``gui`` : tkinter GUI. BaseTool 인터페이스에 맞춰 parent 프레임에 임베드한다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool


class BallMapTool(BaseTool):
    """패키지 크기와 pitch 로부터 BGA 볼 좌표를 생성하는 도구."""

    name = "Ball Map 생성"
    default_geometry = "980x700"
    min_size = (860, 620)

    def build_ui(self, parent: tk.Frame) -> None:
        try:
            from .gui import build_gui
            build_gui(parent)
        except Exception as e:
            msg = (
                "Ball Map 도구를 로드하지 못했습니다.\n\n"
                f"{type(e).__name__}: {e}"
            )
            frame = ttk.Frame(parent, padding=16)
            frame.pack(fill="both", expand=True)
            ttk.Label(
                frame, text=msg, justify="left", foreground="#884400",
                wraplength=560,
            ).pack(anchor="w")
