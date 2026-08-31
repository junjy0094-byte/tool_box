import tkinter as tk
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """새 도구를 추가하려면 이 클래스를 상속하고 name, build_ui를 구현하세요.

    - ``name``: 런처 목록에 표시되는 도구 이름 (클래스 속성으로 지정).
    - ``summary``: 한 줄 요약. 런처 도움말 목록에 함께 표시된다.
    - ``help_text``: 도움말 창에 표시할 상세 설명. 도구를 처음 쓰는 사람이
      읽고 바로 따라 할 수 있도록 "무엇을 하는가 / 입력 / 출력 / 사용 순서 /
      참고" 순서로 적는다.
    - ``default_geometry``: 도구 창의 기본 크기(``"WxH"``). 선택 사항.
    - ``min_size``: 도구 창의 최소 크기 ``(너비, 높이)``. 선택 사항.
      이 크기보다 작아지면 위젯이 잘리는 도구에서 지정한다.
    - ``build_ui(parent)``: parent 프레임 안에 UI를 구성.
    """

    name: str = ""
    summary: str = ""
    help_text: str = ""
    default_geometry: str = "900x650"
    min_size: tuple[int, int] = (480, 360)

    @abstractmethod
    def build_ui(self, parent: tk.Frame) -> None:
        """parent 프레임 안에 UI를 구성합니다."""
