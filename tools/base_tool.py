import tkinter as tk
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """새 도구를 추가하려면 이 클래스를 상속하고 name, build_ui를 구현하세요.

    - ``name``: 런처 목록에 표시되는 도구 이름 (클래스 속성으로 지정).
    - ``default_geometry``: 도구 창의 기본 크기(``"WxH"``). 선택 사항.
    - ``min_size``: 도구 창의 최소 크기 ``(너비, 높이)``. 선택 사항.
      이 크기보다 작아지면 위젯이 잘리는 도구에서 지정한다.
    - ``build_ui(parent)``: parent 프레임 안에 UI를 구성.
    """

    name: str = ""
    default_geometry: str = "900x650"
    min_size: tuple[int, int] = (480, 360)

    @abstractmethod
    def build_ui(self, parent: tk.Frame) -> None:
        """parent 프레임 안에 UI를 구성합니다."""
