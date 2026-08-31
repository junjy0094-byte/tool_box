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

_HELP_LF = """\
[ 무엇을 하는 도구인가 ]
  리드프레임 같은 형상 이미지를 배경으로 깔고 그 위를 따라 그려서, ANSYS APDL
  area(면) 생성 매크로를 만든다. 도면 캡처나 사진밖에 없을 때 형상을 해석
  모델로 옮기는 용도다. 이미지 픽셀은 실제 치수(um)로 환산되어 좌표가 나온다.

[ 입력 ]
  · 배경 이미지 (png/jpg/bmp/tif)
  · 이미지 가로 전체의 실제 폭 [um] — 이 값으로 픽셀↔um 축척이 정해진다
  · 이미지 중심이 놓일 좌표(오프셋), 그리드 피치, 목표 요소 크기, 반올림 자리수
  · (선택) 이전에 저장한 polys.json 을 불러와 이어 작업

[ 출력 ]  (설정한 출력 폴더에 저장)
  · geom.mac    K / LSTR / AL 로 면을 만들고, 홀은 ASBA 로 빼는 APDL 매크로
  · polys.json  폴리곤·보조선·축척 정보 (다시 불러와 이어 작업)

[ 사용 순서 ]
  1. 이미지를 고르고 [이미지 크기 확인] 으로 환산 축척(1px = ? um)을 확인한다.
  2. [그리기 창 열기].
  3. 좌클릭으로 점을 찍고 (c) 로 닫으면 외곽(초록), (h) 로 닫으면 홀(빨강)이 된다.
  4. (a) 보조선 모드에서 기준선을 그어 두면 스냅과 평행/수직 구속에 쓸 수 있다.
     (r) 로 레퍼런스 보조선을 고르고 (p)/(e) 로 평행/수직 구속을 건다.
  5. (s) 선택 모드에서 폴리곤을 고르고 드래그 이동, 회전(. ,), 반전(f v),
     복사·붙여넣기(Ctrl+C/V), 삭제(Delete)를 한다.
  6. (w) 로 geom.mac 과 polys.json 을 저장한다.

[ 참고 ]
  · 스냅 우선순위는 기존 정점 → 보조선 위 최근접점 → 그리드 순이다.
  · AUTOFIT(k)은 이동 중 선택 영역의 좌/우(하/상) 끝과 중심이 다른 형상의
    좌표나 원점과 가까워지면 그 값에 딱 맞춰 준다. 허용범위는 - / = 로 조절한다.
  · 반올림 자리수(1/2/3 키)는 이미 그린 형상 전체에 즉시 적용되고,
    반올림으로 겹친 점은 자동으로 지워진다.
  · 홀은 중심이 어느 외곽 안에 있는지 보고 그 면에서 자동으로 빼 준다.
  · 창 아래 툴바로 확대/이동을 하는 동안에는 클릭이 점으로 들어가지 않는다.
  · matplotlib / Pillow 가 필요하다.
"""



class LeadframeTraceTool(BaseTool):
    """리드프레임 이미지를 따라 그려 APDL area 매크로를 만드는 도구."""

    name = "Leadframe 그리기"
    summary = "이미지를 따라 그려 APDL area 매크로 생성 (픽셀→um 환산)"
    help_text = _HELP_LF
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
