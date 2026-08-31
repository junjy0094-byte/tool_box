"""Zone 분할기 도구 패키지 (tool_box 연동).

원본은 모듈 상단 상수를 직접 고쳐 쓰던 단독 스크립트(zone_draw.py)였다.
tool_box 에 병합하면서 두 부분으로 나눴다.

- ``core`` : 그리기/스냅/검증/APDL 출력 엔진. 상단 상수를 ``configure()`` 로
             주입할 수 있게 하고, ``print`` 를 GUI 로 흘릴 수 있는 ``log`` 로
             바꾼 것 외에는 원본 로직 그대로다.
- ``gui``  : 패키지 외곽·스냅·메시 설정을 입력받는 간단한 폼. [그리기 창 열기]
             를 누르면 matplotlib 화면을 별도 창에 임베드해 띄운다.

의존성(numpy, scipy, matplotlib, shapely)은 그리기 창을 열 때만 로드된다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool


class ZoneDrawTool(BaseTool):
    """범프 맵 위에 zone 폴리곤을 그려 ANSYS APDL 매크로로 내보내는 도구."""

    name = "Zone 분할기 (범프 → APDL 매크로)"
    default_geometry = "680x800"
    min_size = (620, 720)

    def build_ui(self, parent: tk.Frame) -> None:
        try:
            from .gui import build_gui
            build_gui(parent)
        except Exception as e:
            frame = ttk.Frame(parent, padding=16)
            frame.pack(fill="both", expand=True)
            ttk.Label(
                frame,
                text=(f"{self.name} 도구를 로드하지 못했습니다.\n\n"
                      f"{type(e).__name__}: {e}\n\n"
                      "다음 패키지가 설치되어 있는지 확인하세요:\n"
                      "  pip install numpy scipy matplotlib shapely"),
                justify="left", foreground="#884400", wraplength=560,
            ).pack(anchor="w")
