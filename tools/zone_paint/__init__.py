"""Zone 페인터 도구 패키지 (tool_box 연동).

원본은 모듈 상단 상수를 직접 고쳐 쓰던 단독 스크립트(zone_paint.py)였다.
tool_box 에 병합하면서 두 부분으로 나눴다.

- ``core`` : 칠하기 → 경계 생성(ortho/minlink/voronoi/convex) → 검증 →
             APDL 출력 엔진. 상단 상수를 ``configure()`` 로 주입할 수 있게 하고,
             ``print`` 를 GUI 로 흘릴 수 있는 ``log`` 로 바꾼 것 외에는 원본
             알고리즘 그대로다.
- ``gui``  : 범프 파일·패키지 외곽·생성 방법·여유 비율·메시 설정을 받는 폼.
             [칠하기 창 열기] 를 누르면 matplotlib 화면을 별도 창에 임베드한다.

zone_draw(직접 그리기)와 달리 범프를 사각 드래그로 칠해 구역을 지정하면
경계선을 알고리즘이 만들어 준다. 의존성(numpy, scipy, matplotlib, shapely)은
칠하기 창을 열 때만 로드된다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool


class ZonePaintTool(BaseTool):
    """범프를 칠해 구역을 지정하고 zone 경계를 자동 생성하는 도구."""

    name = "Zone 페인터 (칠하기 → 경계 자동생성)"
    default_geometry = "700x880"
    min_size = (640, 780)

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
