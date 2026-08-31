"""Leadframe 그리기 도구 패키지 (tool_box 연동).

원본은 모듈 상단 상수를 직접 고쳐 쓰던 단독 스크립트(trace_gui.py)였다.
tool_box 에 병합하면서 두 부분으로 나눴다.

- ``core`` : 이미지 위에 라인을 따서 APDL area 매크로를 만드는 트레이싱 엔진.
             모듈 전역에 흩어져 있던 상태를 ``TraceApp`` 클래스로 묶고, 상단
             상수를 ``configure()`` 로 주입할 수 있게 하고, ``print`` 를 GUI 로
             흘릴 수 있는 ``log`` 로 바꾼 것 외에는 원본 로직 그대로다.
- ``gui``  : 배경 이미지·축척(이미지 실제 폭, 중심 오프셋)·그리드·반올림 자리수·
             출력 파일 설정을 받는 폼. [그리기 창 열기] 를 누르면 matplotlib
             화면을 별도 창에 임베드하고, 줌/팬 툴바와 단축키에 대응하는 명령
             버튼, 로그 창을 함께 띄운다.

의존성(matplotlib, Pillow)은 그리기 창을 열 때만 로드된다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool


class LeadframeTraceTool(BaseTool):
    """리드프레임 이미지를 따라 그려 APDL area 매크로를 만드는 도구."""

    name = "Leadframe 그리기"
    default_geometry = "680x720"
    min_size = (620, 620)

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
                      "  pip install matplotlib pillow"),
                justify="left", foreground="#884400", wraplength=560,
            ).pack(anchor="w")
