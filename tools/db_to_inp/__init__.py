"""ANSYS .db -> Abaqus .inp 변환 도구 패키지 (tool_box 연동).

원본: https://github.com/junjy0094-byte/ansys_abaqus_conversion
동기화 기준: default branch 51db615 (2026-08)

원본 app/ 패키지를 그대로 옮겼고, 수정은 gui.ConverterApp 이 Tk 창뿐 아니라
Frame 에도 붙을 수 있게 창 속성 설정을 조건부로 바꾸고 build_gui(parent)
진입점을 추가한 것뿐이다.

Step 1(MAPDL cleanup + CDWRITE)은 PyMAPDL(ansys-mapdl-core)과 로컬 ANSYS
설치가 필요하며, 해당 import 는 Step 1 실행 시점에만 일어난다. Step 2
(CDB -> INP 빌드)는 표준 라이브러리만으로 동작한다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool


class DbToInpTool(BaseTool):
    """ANSYS .db 를 정리해 Abaqus .inp 로 변환하는 도구."""

    name = "DB → INP 변환기 (ANSYS→Abaqus)"
    # 원본 앱은 창을 720x880 으로 고정했지만 실제 컨텐츠는 971x777 을
    # 요구해 Browse 버튼과 Sub-model 체크박스가 잘렸다.
    default_geometry = "1000x900"
    min_size = (990, 700)

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
                      f"{type(e).__name__}: {e}"),
                justify="left", foreground="#884400", wraplength=560,
            ).pack(anchor="w")
