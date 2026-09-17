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
  · 또는 .db 가 들어 있는 폴더 — "Folder (batch)" 모드로 한 번에 전부 변환
    (파일명 앞/뒤 필터로 대상을 좁힐 수 있다)
  · Settings : Node Merge Tol, 초기/최종 온도, CDWRITE UNBLOCKED 여부
  · Model Configuration : 대칭 모드(Quarter / Full), 직교이방성 재질 사용 여부와
    재질 번호 범위(기본 9990-9999), Free Mesh 여부
  · MAPDL Launch Settings : ANSYS 버전, 프로세서 수, 라이선스 종류,
    동시 실행 파일 수(Parallel jobs)

[ 출력 ]
  · <모델>.cdb  (Step 1 결과)
  · <모델>.inp  (Step 2 결과 — Abaqus 입력 파일)
    일괄 모드에서는 <모델>_<들어있던 폴더명>.inp 로 이름이 붙고,
    선택한 폴더의 바깥 경로에 만든 "<폴더명>_inp" 폴더에 모두 모인다.
  · 실행 로그 (창 아래 Log), Target Files 표와 진행 막대

[ 사용 순서 ]
  1. 파일 하나만 변환하려면 "Single file" 을 고르고 [Browse] 로 .db 를 고른다.
     파일 이름이 'sub' 로 끝나면 Sub-model 이 자동으로 켜진다.
     폴더 전체를 변환하려면 "Folder (batch)" 를 고르고 폴더를 지정한다.
     (하위 폴더까지 훑으려면 "Include subfolders" 를 켠다)
  2. 대칭 모드와 재질 설정을 확인한다.
  3. 폴더 모드면 "Name starts with / ends with" 로 대상을 좁히고,
     아래 Target Files 표에서 실제로 무엇이 변환될지 확인한다.
  4. 여러 파일을 동시에 돌리려면 "Parallel jobs" 를 2 이상으로 올린다.
  5. "Run up to" 에서 어디까지 실행할지 고르고 [Run].
  6. 진행 상황은 Target Files 표의 상태와 진행 막대에서, 자세한 내용과 오류는
     Log 에서 확인한다. 도중에 멈추려면 [Stop].

[ 폴더 일괄 변환 / 병렬 실행 ]
  · 폴더 모드에서는 파일마다 이름이 'sub' 로 끝나는지 따로 판단해 Sub-model
    여부를 자동 적용한다. Sub-model 체크박스는 단일 파일 모드에서만 쓴다.
  · 중간 산출물은 파일별로 <폴더>/_data/<모델명>/ 에 나뉘어 저장되고,
    결과 .inp 는 원본 .db 옆에 <모델명>.inp 로 생긴다.
  · 한 파일이 실패해도 나머지는 계속 돌고, 끝에 성공/실패 요약이 찍힌다.
  · Parallel jobs 는 동시에 돌릴 파일 개수다. 파일마다 MAPDL 이 따로 뜨므로
    실제 사용 코어는 (Parallel jobs x Processors) 이고 라이선스도 그만큼
    동시에 물린다. 코어/라이선스/메모리 여유를 보고 정할 것.
  · 병렬 실행 중에는 로그 줄 앞에 [모델명] 이 붙는다.

[ 파일명 필터 / 대상 확인 / 진행 상황 / 중단 ]
  · Name starts with / ends with : 확장자를 뺀 파일명 기준으로 앞/뒤를 거른다.
    대소문자는 구분하지 않고, 비워 두면 필터 없이 전부 대상이다.
    둘 다 채우면 AND 조건 (앞도 맞고 뒤도 맞는 파일만).
  · Target Files 표 : 설정을 바꿀 때마다 실제 변환 대상이 바로 갱신된다.
    파일명 / Sub 여부 / 상태 / 만들어질 .inp 이름 / 원본 폴더를 보여 준다.
  · 상태는 Pending -> Running -> Done / Failed / Cancelled 로 바뀌고,
    표 아래 진행 막대와 "n / N finished" 로 전체 진행률을 볼 수 있다.
  · [Stop] : 아직 시작하지 않은 파일은 바로 취소되고, 이미 MAPDL 로 들어간
    파일은 진행 중인 MAPDL 명령이 끝나는 단계 경계에서 멈춘다. 명령 하나가
    오래 걸리면 그만큼 늦게 반응한다. 중단된 파일의 .inp 는 만들어지지 않는다.

[ INP 출력 위치 / 이름 ]
  · 일괄 모드는 결과 .inp 를 원본 옆이 아니라 한 폴더에 모은다. 기본 위치는
    선택한 폴더의 바깥(상위) 경로에 만드는 "<폴더명>_inp" 이고, "INP output"
    칸에서 다른 곳으로 바꿀 수 있다.
  · 파일명 뒤에는 그 .db 가 들어 있던 폴더 이름이 붙는다.
    예: D:/work/caseA/model.db -> D:/work/caseA_inp/model_caseA.inp
    하위 폴더까지 훑을 때 같은 이름을 구분하기 위한 규칙이고, 그래도 겹치면
    _2, _3 이 붙는다.
  · 단일 파일 모드는 기존과 같이 .db 옆에 <모델명>.inp 로 만든다.

[ 참고 — 반드시 읽을 것 ]
  · 도구 안의 [Notes / Help] 버튼에 더 자세한 주의사항이 정리되어 있다.
  · 절점 좌표에는 항상 x1000 배율이 적용된다 (m → mm 가정). 모델 단위가 m 이
    아니면 결과 좌표가 틀어진다.
  · 현재 8절점 Hex 요소(C3D8I)만 지원한다. Free Mesh 는 체크하면 실행이 막힌다.
  · 대칭 모드 Half(1/2)는 미구현이라 실행이 막힌다.
  · Sub-model 변환에서는 INISTATE 초기응력이 있으면 *INITIAL CONDITIONS,
    TYPE=STRESS 블록으로 함께 써 준다 (값이 0 이 아닌 재질을 자동으로 찾는다).
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
    default_geometry = "1080x980"
    min_size = (1040, 800)

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
