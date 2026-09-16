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

_HELP_ZONE = """\
[ 무엇을 하는 도구인가 ]
  범프(볼) 배열이 깔린 패키지 평면 위에 zone(구역) 폴리곤을 직접 그려서,
  ANSYS APDL 로 그 구역들을 만들어 주는 매크로를 뽑는다. 범프마다 어느 구역에
  속하는지 라벨이 붙고, 구역 경계에 걸친 범프는 컨테이너에서 미리 도려내
  메시가 깨지지 않게 처리한다. AutoCAD 로 선을 긋는 방식에 가깝다.

[ 입력 ]
  · 범프 좌표 파일 — 헤더 1줄 + "인덱스,x,y[,지름]" (Ball Map 생성기 출력 그대로 가능)
    지름 열이 없으면 설정의 '기본 볼 지름 D' 를 쓴다.
  · 패키지 외곽 X/Y 최소·최대 — [범프 좌표에서 자동 채우기] 로 채울 수 있다.
  · 스냅/톨러런스, 메시 설정 (범프 한 변당 분할수, 삼각 요소 여부 등)

[ 출력 ]  (설정한 출력 폴더에 저장)
  · labels.txt   범프별 "인덱스,x,y,zone 번호"
  · bumps.mac    범프를 사각형(RECTNG)으로 만드는 APDL 매크로
  · zones.mac    zone 컨테이너 생성 + 홀 차감 + 범프 부울(ASBA) 매크로
  · run.mac      bumps/zones 를 불러 위상 정리·검증·메시까지 하는 실행 매크로
  · zones.png    화면 그림
  · polys.npz    그린 폴리곤 (다시 불러와 이어 작업)

[ 사용 순서 ]
  1. 범프 파일을 고르고 [범프 좌표에서 자동 채우기] 로 외곽을 잡는다.
  2. [그리기 창 열기].
  3. 좌클릭으로 점을 찍어 선을 잇는다. 첫 점을 다시 클릭하거나 (c) 로 닫는다.
     양 끝이 패키지 외곽선 위에 있으면 (e)/(E) 로 외곽을 따라 자동으로 닫는다.
  4. (f) 로 남은 영역을 자동으로 폴리곤화하면 빈 곳 없이 채워진다.
  5. (v) 로 겹침·미할당·면적을 검증하고, (s) 로 APDL 매크로를 저장한다.
  6. (w)/(r) 로 폴리곤을 저장·복원할 수 있다.

[ 참고 ]
  · 스냅 6종(정점/범프/여유중심/격자/외곽선/라인 위)은 숫자 키 1~6 으로 켜고 끈다.
  · 오른쪽 명령 버튼은 단축키와 같은 동작이라 키보드를 안 써도 된다.
  · 검증에서 '가로지름' 은 경계가 범프 내부를 지난다는 뜻이다. 저장할 때
    그런 범프는 컨테이너 외곽에서 잘라내고 ASBA 대상에서 뺀다.
  · 모든 톨러런스가 패키지 크기에 비례해 정해지므로 mm/um 단위와 무관하다.
  · numpy / scipy / matplotlib / shapely 가 필요하다.
"""



class ZoneDrawTool(BaseTool):
    """범프 맵 위에 zone 폴리곤을 그려 ANSYS APDL 매크로로 내보내는 도구."""

    name = "Bump array 내 sub zone 생성기"
    summary = "범프 배열 위에 zone 폴리곤을 그려 ANSYS APDL 매크로로 출력"
    help_text = _HELP_ZONE
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
