"""Gerber Trace Mapping 도구 패키지 (tool_box 연동).

원본: https://github.com/junjy0094-byte/trace_mapping
동기화 기준: default branch efa479d (2026-08)
패키지 내부 임포트를 상대 임포트로 바꾸고, gui.gui_main() 을
build_gui(parent) + gui_main() 으로 분리한 것 외에는 원본과 동일하다.
BaseTool 인터페이스에 맞춰 GUI 를 parent 프레임으로 임베드한다.

실제 파싱/렌더링 의존성(numpy, matplotlib, shapely, pcb-tools) 은
도구를 열 때만 로드되도록 ``build_ui`` 안에서 지연 import 한다.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from tools.base_tool import BaseTool

_HELP_TRACE = """\
[ 무엇을 하는 도구인가 ]
  PCB/기판의 Gerber(artwork) 파일을 읽어, 지정한 NX x NY 격자의 칸마다
  동박이 차지하는 면적 비율(0~1)을 계산한다. 해석 모델에서 배선층을 한 장씩
  모델링하는 대신 '칸별 동박 비율' 로 물성을 등가화해 쓰기 위한 도구다.

[ 입력 ]
  · Gerber / artwork 파일 (.art, .gbr) — [Add Files] 또는 [Add Dir]
  · Grid Parameters : NX, NY (격자 분할 수), Merge Tolerance, Display Pixels
  · Mapping Bounds  : 비우면 Gerber 파일에서 읽은 범위를 그대로 쓴다.
                      값을 넣으면 모든 층에 같은 범위를 강제한다.
  · Custom Grid     : 균일 격자 대신 셀 경계 좌표를 CSV(열벡터)로 직접 지정
  · Output Directory: 비우면 입력 파일과 같은 폴더

[ 출력 ]  (층별로 <파일이름>.xxx)
  · <층>.csv                  격자별 동박 면적비. 행=Y(아래→위), 열=X(왼→오)
                              머리말에 격자 크기·범위·(커스텀이면) 셀 경계가 들어감
  · <층>.png                  동박 형상 + 비율 맵 그림
  · all_layers_summary.png    전체 층 요약 그림
  · <층>_reference_full.mac   (옵션) 래스터 서브픽셀 1개당 2D 요소 1개인
                              APDL 참조 모델. 매우 커질 수 있어 Stride 로 줄인다.
  · 래스터 캐시(.npz)         같은 파일을 다시 처리할 때 재사용

[ 사용 순서 ]
  1. Gerber 파일을 추가한다.
  2. NX / NY 를 정한다 (해석 격자와 맞추는 것이 보통).
  3. 필요하면 Mapping Bounds 나 Custom Grid 로 범위·격자를 고정한다.
  4. 옵션을 확인하고 [Run] — 진행 상황은 Log 창에 표시된다.
  5. 끝나면 그림이 뜨고 CSV 가 저장된다. 이후 후처리(Post-process) 단계에서
     저장된 결과를 다시 그려 볼 수 있다.

[ 참고 ]
  · Use Gerber polarity(권장)를 켜면 어두운/밝은 폴리곤(빼기 영역)을 제대로 처리한다.
  · Exclude largest poly 는 보드 외곽 같은 거대한 폴리곤을 제외할 때 쓴다.
  · Interactive exclude 를 켜면 제외할 폴리곤을 그림에서 직접 고를 수 있다.
  · 계산은 셀 안을 서브픽셀로 잘게 나눠 채워진 비율을 세는 방식이라,
    Display Pixels 를 키우면 정확해지지만 느려진다.
  · numpy / matplotlib / shapely / pcb-tools 가 필요하다.
"""



class TraceMappingTool(BaseTool):
    """Gerber/Artwork 파일을 NxM 격자의 동박 면적 비율로 변환하는 도구."""

    name = "Trace Mapping"
    summary = "Gerber 배선 도면을 NxM 격자의 동박 면적 비율로 변환 (CSV/PNG/APDL)"
    help_text = _HELP_TRACE
    # 업스트림 GUI 는 Mapping Bounds 한 줄만으로 1153px 를 요구한다.
    # 창이 이보다 작으면 우측 입력칸과 하단 Run 버튼이 잘린다.
    default_geometry = "1200x740"
    min_size = (1180, 700)

    def build_ui(self, parent: tk.Frame) -> None:
        try:
            from .gui import build_gui
        except Exception as e:
            # 의존성 누락 등: 에러 메시지를 프레임에 직접 표시
            self._render_dependency_error(parent, e)
            return

        try:
            build_gui(parent)
        except Exception as e:
            self._render_dependency_error(parent, e)

    @staticmethod
    def _render_dependency_error(parent: tk.Frame, exc: Exception) -> None:
        msg = (
            "Trace Mapping 도구를 로드하지 못했습니다.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "다음 패키지가 설치되어 있는지 확인하세요:\n"
            "  pip install numpy matplotlib shapely pcb-tools"
        )
        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text=msg, justify="left", foreground="#884400",
            wraplength=560,
        ).pack(anchor="w")
