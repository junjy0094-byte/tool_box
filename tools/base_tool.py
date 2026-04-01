import tkinter as tk
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """새 도구를 추가하려면 이 클래스를 상속하고 name, build_ui를 구현하세요."""

    @property
    @abstractmethod
    def name(self) -> str:
        """탭에 표시될 도구 이름"""

    @abstractmethod
    def build_ui(self, parent: tk.Frame) -> None:
        """parent 프레임 안에 UI를 구성합니다."""
