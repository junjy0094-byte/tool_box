"""Gerber Trace Mapping 도구 패키지 (tool_box 연동).

원본: https://github.com/junjy0094-byte/trace_mapping
BaseTool 인터페이스에 맞춰 GUI 를 parent 프레임으로 임베드한다.

실제 파싱/렌더링 의존성(numpy, matplotlib, shapely, pcb-tools) 은
도구를 열 때만 로드되도록 ``build_ui`` 안에서 지연 import 한다.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from tools.base_tool import BaseTool


class TraceMappingTool(BaseTool):
    """Gerber/Artwork 파일을 NxM 격자의 동박 면적 비율로 변환하는 도구."""

    name = "Trace Mapping"
    default_geometry = "760x680"

    def build_ui(self, parent: tk.Frame) -> None:
        try:
            from .gui import build_gui
        except Exception as e:
            # 의존성 누락 등: 에러 메시지를 프레임에 직접 표시
            self._render_dependency_error(parent, e)
            return

        try:
            build_gui(parent)
        except Exception as e:
            self._render_dependency_error(parent, e)

    @staticmethod
    def _render_dependency_error(parent: tk.Frame, exc: Exception) -> None:
        msg = (
            "Trace Mapping 도구를 로드하지 못했습니다.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "다음 패키지가 설치되어 있는지 확인하세요:\n"
            "  pip install numpy matplotlib shapely pcb-tools"
        )
        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text=msg, justify="left", foreground="#884400",
            wraplength=560,
        ).pack(anchor="w")
