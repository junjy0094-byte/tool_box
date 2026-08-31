"""Ball Map Generator 도구 패키지 (tool_box 연동).

- ``core`` / ``gui``              : 좌표 생성기 (BallMapTool)
- ``binary_map`` / ``binary_gui`` : 좌표 -> 0/1 격자 변환기 (BallMapBinaryTool)

두 GUI 모두 BaseTool 인터페이스에 맞춰 parent 프레임에 임베드된다.
"""

import tkinter as tk
from tkinter import ttk

from tools.base_tool import BaseTool

_HELP_GEN = """\
[ 무엇을 하는 도구인가 ]
  패키지 크기와 pitch 만 넣으면 BGA 볼(범프) 중심 좌표를 만들어 준다.
  격자 배열과 지그재그 배열을 지원하며, 만든 좌표는 그대로 해석 입력이나
  다른 도구(Ball Map 변환기, Bump array 내 sub zone 생성기)의 입력이 된다.

[ 입력 ]
  · 배열 타입 : in-line / staggered-30 / staggered-45 / staggered-60
  · Ball pitch, Ball diameter, 패키지 X/Y 크기, Edge margin
  · 각도 기준축(X/Y), 코너에 볼 배치 여부 — staggered 에서만 의미 있음
  · 표시 방식(원/점), 그리드 표시, 소수점 자리

[ 출력 ]
  · 미리보기 그림
  · txt 파일 ([txt로 저장...]) — 첫 줄이 헤더 "0,1,2" 이고
    이후 "인덱스,x,y" 3열. 인덱스는 1부터 시작한다.

[ 사용 순서 ]
  1. 배열 타입과 pitch, 패키지 크기를 넣는다.
  2. [생성 / 미리보기] — 개수와 배치를 그림으로 확인한다.
  3. [txt로 저장...] 으로 좌표 파일을 만든다.

[ 참고 ]
  · in-line 은 중심 행/열을 비우므로 원점(0,0)에 볼이 없다.
    staggered 는 원점에 볼이 있다.
  · staggered 의 pitch 는 '최근접 볼 중심거리' 다.
    같은 행 간격 a = 2*P*cos(각도), 행 간격 b = P*sin(각도).
  · Edge margin 은 패키지 가장자리에서 비워 둘 여백이다.
  · 볼이 4,000개를 넘으면 그림을 래스터로 그리고, 20만개를 넘으면 진행 여부를
    묻고, 500만개를 넘으면 생성을 막는다.
"""

_HELP_BIN = """\
[ 무엇을 하는 도구인가 ]
  볼 좌표 목록을 0/1 격자(맵)로 바꾼다. 좌표가 x/y 각 축의 '최소 간격' 을
  pitch 로 하는 균일 격자 위에 놓여 있다고 보고, 볼이 있는 칸을 1, 없는 칸을
  0 으로 채운다. 볼 배치를 행렬 형태로 넘겨야 하는 스크립트나 문서 작업에 쓴다.

[ 입력 ]
  · 좌표 텍스트 — [클립보드에서 붙여넣기] / [파일 열기...] / 직접 입력
    구분자는 탭·콤마·공백 아무거나 되고, 숫자가 아닌 줄(헤더)은 건너뛴다.
    한 줄에 값이 3개 이상이면 마지막 두 개를 (x, y) 로 본다 →
    Ball Map 생성기의 "인덱스,x,y" 출력을 그대로 붙여넣어도 된다.

[ 출력 ]
  · [격자 그림] 탭 : 0/1 배치 그림
  · [격자 텍스트] 탭 : 행/열 인덱스가 붙은 0/1 표
  · [txt로 저장...] / [격자 텍스트 복사]

[ 사용 순서 ]
  1. 좌표를 붙여넣거나 파일을 연다 ([예시 넣기] 로 형식 확인 가능).
  2. [변환] 을 누른다.
  3. 그림으로 배치를 확인하고 텍스트를 저장하거나 복사한다.

[ 참고 ]
  · 격자의 첫 행(행 0)은 y 가 가장 작은 행이다.
  · 좌표가 균일 격자에서 벗어나 있으면 가장 가까운 칸에 넣고, 벗어난 점의
    개수를 요약에 알려 준다. 지그재그 배열은 x/y 최소 간격이 반 피치가 되어
    격자가 촘촘해질 수 있다.
  · 한 축의 서로 다른 좌표가 1개뿐이면 격자를 만들 수 없어 오류가 난다.
"""



class BallMapTool(BaseTool):
    """패키지 크기와 pitch 로부터 BGA 볼 좌표를 생성하는 도구."""

    name = "Ball Map 생성기 (좌표)"
    summary = "패키지 크기·pitch 로 BGA 볼 좌표를 생성하고 txt 로 저장"
    help_text = _HELP_GEN
    default_geometry = "980x700"
    min_size = (860, 620)

    def build_ui(self, parent: tk.Frame) -> None:
        _safe_build(parent, "gui", self.name)


class BallMapBinaryTool(BaseTool):
    """볼 좌표 목록을 0/1 격자로 변환해 그림과 텍스트로 보여주는 도구."""

    name = "Ball Map 변환기 (0,1)"
    summary = "볼 좌표 목록을 0/1 격자 맵으로 변환 (그림·텍스트)"
    help_text = _HELP_BIN
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
