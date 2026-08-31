"""Ball Map Generator 도구 패키지 (tool_box 연동).

- ``core`` / ``gui``              : 좌표 생성기 (BallMapTool)
- ``binary_map`` / ``binary_gui`` : 좌표 -> 0/1 격자 변환기 (BallMapBinaryTool)

두 GUI 모두 BaseTool 인터페이스에 맞춰 parent 프레임에 임베드된다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool


class BallMapTool(BaseTool):
    """패키지 크기와 pitch 로부터 BGA 볼 좌표를 생성하는 도구."""

    name = "Ball Map 생성기 (좌표)"
    default_geometry = "980x700"
    min_size = (860, 620)

    def build_ui(self, parent: tk.Frame) -> None:
        _safe_build(parent, "gui", self.name)


class BallMapBinaryTool(BaseTool):
    """볼 좌표 목록을 0/1 격자로 변환해 그림과 텍스트로 보여주는 도구."""

    name = "Ball Map 변환기 (0,1)"
    default_geometry = "980x780"
    min_size = (780, 640)

    def build_ui(self, parent: tk.Frame) -> None:
        _safe_build(parent, "binary_gui", self.name)


def _safe_build(parent: tk.Frame, module_name: str, tool_name: str) -> None:
    """GUI 모듈을 지연 import 해 구성한다. 실패하면 프레임에 사유를 표시한다."""
    try:
        from importlib import import_module
        import_module("." + module_name, __package__).build_gui(parent)
    except Exception as e:
        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"{tool_name} 도구를 로드하지 못했습니다.\n\n{type(e).__name__}: {e}",
            justify="left", foreground="#884400", wraplength=560,
        ).pack(anchor="w")
