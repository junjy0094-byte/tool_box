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

_HELP_DB = """\
[ 무엇을 하는 도구인가 ]
  ANSYS 해석 모델(.db)을 Abaqus 입력 파일(.inp)로 옮긴다. 두 단계로 나뉜다.
    Step 1  MAPDL 을 띄워 .db 를 정리한 뒤 CDWRITE 로 .cdb 를 뽑는다
    Step 2  .cdb 를 읽어 절점/요소/재질/구속/하중을 Abaqus .inp 로 다시 쓴다
  Step 2 만 쓸 수도 있어서, 이미 .cdb 가 있으면 ANSYS 없이도 변환할 수 있다.

[ 입력 ]
  · ANSYS .db 파일 (Step 1 부터 실행할 때) 또는 .cdb (Step 2 만 실행할 때)
  · Settings : Node Merge Tol, 초기/최종 온도, CDWRITE UNBLOCKED 여부
  · Model Configuration : 대칭 모드(Quarter / Full), 직교이방성 재질 사용 여부와
    재질 번호 범위(기본 9990-9999), Free Mesh 여부
  · MAPDL Launch Settings : ANSYS 버전, 프로세서 수, 라이선스 종류

[ 출력 ]
  · <모델>.cdb  (Step 1 결과)
  · <모델>.inp  (Step 2 결과 — Abaqus 입력 파일)
  · 실행 로그 (창 아래 Log)

[ 사용 순서 ]
  1. [Browse] 로 .db 를 고른다. 파일 이름이 'sub' 로 끝나면 Sub-model 이
     자동으로 켜진다.
  2. 대칭 모드와 재질 설정을 확인한다.
  3. "Run up to" 에서 어디까지 실행할지 고르고 [Run].
  4. 진행 상황과 오류는 Log 에서 확인한다.

[ 참고 — 반드시 읽을 것 ]
  · 도구 안의 [Notes / Help] 버튼에 더 자세한 주의사항이 정리되어 있다.
  · 절점 좌표에는 항상 x1000 배율이 적용된다 (m → mm 가정). 모델 단위가 m 이
    아니면 결과 좌표가 틀어진다.
  · 현재 8절점 Hex 요소(C3D8I)만 지원한다. Free Mesh 는 체크하면 실행이 막힌다.
  · 대칭 모드 Half(1/2)는 미구현이라 실행이 막힌다.
  · Step 1 은 로컬에 ANSYS 가 설치되어 있어야 하고 ansys-mapdl-core 가 필요하다
    (pip install ansys-mapdl-core). Step 2 는 표준 라이브러리만으로 동작한다.
"""



class DbToInpTool(BaseTool):
    """ANSYS .db 를 정리해 Abaqus .inp 로 변환하는 도구."""

    name = "DB → INP 변환기 (ANSYS→Abaqus)"
    summary = "ANSYS .db 를 정리해 .cdb 로 뽑고 Abaqus .inp 로 변환"
    help_text = _HELP_DB
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
