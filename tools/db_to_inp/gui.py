"""ANSYS .db -> Abaqus .inp 변환 GUI.

원본은 단독 실행 앱(converter_app.py)이었으며, tool_box 런처가 넘겨주는
parent 프레임 안에 임베드할 수 있도록 ``build_gui(parent)`` 를 추가했다.
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import atexit
import threading
import queue
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from . import mapdl_ops, cdb_utils, inp_writer, utils


NOTES_TEXT = """\
ANSYS -> Abaqus Converter : 참고 사항 (Notes)
================================================

1. Effective Material (직교이방성 재질)
   - "Orthotropic material present" 체크박스가 켜져 있을 때만 동작합니다.
     꺼져 있으면 모든 재질을 등방성(ISOTROPIC)으로 처리합니다.
   - Material # range(기본값 9990-9999)에 해당하는 재질 번호만 직교이방성
     (ENGINEERING CONSTANTS + ORTHOTROPIC EXPANSION)으로 처리되고, 범위 밖 재질은
     등방성으로 처리됩니다. 해당 번호대의 재질을 ANSYS에 미리 정의해 두어야 합니다.
   - 범위는 Model Configuration에서 "9990-9999"처럼 직접 수정할 수 있습니다.
   - CTE(열팽창계수) 값은 CTEX/CTEY/CTEZ를 먼저 찾고, 없으면 ALPX/ALPY/ALPZ 값을
     사용합니다 (등방성 재질은 X축 값만 사용).

2. 좌표 스케일 (Scale)
   - 노드 좌표는 항상 x1000 배율이 자동 적용됩니다 (예: ANSYS 모델 단위가 m일 때
     Abaqus에서 mm 단위로 쓰기 위함). 코드에 고정되어 있으며 UI에서 바꿀 수 없습니다.
   - 원본 모델 단위가 m가 아니면 결과 좌표가 잘못될 수 있으니 실행 전 반드시 확인하세요.

3. Mesh Type
   - 현재는 8절점 Hex 요소(C3D8I)만 지원합니다.
   - "Free Mesh" 체크박스는 UI에 준비만 되어 있고 실제 변환 로직은 아직 없습니다.
     체크한 채로 Run 하면 실행이 차단됩니다. (추후 업데이트 예정)

4. 대칭 모드 (Symmetry Mode)
   - Quarter (1/4): X=0, Y=0 대칭면 기준 BC를 자동 적용합니다. (기본값, 기존 동작과 동일)
   - Full model (대칭 없음): 전체 모델의 min/max X,Y,Z 좌표를 구해
       * (minX, minY, minZ) 노드  -> 전체 고정 (Ux,Uy,Uz)
       * (maxX, minY, minZ) 노드  -> Uy, Uz 고정
       * (minX, maxY, minZ) 노드  -> Uz 고정
     의 3점 구속으로 강체운동만 제거합니다. 대칭 경계조건은 적용하지 않습니다.
   - Half (1/2): 아직 미구현입니다. 선택 후 Run 하면 실행이 차단됩니다. (추후 업데이트 예정)

5. Tie 처리
   - CE(Constraint Equation) 또는 컴포넌트 이름 패턴(TIE_MASTER/TIE_SLAVE 등)으로
     tie 표면을 자동 탐지합니다.
   - tie 표면을 축정렬 평면(axis-aligned plane) 단위로 분리하는 tolerance는 0.001
     (좌표 스케일 적용 후 기준)로 코드에 고정되어 있습니다.

6. Orientation
   - 직교이방성 재질(999x)에는 로컬 좌표계 (1,0,0,0,1,0)이 모든 재질에 동일하게
     적용됩니다. 실제 방향이 다르면 생성된 INP에서 직접 수정해야 합니다.

7. Submodel 모드
   - exteriorTolerance=0.05로 코드에 고정되어 있습니다.
   - .db 파일명이 "sub"로 끝나면(대소문자 무관, 예: model_sub.db) Sub-model 체크가
     자동으로 켜지고, 그렇지 않으면 자동으로 꺼집니다. File Selection 칸에서 직접
     체크/해제로 덮어쓸 수도 있습니다.
   - 초기응력(Initial Stress): Sub-model 변환에서만 동작합니다. Step 1 에서
     가장 번호가 작은 요소 하나만 ESEL 한 뒤 INISTATE,LIST 를 읽습니다.
     그 목록에서 6성분이 모두 0 이 아닌 재질(matid)을 그대로 골라 오므로
     재질 번호를 따로 지정할 필요가 없습니다. CSYS 열은 무시합니다.
   - 가져온 값은 INP 의 *INITIAL CONDITIONS, TYPE=TEMPERATURE 바로 아래에
       *INITIAL CONDITIONS, TYPE=STRESS
       eset901, s1, s2, s3, s4, s5, s6
     형태로 재질마다 한 줄씩 들어갑니다. 초기응력이 없거나 해당 재질의
     요소가 모델에 없으면 그 줄은 만들어지지 않습니다.

7-1. clean_model.db 저장
   - Settings 의 "Save cleaned model as clean_model.db" 는 기본이 꺼져 있습니다.
   - 정리된 모델을 ANSYS 에서 다시 열어 볼 때만 필요한 보관용 파일입니다.
     .inp 변환(Step 2)은 clean_model.cdb 만 읽으므로 꺼도 결과는 같습니다.
   - 큰 모델일수록 저장에 시간이 걸리므로, 필요할 때만 켜세요.

8. MAPDL 실행 옵션
   - 병렬 모드는 SMP(-smp)로 고정되어 있습니다. MPI 등 다른 옵션이 필요하면
     코드 수정이 필요합니다.

9. 초기/최종 온도
   - Settings에서 직접 설정 가능합니다 (기본값: 초기 183.0, 최종 25.0).

10. 폴더 일괄 변환 (Batch)
   - File Selection에서 "Folder (batch)"를 고르면 선택한 폴더 안의 .db 파일을
     모두 변환합니다. "Include subfolders"를 켜면 하위 폴더까지 훑습니다.
   - 일괄 모드에서는 파일마다 이름이 "sub"로 끝나는지 자동으로 판단해
     Sub-model 여부를 개별 적용합니다 (Sub-model 체크박스는 단일 파일 모드 전용).
   - 중간 산출물은 파일별로 분리된 폴더(<폴더>/_data/<모델명>/)에 저장되고,
     결과 .inp는 원본 .db와 같은 폴더에 <모델명>.inp 로 생성됩니다.
     (단일 파일 모드는 기존과 같이 <폴더>/_data/ 를 그대로 씁니다.)
   - 한 파일이 실패해도 나머지는 계속 진행하며, 마지막에 성공/실패 요약을 찍습니다.

11. 병렬 실행 (Parallel jobs)
   - MAPDL Launch Settings의 "Parallel jobs"는 동시에 돌릴 파일 개수입니다.
     1이면 기존처럼 한 번에 하나씩 순차 실행합니다.
   - 파일마다 MAPDL 인스턴스가 따로 뜹니다. 즉 실제로 쓰는 코어 수는
     (Parallel jobs x Processors)이고, 라이선스도 그만큼 동시에 물립니다.
     코어/라이선스/메모리 여유를 보고 값을 정하세요.
   - 병렬 실행 중에는 로그 줄 앞에 [모델명] 이 붙어 어느 파일의 로그인지
     구분됩니다.

12. 파일명 필터 (Name starts with / ends with)
   - 일괄 모드에서 확장자를 뺀 파일명 기준으로 앞/뒤를 걸러냅니다.
     대소문자는 구분하지 않고, 비워 두면 필터 없이 전부 대상입니다.
   - 둘 다 채우면 AND 조건입니다 (앞도 맞고 뒤도 맞는 파일만).
   - 예: starts="pkg_", ends="_sub" -> pkg_a_sub.db 는 대상, pkg_a.db 는 제외.

13. Target Files 목록 / 진행 상황
   - 설정을 바꿀 때마다 아래 Target Files 표에 실제 변환 대상이 미리 표시됩니다
     (파일명 / Sub 여부 / 상태 / 만들어질 .inp 이름 / 원본 폴더).
   - 실행하면 상태가 Pending -> Running -> Done / Failed / Cancelled 로 바뀌고,
     표 아래 진행 막대와 "n / N finished" 로 전체 진행률을 볼 수 있습니다.

14. Stop 버튼
   - 아직 시작하지 않은 파일은 즉시 Cancelled 로 넘어갑니다.
   - 이미 떠 있는 MAPDL 인스턴스는 바로 종료시킵니다. 먼저 프로세스를 죽인 뒤
     exit() 을 부르므로, 응답이 없는 인스턴스에서도 바로 끝납니다
     (Windows: taskkill /F /T /PID). 따로 작업 관리자에서 죽일 필요가 없습니다.
   - 라이선스가 없거나 서버가 느려 기동 중(최대 120초 대기)에 눌러도 바로
     멈춥니다. 기다리던 쪽은 즉시 포기하고, 뒤늦게 떠 버린 인스턴스는 뒤에서
     따로 정리합니다.
   - 진행 중이던 MAPDL 명령은 그 과정에서 끊기며, 해당 파일은 실패가 아니라
     Cancelled 로 기록됩니다.
   - 중단된 파일의 .inp 는 만들어지지 않습니다.

15. INP 출력 폴더와 파일명
   - 일괄 모드에서는 결과 .inp 를 원본 옆이 아니라 한 폴더에 모읍니다.
     기본 위치는 선택한 폴더의 바깥(상위) 경로에 만드는 "<폴더명>_inp" 이고,
     File Selection 의 "INP output" 칸에서 다른 곳으로 바꿀 수 있습니다.
   - 파일명 뒤에는 그 .db 가 들어 있던 폴더 이름이 붙습니다.
     예: D:/work/caseA/model.db -> D:/work/caseA_inp/model_caseA.inp
     하위 폴더까지 훑을 때 서로 다른 폴더의 같은 이름을 구분하기 위한 규칙이며,
     그래도 겹치면 _2, _3 이 붙습니다.
   - 단일 파일 모드는 기존과 같이 .db 옆에 <모델명>.inp 로 만듭니다.

16. MAPDL 기동 실패 ("An error occurred when connecting to MAPDL")
   - 1차 시도는 Parallel jobs=1 일 때 예전과 완전히 같은 인자로 띄웁니다
     (포트/대기시간을 지정하지 않고 PyMAPDL 기본값에 맡김). 병렬일 때만
     인스턴스끼리 겹치지 않게 포트를 나눠 줍니다.
   - 1차가 실패하면 포트와 대기시간(120초)을 직접 지정해 한 번 더 시도합니다.
   - 실제로 넘긴 인자를 Log 에 그대로 찍고, 실패하면 MAPDL 이 작업 폴더에 남긴
     .err/.out 내용도 같이 찍습니다. 원인은 대부분 거기에 있습니다.
   - 기동에 실패했거나 Stop 을 눌렀거나 앱을 닫을 때, 우리가 띄운 MAPDL 은
     PID 로 강제 종료(Windows: taskkill /F /T)까지 해서 남기지 않습니다.
   - 기동에 쓸 포트는 시도할 때마다 비어 있는지 확인해서 명시합니다.
   - 그래도 MAPDL 이 다른 포트에 gRPC 서버를 여는 경우가 있습니다. PyMAPDL 은
     원래 포트에서 기다리다 접속에 실패하지만 프로세스는 멀쩡히 살아 있으므로,
     .out 에서 실제 리슨 포트를 읽어 그 포트로 다시 붙어 그대로 진행합니다
     (로그의 "Attached to MAPDL on port ..." 줄).
   - 포트를 정확히 읽기 위해 기동 전에 이전 실행의 .out/.err/.lock 을 지웁니다.
   - 프록시 환경변수(http_proxy/https_proxy)가 있으면 grpc 가 127.0.0.1 접속까지
     프록시로 보내 버려, MAPDL 이 정상적으로 리스닝 중인데도 접속에 실패합니다.
     그래서 기동 전에 로컬만 프록시를 우회하도록 맞춰 둡니다
     (GRPC_ENABLE_HTTP_PROXY=0, NO_PROXY 에 localhost/127.0.0.1/::1 추가).
     이 설정은 이 프로그램이 도는 동안에만 적용되고 시스템에는 영향이 없습니다.
   - 변환기와 무관하게 PyMAPDL + ANSYS 설치만 점검하려면
     "python scripts/mapdl_smoke_test.py" 를 돌려 보세요. 거기서도 실패하면
     원인은 변환기 코드가 아닙니다.
   - "resource file ...\Language\/fx0.msb not found" 는 CADOE_LIBDIR<버전> 이
     언어 폴더(en-us)까지 안 가고 Language 폴더에서 끊겼다는 뜻입니다. 실행
     직전에 fx0.msb 가 실제로 있는 폴더를 찾아 바로잡고, ANSYS_LANG 도 비어
     있으면 채웁니다. 계속 문제가 되면 사용자 환경변수에
     CADOE_LIBDIR<버전> = ...\Language\en-us 를 직접 넣어 두세요.
     다만 이 오류가 떠도 MAPDL 이 gRPC 서버를 띄우는 경우가 있어, 접속 실패의
     진짜 원인이 아닐 수 있습니다.
   - 그 밖에 MAPDL 자체가 내는 오류는 ANSYS 설치/환경 문제입니다. Version 값과
     AWP_ROOT<버전> 환경변수를 보고, 같은 버전을 ANSYS Launcher 로 직접 띄워
     되는지부터 확인하세요.
"""


# PyMAPDL 기본 포트. 여기서부터 비어 있는 포트를 찾아 인스턴스마다 따로 붙인다.
MAPDL_BASE_PORT = 50052
MAPDL_PORT_SCAN = 400
# gRPC 접속 대기 시간(초). PyMAPDL 기본값(45초)은 큰 모델/느린 라이선스 서버에서 짧다.
MAPDL_START_TIMEOUT = 120
# ANSYS_LANG 이 비어 있을 때 쓸 기본 언어 코드 (Language 폴더 하위 폴더 이름).
ANSYS_DEFAULT_LANG = "en-us"
# MAPDL 이 CADOE_LIBDIR<버전> 아래에서 찾는 리소스 파일. 이 파일이 있는 폴더가
# CADOE_LIBDIR 의 올바른 값이다.
CADOE_PROBE_FILE = "fx0.msb"
# MAPDL gRPC 는 항상 이 PC 안에서만 오가므로 프록시를 타면 안 된다.
PROXY_VARS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
LOCAL_NO_PROXY = ("localhost", "127.0.0.1", "::1")
# MAPDL 이 .out 에 남기는 실제 gRPC 리슨 포트.
GRPC_LISTEN_RE = re.compile(r"Server\s+listening\s+on\s*:?\s*[\d.]+:(\d+)", re.I)

MAPDL_LAUNCH_HINT = """\
MAPDL 접속에 실패했습니다. 위에 찍힌 .out/.err 내용이 진짜 원인입니다.
  · "resource file ...\Language\/fx0.msb not found" 는 CADOE_LIBDIR<버전> 이
    언어 폴더(en-us)까지 안 가고 Language 폴더에서 끊겼다는 뜻입니다. 실행
    직전에 자동으로 바로잡지만, 그래도 나면 사용자 환경변수에
    CADOE_LIBDIR<버전> = ...\Language\en-us 를 직접 넣으세요.
    다만 이 오류가 떠도 MAPDL 이 gRPC 서버를 띄우는 경우가 있어, 접속 실패의
    진짜 원인이 아닐 수 있습니다. 위의 "MAPDL is listening on port ..." 줄을
    먼저 보세요.
  · 그 밖에 MAPDL 자체가 기동 중에 낸 오류라면 파이썬이 아니라 ANSYS 설치/환경
    문제입니다. Version 값이 실제 설치된 버전과 같은지 확인하고, 같은 버전을
    직접(ANSYS Mechanical APDL Launcher) 띄워 정상 실행되는지부터 보세요.
    환경변수 AWP_ROOT<버전> 이 맞아야 합니다.
  · 프로세스는 뜨는데 접속만 안 되면, 먼저 프록시 환경변수를 의심하세요.
    grpc 는 http_proxy/https_proxy 를 읽어 127.0.0.1 접속까지 프록시로 보냅니다.
    실행 직전에 자동으로 우회하지만(GRPC_ENABLE_HTTP_PROXY=0 + NO_PROXY),
    그래도 안 되면 방화벽/보안 프로그램이 로컬 포트를 막는 경우입니다.
  그 밖에 확인할 것:
  1) 이전 실행에서 남은 ANSYS/MAPDL 프로세스 (작업 관리자에서 모두 종료,
     또는 명령 프롬프트에서  taskkill /F /IM ANSYS.exe /T ).
  2) 라이선스: License Type 이 맞는지, Parallel jobs 만큼 여유가 있는지.
  3) Parallel jobs x Processors 가 장비 코어 수를 넘지 않는지.
  4) 경로에 한글/공백이 섞여 있지 않은지."""


# Target Files 목록에 찍히는 상태값
ST_PENDING = "Pending"
ST_RUNNING = "Running"
ST_DONE = "Done"
ST_FAILED = "Failed"
ST_CANCELLED = "Cancelled"


class _Aborted(Exception):
    """Stop 버튼으로 중단됐을 때 파이프라인이 빠져나오는 신호."""


class _Job:
    """변환할 .db 파일 하나에 대한 실행 정보."""

    __slots__ = ("db_path", "data_dir", "is_submodel", "prefix", "inp_path")

    def __init__(self, db_path, data_dir, is_submodel, inp_path, prefix=""):
        self.db_path = db_path
        self.data_dir = data_dir
        self.is_submodel = is_submodel
        # 결과 .inp 전체 경로 (일괄 모드에서는 모아두는 폴더 안)
        self.inp_path = inp_path
        # 병렬 실행 시 로그 줄 앞에 붙일 "[모델명] " 표시
        self.prefix = prefix


class ConverterApp:
    def __init__(self, root):
        # root 는 Tk/Toplevel 이거나, tool_box 런처가 넘겨준 Frame 일 수 있다.
        # 창 속성은 실제 창일 때만 설정한다 (Frame 에는 해당 메서드가 없다).
        self.root = root
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.title("ANSYS → Abaqus Converter")
            root.geometry("900x980")
            root.resizable(False, False)

        self.db_path = tk.StringVar()
        # "file" = 단일 .db, "folder" = 폴더 안의 .db 전부 일괄 변환
        self.input_mode = tk.StringVar(value="file")
        self.batch_dir = tk.StringVar()
        self.batch_recursive = tk.BooleanVar(value=False)
        # 파일명(확장자 제외) 기준 앞/뒤 필터. 비워 두면 전부 대상.
        self.name_starts = tk.StringVar()
        self.name_ends = tk.StringVar()
        # 일괄 모드에서 .inp 를 모아 둘 폴더 (선택 폴더의 바깥 경로에 자동 생성)
        self.inp_out_root = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.data_dir = tk.StringVar()
        self.node_tol = tk.StringVar(value="1e-6")
        self.init_temp = tk.StringVar(value="183.0")
        self.final_temp = tk.StringVar(value="25.0")
        # UNBLOCKED CDWRITE format expands ETBLOCK into classic ET/KEYOPT
        # cards so older HyperMesh versions can read the .cdb. Default on.
        # NOTE: the built-in CDB parser (Step 2) requires BLOCKED nblock/eblock,
        # so a full Step 2 run forces BLOCKED regardless of this flag.
        self.cdwrite_unblocked = tk.BooleanVar(value=True)
        # 정리된 모델을 clean_model.db 로 남길지. Step 2 는 .cdb 만 읽으므로
        # 보관용이며, 큰 모델에서는 저장 시간이 길어 기본은 꺼 둔다.
        self.save_clean_db = tk.BooleanVar(value=False)
        self.is_submodel = tk.BooleanVar(value=False)
        self.free_mesh = tk.BooleanVar(value=False)
        self.symmetry_options = [
            "Quarter (1/4 symmetry)",
            "Half (1/2 symmetry) - not yet supported",
            "Full model (no symmetry)",
        ]
        self.symmetry_mode = tk.StringVar(value=self.symmetry_options[0])
        self.has_orthotropic = tk.BooleanVar(value=True)
        self.ortho_mat_range = tk.StringVar(value="9990-9999")
        self.mapdl_version = tk.StringVar(value="242")
        self.nproc = tk.StringVar(value="4")
        # 동시에 돌릴 파일 개수 (1 이면 기존처럼 순차 실행)
        self.max_jobs = tk.StringVar(value="1")
        self.license_type = tk.StringVar(value="preppost")

        self._step1_log_path = None
        # 작업 스레드가 여러 개일 수 있으므로 로그는 큐에 넣고 메인 스레드에서만 그린다.
        self._log_queue = queue.Queue()
        # 작업이 끝나면 여기서 올려두고, Run 버튼은 메인 스레드에서 다시 켠다.
        self._batch_done = threading.Event()
        # 두 인스턴스가 동시에 포트를 잡으려다 충돌하지 않도록 MAPDL 기동만 직렬화한다.
        # (기동 후 무거운 작업은 그대로 병렬로 돈다.)
        self._launch_lock = threading.Lock()
        # 인스턴스마다 다른 포트를 쓰도록 스캔 시작점을 들고 다닌다.
        self._next_port = MAPDL_BASE_PORT
        # 떠 있는 인스턴스 추적 — 앱이 닫힐 때 남기지 않고 정리하기 위한 것.
        self._active_mapdl = set()
        # 우리가 띄운 MAPDL 프로세스 PID — Stop / 종료 시 확실히 죽이기 위한 것.
        self._spawned_pids = set()
        # MAPDL 기동용 환경변수 정리는 세션당 한 번만.
        self._env_prepared = False
        atexit.register(self._exit_all_mapdl)
        # Stop 버튼 신호 + 실행 중 여부
        self._stop_event = threading.Event()
        self._running = False
        # 파일별 상태 갱신도 작업 스레드에서 오므로 큐를 거쳐 메인 스레드에서 반영한다.
        self._status_queue = queue.Queue()
        self._job_status = {}
        self._file_rows = {}

        self.db_path.trace_add("write", self._on_db_path_change)
        self._build_ui()
        self._on_input_mode_change()
        for var in (self.batch_dir, self.name_starts, self.name_ends):
            var.trace_add("write", self._on_filter_change)
        self.batch_recursive.trace_add("write", self._on_filter_change)
        self.db_path.trace_add("write", self._on_filter_change)
        self.is_submodel.trace_add("write", self._on_filter_change)
        self._refresh_file_list()
        self.root.after(120, self._drain_log)

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        frm_file = tk.LabelFrame(self.root, text="File Selection", padx=10, pady=5)
        frm_file.pack(fill="x", padx=10, pady=(10, 5))

        frm_mode = tk.Frame(frm_file)
        frm_mode.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 3))
        tk.Radiobutton(
            frm_mode, text="Single file", variable=self.input_mode, value="file",
            command=self._on_input_mode_change,
        ).pack(side="left")
        tk.Radiobutton(
            frm_mode, text="Folder (batch — every .db in the folder)",
            variable=self.input_mode, value="folder",
            command=self._on_input_mode_change,
        ).pack(side="left", padx=(15, 0))

        tk.Label(frm_file, text="ANSYS .db:").grid(row=1, column=0, sticky="w")
        self.ent_db = tk.Entry(frm_file, textvariable=self.db_path, width=55)
        self.ent_db.grid(row=1, column=1, padx=5)
        self.btn_browse_db = tk.Button(frm_file, text="Browse", command=self._browse_db)
        self.btn_browse_db.grid(row=1, column=2)

        tk.Label(frm_file, text="Folder:").grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.ent_dir = tk.Entry(frm_file, textvariable=self.batch_dir, width=55)
        self.ent_dir.grid(row=2, column=1, padx=5, pady=(3, 0))
        self.btn_browse_dir = tk.Button(frm_file, text="Browse", command=self._browse_dir)
        self.btn_browse_dir.grid(row=2, column=2, pady=(3, 0))

        frm_filter = tk.Frame(frm_file)
        frm_filter.grid(row=3, column=0, columnspan=3, sticky="w")
        self.chk_recursive = tk.Checkbutton(
            frm_filter, text="Include subfolders", variable=self.batch_recursive,
        )
        self.chk_recursive.pack(side="left")
        self.lbl_starts = tk.Label(frm_filter, text="Name starts with:")
        self.lbl_starts.pack(side="left", padx=(15, 3))
        self.ent_starts = tk.Entry(frm_filter, textvariable=self.name_starts, width=16)
        self.ent_starts.pack(side="left")
        self.lbl_ends = tk.Label(frm_filter, text="ends with:")
        self.lbl_ends.pack(side="left", padx=(12, 3))
        self.ent_ends = tk.Entry(frm_filter, textvariable=self.name_ends, width=16)
        self.ent_ends.pack(side="left")
        self.lbl_filter_hint = tk.Label(
            frm_filter, text="(filename without .db, case-insensitive; blank = no filter)",
            fg="#555555",
        )
        self.lbl_filter_hint.pack(side="left", padx=(8, 0))

        self.lbl_out_root = tk.Label(frm_file, text="INP output:")
        self.lbl_out_root.grid(row=4, column=0, sticky="w", pady=(3, 0))
        self.ent_out_root = tk.Entry(frm_file, textvariable=self.inp_out_root, width=55)
        self.ent_out_root.grid(row=4, column=1, padx=5, pady=(3, 0))
        self.btn_browse_out = tk.Button(frm_file, text="Browse", command=self._browse_out_root)
        self.btn_browse_out.grid(row=4, column=2, pady=(3, 0))
        self.lbl_out_hint = tk.Label(
            frm_file,
            text="Batch mode gathers every .inp here (default: <parent of the selected folder>"
                 "/<folder>_inp). Each file is named <model>_<its folder>.inp",
            fg="#555555",
        )
        self.lbl_out_hint.grid(row=5, column=1, columnspan=2, sticky="w")

        self.chk_submodel = tk.Checkbutton(
            frm_file,
            text="Sub-model (.db is a submodel — skips tie processing, uses submodel BCs; "
                 "auto-set when filename ends with 'sub'. Batch mode decides per file.)",
            variable=self.is_submodel,
        )
        self.chk_submodel.grid(row=6, column=0, columnspan=3, sticky="w", pady=(3, 0))

        frm_set = tk.LabelFrame(self.root, text="Settings", padx=10, pady=5)
        frm_set.pack(fill="x", padx=10, pady=5)

        tk.Label(frm_set, text="Node Merge Tol:").grid(row=0, column=0, sticky="w")
        tk.Entry(frm_set, textvariable=self.node_tol, width=12).grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(frm_set, text="Initial Temp:").grid(row=0, column=2, sticky="w", padx=(20, 0))
        tk.Entry(frm_set, textvariable=self.init_temp, width=10).grid(row=0, column=3, sticky="w", padx=5)

        tk.Label(frm_set, text="Final Temp:").grid(row=0, column=4, sticky="w", padx=(20, 0))
        tk.Entry(frm_set, textvariable=self.final_temp, width=10).grid(row=0, column=5, sticky="w", padx=5)

        tk.Checkbutton(
            frm_set,
            text="CDWRITE UNBLOCKED (HyperMesh compatible; auto-disabled for full Step 2 run)",
            variable=self.cdwrite_unblocked,
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(5, 0))

        tk.Checkbutton(
            frm_set,
            text="Save cleaned model as clean_model.db (보관용 — .inp 변환에는 쓰지 않음, "
                 "큰 모델에서는 느려짐)",
            variable=self.save_clean_db,
        ).grid(row=2, column=0, columnspan=6, sticky="w")

        frm_model = tk.LabelFrame(self.root, text="Model Configuration", padx=10, pady=5)
        frm_model.pack(fill="x", padx=10, pady=5)

        tk.Checkbutton(
            frm_model,
            text="Free Mesh (tet / mixed elements) — NOT YET SUPPORTED (run disabled if checked)",
            variable=self.free_mesh,
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        tk.Label(frm_model, text="Symmetry Mode:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.symmetry_menu = tk.OptionMenu(frm_model, self.symmetry_mode, *self.symmetry_options)
        self.symmetry_menu.config(width=32)
        self.symmetry_menu.grid(row=1, column=1, columnspan=3, sticky="w", padx=5, pady=(5, 0))

        tk.Checkbutton(
            frm_model,
            text="Orthotropic (effective) material present",
            variable=self.has_orthotropic,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        tk.Label(frm_model, text="Material # range:").grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
        tk.Entry(frm_model, textvariable=self.ortho_mat_range, width=14).grid(
            row=2, column=3, sticky="w", padx=5, pady=(5, 0)
        )

        frm_mapdl = tk.LabelFrame(self.root, text="MAPDL Launch Settings", padx=10, pady=5)
        frm_mapdl.pack(fill="x", padx=10, pady=5)

        tk.Label(frm_mapdl, text="Version:").grid(row=0, column=0, sticky="w")
        tk.Entry(frm_mapdl, textvariable=self.mapdl_version, width=10).grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(frm_mapdl, text="Processors:").grid(row=0, column=2, sticky="w", padx=(15, 0))
        tk.Entry(frm_mapdl, textvariable=self.nproc, width=6).grid(row=0, column=3, sticky="w", padx=5)

        tk.Label(frm_mapdl, text="License Type:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        license_options = ["preppost", "ansys", "mech", "struct", "dyna", "enterprise"]
        tk.OptionMenu(frm_mapdl, self.license_type, *license_options).grid(
            row=1, column=1, sticky="w", padx=5, pady=(5, 0)
        )

        tk.Label(frm_mapdl, text="Parallel jobs:").grid(row=1, column=2, sticky="w", padx=(15, 0), pady=(5, 0))
        tk.Entry(frm_mapdl, textvariable=self.max_jobs, width=6).grid(
            row=1, column=3, sticky="w", padx=5, pady=(5, 0)
        )
        tk.Label(
            frm_mapdl,
            text="(files converted at the same time — each one launches its own MAPDL, "
                 "so cores/licenses used = Parallel jobs x Processors)",
            fg="#555555",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(3, 0))

        frm_run = tk.Frame(self.root, pady=5)
        frm_run.pack(fill="x", padx=10)

        step_options = ["Step 1 (MAPDL Cleanup + CDWRITE)", "Step 2 (Full - Build INP)"]
        self.run_until = tk.StringVar(value=step_options[-1])
        tk.Label(frm_run, text="Run up to:").pack(side="left", padx=(0, 5))
        self.run_upto_menu = tk.OptionMenu(frm_run, self.run_until, *step_options)
        self.run_upto_menu.config(width=28, height=1)
        self.run_upto_menu.pack(side="left", padx=(0, 15))

        self.btn_run = tk.Button(
            frm_run, text="Run", command=self._run, width=14, height=1,
            bg="#2E8B57", fg="white", activebackground="#3BA66B", activeforeground="white",
        )
        self.btn_show_step1 = tk.Button(
            frm_run, text="Show Step 1 Commands", command=self._show_step1_log, width=22, height=1,
        )
        self.btn_notes = tk.Button(
            frm_run, text="Notes / Help", command=self._show_notes, width=14, height=1,
        )
        self.btn_stop = tk.Button(
            frm_run, text="Stop", command=self._stop, width=10, height=1, state="disabled",
            bg="#B03A2E", fg="white", activebackground="#C0503E", activeforeground="white",
            disabledforeground="#DDDDDD",
        )
        self.btn_run.pack(side="right")
        self.btn_stop.pack(side="right", padx=(0, 8))
        self.btn_show_step1.pack(side="right", padx=(0, 8))
        self.btn_notes.pack(side="right", padx=(0, 8))

        frm_files = tk.LabelFrame(self.root, text="Target Files", padx=10, pady=5)
        frm_files.pack(fill="both", expand=True, padx=10, pady=5)

        tree_wrap = tk.Frame(frm_files)
        tree_wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            tree_wrap, columns=("name", "sub", "status", "out", "folder"),
            show="headings", height=5,
        )
        for col, text, width, anchor in (
            ("name", "File", 210, "w"),
            ("sub", "Sub", 40, "center"),
            ("status", "Status", 80, "center"),
            ("out", "Output .inp", 230, "w"),
            ("folder", "Source folder", 260, "w"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "folder"))
        tree_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        frm_prog = tk.Frame(frm_files)
        frm_prog.pack(fill="x", pady=(5, 0))
        self.progress = ttk.Progressbar(frm_prog, mode="determinate", maximum=1, value=0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.lbl_progress = tk.Label(frm_prog, text="No target file", width=42, anchor="w")
        self.lbl_progress.pack(side="left", padx=(10, 0))

        frm_log = tk.LabelFrame(self.root, text="Log", padx=10, pady=5)
        frm_log.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log = scrolledtext.ScrolledText(frm_log, height=8, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    # -----------------------------------------------------------------------
    # UI callbacks
    # -----------------------------------------------------------------------

    def _symmetry_key(self):
        val = self.symmetry_mode.get()
        if val.startswith("Half"):
            return "half"
        if val.startswith("Full"):
            return "full"
        return "quarter"

    def _browse_db(self):
        path = filedialog.askopenfilename(filetypes=[("ANSYS DB", "*.db"), ("All", "*.*")])
        if path:
            self.db_path.set(path)
            self.output_dir.set(os.path.dirname(path))

    def _browse_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.batch_dir.set(path)
            self.output_dir.set(path)
            self.inp_out_root.set(self._default_inp_out_root(path))

    def _browse_out_root(self):
        path = filedialog.askdirectory()
        if path:
            self.inp_out_root.set(path)

    @staticmethod
    def _default_inp_out_root(folder):
        """선택한 폴더의 바깥(상위) 경로에 '<폴더명>_inp' 를 만든다."""
        folder = os.path.abspath(folder)
        parent = os.path.dirname(folder)
        return os.path.join(parent or folder, os.path.basename(folder) + "_inp")

    def _is_batch(self):
        return self.input_mode.get() == "folder"

    def _on_input_mode_change(self, *_args):
        """Enable only the widgets that belong to the selected input mode."""
        batch = self._is_batch()
        file_state = "disabled" if batch else "normal"
        dir_state = "normal" if batch else "disabled"
        for w in (self.ent_db, self.btn_browse_db, self.chk_submodel):
            w.config(state=file_state)
        for w in (self.ent_dir, self.btn_browse_dir, self.chk_recursive,
                  self.ent_starts, self.ent_ends, self.ent_out_root, self.btn_browse_out):
            w.config(state=dir_state)
        for w in (self.lbl_starts, self.lbl_ends, self.lbl_filter_hint,
                  self.lbl_out_root, self.lbl_out_hint):
            w.config(state=dir_state)
        self._refresh_file_list()

    def _on_filter_change(self, *_args):
        self._refresh_file_list()

    def _on_db_path_change(self, *_args):
        """Auto-toggle Sub-model when the .db filename ends with 'sub' (case-insensitive)."""
        self.is_submodel.set(self._auto_submodel(self.db_path.get()))

    @staticmethod
    def _auto_submodel(db_path):
        """'sub' 로 끝나는 파일명(대소문자 무관)이면 submodel 로 본다."""
        stem = os.path.splitext(os.path.basename(db_path))[0]
        return stem.lower().endswith("sub")

    def _collect_db_files(self, folder):
        """폴더 안의 .db 파일 목록 (이름순). 중간 산출물 폴더(_data)는 건너뛴다."""
        found = []
        if self.batch_recursive.get():
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d != "_data"]
                found += [os.path.join(root, f) for f in files if f.lower().endswith(".db")]
        else:
            found = [
                os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith(".db") and os.path.isfile(os.path.join(folder, f))
            ]
        # Step 1 이 만들어 둔 중간 결과물은 입력으로 다시 잡지 않는다.
        found = [f for f in found
                 if os.path.splitext(os.path.basename(f))[0].lower() != "clean_model"]
        found = [f for f in found if self._name_matches_filter(f)]
        return sorted(found, key=lambda f: os.path.basename(f).lower())

    def _name_matches_filter(self, db_path):
        """파일명(확장자 제외) 앞/뒤 필터. 대소문자 무시, 빈 칸은 통과."""
        stem = os.path.splitext(os.path.basename(db_path))[0].lower()
        starts = self.name_starts.get().strip().lower()
        ends = self.name_ends.get().strip().lower()
        if starts and not stem.startswith(starts):
            return False
        if ends and not stem.endswith(ends):
            return False
        return True

    # -----------------------------------------------------------------------
    # Target Files 목록 / 진행 상황
    # -----------------------------------------------------------------------

    def _refresh_file_list(self, *_args):
        """현재 설정으로 무엇이 변환 대상인지 미리 보여준다 (실행 중에는 건드리지 않음)."""
        if self._running:
            return
        if self._is_batch() and not self.inp_out_root.get().strip():
            folder = self.batch_dir.get().strip()
            if folder and os.path.isdir(folder):
                self.inp_out_root.set(self._default_inp_out_root(folder))
        try:
            jobs = self._collect_jobs()
        except ValueError:
            jobs = []
        self._populate_file_list(jobs)

    def _populate_file_list(self, jobs):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._file_rows = {}
        self._job_status = {}
        for job in jobs:
            item = self.tree.insert("", "end", values=(
                os.path.basename(job.db_path),
                "Y" if job.is_submodel else "",
                ST_PENDING,
                os.path.basename(job.inp_path),
                os.path.dirname(job.db_path),
            ))
            self._file_rows[job.db_path] = item
            self._job_status[job.db_path] = ST_PENDING
        self._update_progress()

    def _set_status(self, db_path, status):
        """작업 스레드에서 호출 — 큐를 통해 메인 스레드가 반영한다."""
        self._status_queue.put((db_path, status))

    def _apply_status(self, db_path, status):
        self._job_status[db_path] = status
        item = self._file_rows.get(db_path)
        if item:
            self.tree.set(item, "status", status)
            self.tree.see(item)

    def _update_progress(self):
        total = len(self._job_status)
        if not total:
            self.progress.config(maximum=1, value=0)
            self.lbl_progress.config(text="No target file")
            return
        counts = {st: 0 for st in (ST_PENDING, ST_RUNNING, ST_DONE, ST_FAILED, ST_CANCELLED)}
        for st in self._job_status.values():
            counts[st] = counts.get(st, 0) + 1
        finished = counts[ST_DONE] + counts[ST_FAILED] + counts[ST_CANCELLED]
        self.progress.config(maximum=total, value=finished)
        text = f"{finished} / {total} finished"
        if not self._running and finished == 0:
            text = f"{total} file(s) to convert"
        extra = []
        if counts[ST_RUNNING]:
            extra.append(f"{counts[ST_RUNNING]} running")
        if counts[ST_FAILED]:
            extra.append(f"{counts[ST_FAILED]} failed")
        if counts[ST_CANCELLED]:
            extra.append(f"{counts[ST_CANCELLED]} cancelled")
        if extra:
            text += " (" + ", ".join(extra) + ")"
        self.lbl_progress.config(text=text)

    def _parse_ortho_mat_range(self):
        text = self.ortho_mat_range.get().strip()
        parts = [p.strip() for p in text.replace("~", "-").split("-") if p.strip()]
        if len(parts) != 2:
            raise ValueError(f"Material # range must be like '9990-9999'. Got: '{text}'")
        try:
            lo, hi = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"Material # range must be like '9990-9999'. Got: '{text}'")
        return (lo, hi) if lo <= hi else (hi, lo)

    def _show_step1_log(self):
        log_path = self._step1_log_path
        if not log_path or not os.path.exists(log_path):
            search_dirs = [self.data_dir.get(), self.output_dir.get()]
            for d in search_dirs:
                if not d:
                    continue
                candidate = os.path.join(d, "step1_apdl.log")
                if os.path.exists(candidate):
                    log_path = candidate
                    break
        if not log_path or not os.path.exists(log_path):
            messagebox.showinfo("Step 1 Commands", "No Step 1 APDL log found yet. Run Step 1 first.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Step 1 - MAPDL Commands ({os.path.basename(log_path)})")
        win.geometry("800x600")
        txt = scrolledtext.ScrolledText(win, wrap="none")
        txt.pack(fill="both", expand=True, padx=5, pady=5)
        try:
            with open(log_path, "r") as f:
                content = f.read()
            if not content.strip():
                content = "(log file is empty - Step 1 may still be running)"
            txt.insert("1.0", content)
        except Exception as e:
            txt.insert("1.0", f"Error reading log: {e}")
        txt.config(state="disabled")
        tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 5))

    def _show_notes(self):
        win = tk.Toplevel(self.root)
        win.title("Notes / Help")
        win.geometry("800x600")
        txt = scrolledtext.ScrolledText(win, wrap="word")
        txt.pack(fill="both", expand=True, padx=5, pady=5)
        txt.insert("1.0", NOTES_TEXT)
        txt.config(state="disabled")
        tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 5))

    def _log(self, msg):
        """어느 스레드에서 불러도 안전하도록 큐에만 넣는다."""
        self._log_queue.put(msg)

    def _drain_log(self):
        """메인 스레드에서 주기적으로 큐를 비워 Log 위젯에 그린다."""
        lines = []
        try:
            while True:
                lines.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        updates = []
        try:
            while True:
                updates.append(self._status_queue.get_nowait())
        except queue.Empty:
            pass
        try:
            if lines:
                self.log.config(state="normal")
                self.log.insert("end", "\n".join(lines) + "\n")
                self.log.see("end")
                self.log.config(state="disabled")
            for db_path, status in updates:
                self._apply_status(db_path, status)
            if updates:
                self._update_progress()
            if self._batch_done.is_set():
                self._batch_done.clear()
                self._running = False
                self.btn_run.config(state="normal")
                self.btn_stop.config(state="disabled")
                self._update_progress()
            self.root.after(120, self._drain_log)
        except tk.TclError:
            # 창이 닫혀 위젯이 사라진 경우 — 반복을 멈춘다.
            pass

    def _run(self):
        if self.free_mesh.get():
            messagebox.showwarning(
                "Not Supported",
                "Free mesh (tet / mixed element) mode is not yet implemented.\n"
                "This feature is planned for a future update. Uncheck it to run with hex mesh.",
            )
            return
        if self._symmetry_key() == "half":
            messagebox.showwarning(
                "Not Supported",
                "Half (1/2) symmetry mode is not yet implemented.\n"
                "This feature is planned for a future update.",
            )
            return
        try:
            jobs = self._collect_jobs()
            opts = self._collect_options()
        except ValueError as e:
            messagebox.showwarning("Warning", str(e))
            return

        for job in jobs:
            os.makedirs(job.data_dir, exist_ok=True)
            os.makedirs(os.path.dirname(job.inp_path), exist_ok=True)

        self._populate_file_list(jobs)
        self._stop_event.clear()
        self._running = True
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._update_progress()
        threading.Thread(target=self._run_batch, args=(jobs, opts), daemon=True).start()

    def _stop(self):
        """실행 중인 작업에 중단을 요청한다."""
        if not self._running:
            return
        self._stop_event.set()
        self.btn_stop.config(state="disabled")
        self._log(
            "\n*** Stop requested — queued files are cancelled and running MAPDL "
            "instances are being shut down. ***"
        )
        threading.Thread(target=self._force_stop_mapdl, daemon=True).start()

    def _collect_jobs(self):
        """실행 모드에 맞춰 변환할 파일 목록(_Job)을 만든다."""
        if self._is_batch():
            folder = self.batch_dir.get().strip()
            if not folder:
                raise ValueError("Select a folder first.")
            if not os.path.isdir(folder):
                raise ValueError(f"Folder not found: {folder}")
            db_files = self._collect_db_files(folder)
            if not db_files:
                raise ValueError(f"No .db file found in: {folder}")
            out_root = self.inp_out_root.get().strip() or self._default_inp_out_root(folder)
            out_root = os.path.abspath(out_root)
            self.output_dir.set(folder)
            self.data_dir.set(os.path.join(folder, "_data"))

            jobs = []
            used_names = set()
            for f in db_files:
                f = os.path.abspath(f)
                stem = os.path.splitext(os.path.basename(f))[0]
                inp_name = self._unique_inp_name(stem, os.path.dirname(f), used_names)
                jobs.append(_Job(
                    db_path=f,
                    # 파일끼리 중간 산출물이 섞이지 않도록 모델별 폴더를 쓴다.
                    data_dir=os.path.join(os.path.dirname(f), "_data",
                                          self._safe_dir_name(stem)),
                    is_submodel=self._auto_submodel(f),
                    inp_path=os.path.join(out_root, inp_name),
                    prefix=f"[{stem}] ",
                ))
            return jobs

        db_path = self.db_path.get().strip()
        if not db_path:
            raise ValueError("Select an ANSYS .db file first.")
        if not os.path.isfile(db_path):
            raise ValueError(f"File not found: {db_path}")
        db_path = os.path.abspath(db_path)
        out_dir = os.path.dirname(db_path)
        data_dir = os.path.join(out_dir, "_data")
        self.output_dir.set(out_dir)
        self.data_dir.set(data_dir)
        return [_Job(
            db_path=db_path,
            data_dir=data_dir,
            is_submodel=self.is_submodel.get(),
            inp_path=os.path.join(out_dir, os.path.splitext(os.path.basename(db_path))[0] + ".inp"),
            prefix="",
        )]

    @staticmethod
    def _safe_dir_name(stem):
        """MAPDL 작업 폴더 이름으로 쓸 수 있게 ASCII 로 정리한다.

        MAPDL 은 작업 경로에 한글/공백/특수문자가 있으면 기동에 실패할 수 있어
        모델명을 그대로 폴더명으로 쓰지 않는다. 정리하다 이름이 겹칠 수 있으므로
        바뀐 경우에는 원래 이름의 해시를 붙여 구분한다.
        """
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem).strip("._-")[:40]
        if not safe:
            safe = "model"
        if safe != stem:
            import hashlib
            safe = f"{safe}_{hashlib.md5(stem.encode('utf-8')).hexdigest()[:6]}"
        return safe

    @staticmethod
    def _unique_inp_name(stem, src_folder, used_names):
        """<모델명>_<들어있던 폴더명>.inp — 한 폴더에 모으므로 이름이 겹치면 번호를 붙인다."""
        folder_name = os.path.basename(src_folder.rstrip(os.sep)) or "root"
        base = f"{stem}_{folder_name}"
        name = f"{base}.inp"
        n = 2
        while name.lower() in used_names:
            name = f"{base}_{n}.inp"
            n += 1
        used_names.add(name.lower())
        return name

    def _collect_options(self):
        """작업 스레드에서 tk 변수를 읽지 않도록 설정값을 미리 스냅샷한다."""
        version_str = self.mapdl_version.get().strip()
        if version_str:
            try:
                version = int(version_str)
            except ValueError:
                raise ValueError(
                    f"MAPDL Version must be an integer (e.g. 192, 211, 242). Got: '{version_str}'"
                )
        else:
            version = 242

        try:
            node_tol = float(self.node_tol.get())
        except ValueError:
            raise ValueError(f"Node Merge Tol must be numeric. Got: '{self.node_tol.get()}'")
        try:
            init_temp = float(self.init_temp.get())
            final_temp = float(self.final_temp.get())
        except ValueError:
            raise ValueError(
                "Initial/Final Temp must be numeric. "
                f"Got init='{self.init_temp.get()}' final='{self.final_temp.get()}'"
            )
        try:
            nproc = int(self.nproc.get().strip()) if self.nproc.get().strip() else 4
        except ValueError:
            raise ValueError(f"Processors must be an integer. Got: '{self.nproc.get()}'")
        try:
            max_jobs = int(self.max_jobs.get().strip()) if self.max_jobs.get().strip() else 1
        except ValueError:
            raise ValueError(f"Parallel jobs must be an integer. Got: '{self.max_jobs.get()}'")
        if max_jobs < 1:
            raise ValueError("Parallel jobs must be 1 or more.")

        return {
            "node_tol": node_tol,
            "init_temp": init_temp,
            "final_temp": final_temp,
            "cdwrite_unblocked": bool(self.cdwrite_unblocked.get()),
            "save_clean_db": bool(self.save_clean_db.get()),
            "symmetry_mode": self._symmetry_key(),
            "has_orthotropic": bool(self.has_orthotropic.get()),
            "ortho_mat_range": self._parse_ortho_mat_range(),
            "version": version,
            "nproc": nproc,
            "license_type": self.license_type.get().strip() or "preppost",
            "max_jobs": max_jobs,
            "stop_after_step1": self.run_until.get().startswith("Step 1"),
        }

    # -----------------------------------------------------------------------
    # Pipeline
    # -----------------------------------------------------------------------

    def _run_batch(self, jobs, opts):
        """jobs 를 순차 또는 병렬로 돌리고 마지막에 요약을 남긴다."""
        try:
            workers = min(opts["max_jobs"], len(jobs))
            if len(jobs) > 1:
                self._log(f"=== Batch: {len(jobs)} file(s), {workers} at a time ===")
                self._log(f"    INP output folder: {os.path.dirname(jobs[0].inp_path)}")
                for job in jobs:
                    self._log(
                        f"    - {os.path.basename(job.db_path)}"
                        f"{' (submodel)' if job.is_submodel else ''}"
                        f"  ->  {os.path.basename(job.inp_path)}"
                    )
            if workers <= 1:
                results = [self._run_pipeline(job, opts) for job in jobs]
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(lambda j: self._run_pipeline(j, opts), jobs))

            if len(jobs) > 1:
                done = [r for r in results if r[1] == ST_DONE]
                failed = [r for r in results if r[1] == ST_FAILED]
                cancelled = [r for r in results if r[1] == ST_CANCELLED]
                self._log(
                    f"\n=== Batch finished: {len(done)} done, {len(failed)} failed, "
                    f"{len(cancelled)} cancelled ==="
                )
                for job, _st, err in failed:
                    self._log(f"  FAILED {os.path.basename(job.db_path)}: {err}")
                for job, _st, _err in cancelled:
                    self._log(f"  CANCELLED {os.path.basename(job.db_path)}")
        finally:
            self._batch_done.set()

    def _raise_if_stopped(self):
        if self._stop_event.is_set():
            raise _Aborted()

    def _run_pipeline(self, job, opts):
        """파일 하나를 변환한다. 예외는 삼켜서 (job, ok, err) 로 돌려준다."""
        def log(msg):
            if not job.prefix:
                self._log(msg)
                return
            # 빈 줄(앞뒤 여백)에는 붙이지 않고 내용이 있는 줄에만 [모델명] 을 단다.
            self._log("\n".join(
                job.prefix + line if line.strip() else line
                for line in str(msg).split("\n")
            ))

        if self._stop_event.is_set():
            self._set_status(job.db_path, ST_CANCELLED)
            return (job, ST_CANCELLED, None)

        self._set_status(job.db_path, ST_RUNNING)
        try:
            log(f"\n=== Converting: {job.db_path} ===")
            self._step1_cleanup(job, opts, log)
            if opts["stop_after_step1"]:
                log("=== Stopped after Step 1 ===")
                self._set_status(job.db_path, ST_DONE)
                return (job, ST_DONE, None)
            self._raise_if_stopped()
            cdb_path = os.path.join(job.data_dir, "clean_model.cdb")
            self._step2_build_inp(job, opts, cdb_path, log)
            log("=== All steps completed ===")
            self._set_status(job.db_path, ST_DONE)
            return (job, ST_DONE, None)
        except _Aborted:
            log("=== Cancelled by Stop ===")
            self._set_status(job.db_path, ST_CANCELLED)
            return (job, ST_CANCELLED, None)
        except Exception as e:
            if self._stop_event.is_set():
                # Stop 으로 MAPDL 을 내리면서 끊긴 호출이다 — 실패가 아니라 취소.
                log(f"=== Cancelled by Stop ({type(e).__name__}) ===")
                self._set_status(job.db_path, ST_CANCELLED)
                return (job, ST_CANCELLED, None)
            log(f"[ERROR] {e}")
            self._set_status(job.db_path, ST_FAILED)
            return (job, ST_FAILED, e)

    @staticmethod
    def _mapdl_pid(mapdl):
        """PyMAPDL 버전마다 프로세스를 들고 있는 속성 이름이 달라 차례로 찾는다."""
        for attr in ("_mapdl_process", "process", "_process", "_subprocess"):
            proc = getattr(mapdl, attr, None)
            pid = getattr(proc, "pid", None)
            if pid:
                return pid
        return None

    @staticmethod
    def _kill_pid(pid):
        """자식까지 강제 종료. 우리가 띄운 PID 에만 쓴다."""
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    def _kill_leftover_processes(self, log=None):
        """이미 exit 를 시도한 뒤에도 남아 있는, 우리가 띄운 프로세스를 정리한다."""
        for pid in list(self._spawned_pids):
            self._kill_pid(pid)
            self._spawned_pids.discard(pid)
            if log:
                log(f"  Killed leftover MAPDL process (pid {pid}).")

    def _shutdown_mapdl(self, mapdl, log=None, kill_first=False):
        """인스턴스 하나를 닫고, 그래도 살아 있으면 PID 로 강제 종료한다.

        ``kill_first`` 는 Stop 용이다. 먼저 프로세스를 죽여 두면 exit() 이
        응답 없는 gRPC 채널을 붙잡고 늘어지지 않고 바로 끝난다.
        """
        pid = self._mapdl_pid(mapdl)
        if kill_first and pid:
            self._kill_pid(pid)
        try:
            mapdl.exit()
        except Exception:
            try:
                mapdl.exit(force=True)
            except Exception as e:
                if log:
                    log(f"MAPDL exit warning: {e}")
        self._active_mapdl.discard(mapdl)
        if pid:
            self._kill_pid(pid)
            self._spawned_pids.discard(pid)

    def _force_stop_mapdl(self):
        """Stop 을 눌렀을 때 실제로 MAPDL 프로세스를 내린다 (별도 스레드).

        작업 스레드는 gRPC 호출 안에서 대기 중일 수 있어 단계 경계만 기다리면
        한참 안 죽는다. 그래서 여기서 직접 내리고, 진행 중이던 호출은 오류로
        끊기며 해당 파일은 Cancelled 로 처리된다.
        """
        for mapdl in list(self._active_mapdl):
            self._shutdown_mapdl(mapdl, kill_first=True)
        self._kill_leftover_processes()
        self._log("*** MAPDL instances shut down. ***")

    def _exit_all_mapdl(self):
        """앱 종료 시 아직 떠 있는 MAPDL 을 닫는다.

        작업 스레드는 daemon 이라 종료 시 finally 가 돌지 않을 수 있고, 그렇게
        남은 인스턴스가 포트를 물고 있으면 다음 실행이 기동조차 못 한다.
        """
        for mapdl in list(self._active_mapdl):
            self._shutdown_mapdl(mapdl)
        self._active_mapdl.clear()
        self._kill_leftover_processes()

    @staticmethod
    def _language_dirs(version):
        """설치된 ANSYS 에서 Language 폴더 후보를 모은다."""
        root = os.environ.get(f"AWP_ROOT{version}") or os.environ.get("AWP_ROOT")
        if not root or not os.path.isdir(root):
            return []
        return [d for d in (
            os.path.join(root, "commonfiles", "Language"),
            os.path.join(root, "ansys", "gui", "Language"),
            os.path.join(root, "ansys", "Language"),
        ) if os.path.isdir(d)]

    @staticmethod
    def _lang_subdirs(lang_dir):
        """Language 폴더의 하위 언어 폴더를 en-us 우선으로 정렬해 돌려준다."""
        try:
            subs = sorted(d for d in os.listdir(lang_dir)
                          if os.path.isdir(os.path.join(lang_dir, d)))
        except OSError:
            return []
        subs.sort(key=lambda d: (d.lower() != ANSYS_DEFAULT_LANG, d.lower()))
        return subs

    @classmethod
    def _find_cadoe_libdir(cls, version, current):
        """fx0.msb 가 실제로 들어 있는 폴더를 찾는다.

        CADOE_LIBDIR<버전> 이 Language 폴더까지만 가리키고 언어 폴더(en-us)가
        빠져 있는 경우가 있어, 우선 그 아래를 먼저 본다.
        """
        bases = []
        if current and os.path.isdir(current):
            bases.append(current)
        bases += cls._language_dirs(version)
        for base in bases:
            if os.path.isfile(os.path.join(base, CADOE_PROBE_FILE)):
                return base
            for sub in cls._lang_subdirs(base):
                cand = os.path.join(base, sub)
                if os.path.isfile(os.path.join(cand, CADOE_PROBE_FILE)):
                    return cand
        return None

    @classmethod
    def _find_ansys_lang(cls, version):
        """설치된 ANSYS 의 Language 폴더에서 쓸 언어 코드를 찾는다."""
        for lang_dir in cls._language_dirs(version):
            subs = cls._lang_subdirs(lang_dir)
            if subs:
                return subs[0]
        return None

    def _ensure_ansys_lang(self, opts, log):
        """ANSYS_LANG 이 비어 있으면 채워 준다 (_launch_lock 안에서 호출).

        MAPDL 은 리소스 경로를 "...\Language\<ANSYS_LANG>/fx0.msb" 로 조립한다.
        ANSYS_LANG 이 없으면 가운데가 비어 "...\Language\/fx0.msb" 를 찾다가
        'resource file ... not found' 로 기동에 실패한다. ANSYS Launcher 로 띄울
        때는 런처가 이 값을 넣어 주지만, PyMAPDL 이 실행 파일을 직접 띄우면
        파이썬 프로세스의 환경을 그대로 물려줄 뿐이라 비어 있을 수 있다.
        자식 프로세스가 물려받도록 os.environ 에 넣는다.
        """
        if not os.environ.get("ANSYS_LANG", "").strip():
            lang = self._find_ansys_lang(opts["version"]) or ANSYS_DEFAULT_LANG
            os.environ["ANSYS_LANG"] = lang
            log(f"  ANSYS_LANG was not set — using '{lang}' for this session.")
        self._ensure_cadoe_libdir(opts, log)

    @staticmethod
    def _bypass_proxy_for_local_grpc(log):
        """로컬 gRPC 접속이 회사 프록시로 새지 않게 막는다.

        grpc 는 http_proxy/https_proxy 환경변수를 읽어 127.0.0.1 접속까지
        프록시로 보낸다(requests 와 달리 루프백을 자동으로 빼 주지 않는다).
        프록시가 내부 접속을 막으면 MAPDL 이 정상적으로 리스닝 중인데도
        "unable to connect to MAPDL grpc instance" 로 끝난다.
        """
        found = [v for v in PROXY_VARS if os.environ.get(v, "").strip()]
        if not found:
            return
        if not os.environ.get("GRPC_ENABLE_HTTP_PROXY", "").strip():
            os.environ["GRPC_ENABLE_HTTP_PROXY"] = "0"
        for var in ("NO_PROXY", "no_proxy"):
            hosts = [h.strip() for h in os.environ.get(var, "").split(",") if h.strip()]
            hosts += [h for h in LOCAL_NO_PROXY if h not in hosts]
            os.environ[var] = ",".join(hosts)
        log(
            f"  Proxy env detected ({', '.join(found)}) — bypassing it for the "
            f"local MAPDL gRPC connection (GRPC_ENABLE_HTTP_PROXY=0, "
            f"NO_PROXY+={','.join(LOCAL_NO_PROXY)})."
        )

    def _prepare_mapdl_env(self, opts, log):
        """MAPDL 기동에 필요한 환경변수를 한 번만 정리한다.

        grpc 는 채널을 만들 때 프록시 환경변수를 읽으므로, ansys.mapdl.core
        (=grpc) 를 import 하기 전에 불러야 한다.
        """
        if self._env_prepared:
            return
        self._env_prepared = True
        self._bypass_proxy_for_local_grpc(log)
        self._ensure_ansys_lang(opts, log)

    def _ensure_cadoe_libdir(self, opts, log):
        """CADOE_LIBDIR<버전> 이 fx0.msb 가 있는 폴더를 가리키게 맞춘다.

        MAPDL 은 리소스를 CADOE_LIBDIR<버전> + "/fx0.msb" 로 찾는다. 이 값이
        언어 폴더(en-us)까지 안 가고 Language 폴더에서 끊기면
        "...\Language\/fx0.msb not found" 가 뜬다.
        """
        var = f"CADOE_LIBDIR{opts['version']}"
        current = os.environ.get(var, "").strip().rstrip("\\/")
        if current and os.path.isfile(os.path.join(current, CADOE_PROBE_FILE)):
            return
        target = self._find_cadoe_libdir(opts["version"], current)
        if not target:
            if current:
                log(f"  ({var}={current} has no {CADOE_PROBE_FILE}, and no "
                    f"replacement was found — leaving it as is)")
            return
        os.environ[var] = target
        log(f"  {var} -> {target}  (was {current or 'unset'})")

    @staticmethod
    def _port_is_free(port):
        """아무도 듣고 있지 않으면 비어 있는 포트로 본다."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
            sk.settimeout(0.3)
            try:
                return sk.connect_ex(("127.0.0.1", port)) != 0
            except OSError:
                return False

    def _pick_free_port(self, log):
        """MAPDL 인스턴스마다 다른 포트를 준다 (_launch_lock 안에서만 호출).

        예전에 죽지 않고 남은 MAPDL 이 기본 포트(50052)를 물고 있으면 기동이
        통째로 막히므로, 쓰고 있는 포트는 건너뛴다. 빈 포트를 못 찾으면 None 을
        돌려주고, 호출한 쪽은 포트를 넘기지 않아 PyMAPDL 기본 동작에 맡긴다
        (포트 탐색이 실패했다고 실행 자체를 막지는 않는다).
        """
        skipped = []
        port = self._next_port
        limit = MAPDL_BASE_PORT + MAPDL_PORT_SCAN
        while port < limit:
            if self._port_is_free(port):
                if skipped:
                    log(
                        f"  (port {', '.join(str(p) for p in skipped)} in use — "
                        f"another MAPDL instance may still be running)"
                    )
                self._next_port = port + 1
                return port
            skipped.append(port)
            port += 1
        self._next_port = MAPDL_BASE_PORT
        log(
            f"  (no free port found in {MAPDL_BASE_PORT}-{limit - 1} — "
            f"letting PyMAPDL choose)"
        )
        return None

    @staticmethod
    def _clear_stale_run_files(out_dir, log):
        """이전 실행이 남긴 lock/.out/.err 를 지운다.

        .out/.err 를 지우는 이유는 실패 원인과 실제 리슨 포트를 이번 실행의
        출력에서만 읽기 위해서다. 지난 실행 파일이 섞이면 엉뚱한 포트를 읽는다.
        """
        removed_locks = 0
        for name in os.listdir(out_dir):
            low = name.lower()
            if not low.endswith((".lock", ".out", ".err")):
                continue
            try:
                os.remove(os.path.join(out_dir, name))
                if low.endswith(".lock"):
                    removed_locks += 1
            except OSError:
                pass
        if removed_locks:
            log(f"  Removed {removed_locks} stale lock file(s).")

    @staticmethod
    def _grpc_listen_port(out_dir):
        """MAPDL 이 .out 에 남긴 실제 gRPC 리슨 포트를 읽는다."""
        found = None
        try:
            names = sorted(os.listdir(out_dir))
        except OSError:
            return None
        for name in names:
            if not name.lower().endswith(".out"):
                continue
            try:
                with open(os.path.join(out_dir, name), "r", errors="replace") as f:
                    for m in GRPC_LISTEN_RE.finditer(f.read()):
                        found = int(m.group(1))
            except OSError:
                continue
        return found

    def _wait_for_port(self, port, timeout=30.0):
        """해당 포트가 접속을 받기 시작할 때까지 기다린다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._port_is_free(port):
                return True
            if self._stop_event.wait(0.5):
                return False
        return not self._port_is_free(port)

    @staticmethod
    def _pid_on_port(port):
        """해당 포트를 LISTENING 중인 프로세스의 PID (Windows 전용)."""
        if os.name != "nt":
            return None
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except Exception:
            return None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" \
                    and parts[1].endswith(f":{port}"):
                try:
                    return int(parts[4])
                except ValueError:
                    return None
        return None

    def _attach_to_running(self, launch_mapdl, port, log):
        """이미 떠 있는 MAPDL 에 붙는다.

        MAPDL 이 우리가 준 포트가 아닌 다른 포트에 붙는 경우가 있는데, 그러면
        PyMAPDL 은 원래 포트에서 기다리다 실패한다. 프로세스는 멀쩡히 살아
        있으므로 실제 포트로 새로 접속해 그대로 쓴다.
        """
        if not self._wait_for_port(port):
            return None
        log(f"  Attaching to the MAPDL already listening on port {port} ...")
        try:
            mapdl = launch_mapdl(start_instance=False, ip="127.0.0.1", port=port)
        except Exception as e:
            log(f"  Attach failed: {type(e).__name__}: {e}")
            return None
        log(f"  Attached to MAPDL on port {port}.")
        pid = self._pid_on_port(port)
        if pid:
            self._spawned_pids.add(pid)
            log(f"  MAPDL process pid {pid}")
        return mapdl

    def _report_port_mismatch(self, out_dir, wanted_port, log):
        """MAPDL 이 다른 포트에 붙었으면 그게 접속 실패의 원인이다."""
        actual = self._grpc_listen_port(out_dir)
        if actual is None:
            return
        if wanted_port and actual != wanted_port:
            log(
                f"  >>> MAPDL is listening on port {actual}, but we connected to "
                f"{wanted_port}. Port {wanted_port} was taken by something else, so "
                f"MAPDL moved. Kill the leftover MAPDL holding {wanted_port} "
                f"(netstat -ano | findstr {wanted_port}) and run again."
            )
        else:
            log(
                f"  (MAPDL did start its gRPC server on port {actual} — the "
                f"connection itself was blocked. Check firewall/security software.)"
            )

    @staticmethod
    def _log_mapdl_startup_files(out_dir, log, max_lines=20):
        """기동 실패 원인은 PyMAPDL 메시지가 아니라 MAPDL 이 남긴 파일에 있다."""
        for name in sorted(os.listdir(out_dir)):
            if not name.lower().endswith((".err", ".out")):
                continue
            path = os.path.join(out_dir, name)
            try:
                with open(path, "r", errors="replace") as f:
                    tail = [ln.rstrip() for ln in f.read().splitlines() if ln.strip()]
            except OSError:
                continue
            if not tail:
                continue
            log(f"  --- {name} (last {min(len(tail), max_lines)} line(s)) ---")
            for ln in tail[-max_lines:]:
                log(f"    {ln}")

    @staticmethod
    def _base_launch_kwargs(out_dir, opts):
        """단일 파일 실행에서 예전부터 쓰던 인자 그대로. 여기에 손대지 말 것."""
        return dict(
            run_location=out_dir,
            override=True,
            version=opts["version"],
            nproc=opts["nproc"],
            license_type=opts["license_type"],
            additional_switches="-smp",
        )

    def _launch_kwargs_for(self, out_dir, opts, attempt, log):
        """attempt 번째 시도에 쓸 launch_mapdl 인자.

        포트는 시도할 때마다 새로 고른다 (앞선 시도가 남긴 인스턴스가 포트를
        물고 있을 수 있으므로 미리 정해 두면 안 된다). 빈 포트를 못 찾으면
        인자를 빼고 PyMAPDL 기본 동작에 맡긴다.
        """
        kwargs = self._base_launch_kwargs(out_dir, opts)
        port = self._pick_free_port(log)
        if port:
            kwargs["port"] = port
        if attempt > 1:
            kwargs["start_timeout"] = MAPDL_START_TIMEOUT
        return kwargs

    @staticmethod
    def _invoke_launch_mapdl(launch_mapdl, kwargs):
        try:
            return launch_mapdl(**kwargs)
        except TypeError:
            # 설치된 ansys-mapdl-core 가 모르는 인자가 있으면 그 인자를 빼고 한 번 더.
            trimmed = {k: v for k, v in kwargs.items()
                       if k not in ("start_timeout", "port")}
            if trimmed == kwargs:
                raise
            return launch_mapdl(**trimmed)

    def _call_launch_mapdl(self, launch_mapdl, kwargs, log):
        """기동 호출은 별도 스레드에 맡기고, Stop 이면 기다리지 않고 나온다.

        라이선스가 없거나 서버가 느리면 PyMAPDL 이 start_timeout(최대 120초)
        동안 붙잡고 있어서 Stop 을 눌러도 그때까지 아무 반응이 없다. 기다리는
        쪽만 먼저 포기하고, 뒤늦게 떠 버린 인스턴스는 뒷정리 스레드가 닫는다.
        """
        result = {}

        def _worker():
            try:
                result["mapdl"] = self._invoke_launch_mapdl(launch_mapdl, kwargs)
            except BaseException as e:  # noqa: BLE001 - 호출한 쪽에서 그대로 다시 올린다
                result["error"] = e

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        while thread.is_alive():
            if self._stop_event.wait(0.2):
                log("  Stop requested — abandoning the MAPDL launch.")
                threading.Thread(
                    target=self._discard_launch,
                    args=(thread, result, kwargs.get("port")),
                    daemon=True,
                ).start()
                raise _Aborted()
        if "error" in result:
            raise result["error"]
        return result["mapdl"]

    def _discard_launch(self, thread, result, port):
        """Stop 으로 버린 기동이 뒤늦게 성공해도 프로세스를 남기지 않는다."""
        thread.join(timeout=MAPDL_START_TIMEOUT + 60)
        mapdl = result.get("mapdl")
        if mapdl is not None:
            self._shutdown_mapdl(mapdl, kill_first=True)
        if port:
            pid = self._pid_on_port(port)
            if pid:
                self._kill_pid(pid)
        self._kill_leftover_processes()

    def _launch_mapdl(self, launch_mapdl, out_dir, opts, log):
        """최대 2번 시도하고, 실패하면 원인을 로그에 남긴다."""
        last_err = None
        total = 2
        for attempt in range(1, total + 1):
            self._raise_if_stopped()
            # 기동만 직렬화한다 — 두 인스턴스가 같은 포트를 잡는 것을 막는다.
            with self._launch_lock:
                self._raise_if_stopped()
                self._prepare_mapdl_env(opts, log)
                self._clear_stale_run_files(out_dir, log)
                kwargs = self._launch_kwargs_for(out_dir, opts, attempt, log)
                shown = ", ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items())
                                  if k != "run_location")
                log(f"Launching MAPDL (attempt {attempt}/{total}): {shown}")
                try:
                    mapdl = self._call_launch_mapdl(launch_mapdl, kwargs, log)
                    return self._track_instance(mapdl, log)
                except _Aborted:
                    raise
                except Exception as e:
                    last_err = e
                    log(f"  MAPDL launch failed: {type(e).__name__}: {e}")
                    self._report_port_mismatch(out_dir, kwargs.get("port"), log)
                    # 프로세스는 떠 있는데 포트만 어긋난 경우가 있다. 그러면
                    # 죽이지 말고 MAPDL 이 실제로 연 포트로 붙어서 그대로 쓴다.
                    actual = self._grpc_listen_port(out_dir)
                    if actual and actual != kwargs.get("port"):
                        attached = self._attach_to_running(launch_mapdl, actual, log)
                        if attached is not None:
                            return self._track_instance(attached, log)
                    self._log_mapdl_startup_files(out_dir, log)
                    # 반쯤 뜬 인스턴스가 남아 포트를 물지 않도록 정리한다.
                    if actual:
                        pid = self._pid_on_port(actual)
                        if pid:
                            self._spawned_pids.add(pid)
                    self._kill_leftover_processes(log)
            if attempt < total:
                log("  Retrying in 3 s ...")
                if self._stop_event.wait(3):
                    raise _Aborted()
        raise RuntimeError(f"{type(last_err).__name__}: {last_err}\n{MAPDL_LAUNCH_HINT}")

    def _track_instance(self, mapdl, log):
        """기동/접속에 성공한 인스턴스를 추적 목록에 넣는다."""
        self._active_mapdl.add(mapdl)
        pid = self._mapdl_pid(mapdl)
        if pid:
            self._spawned_pids.add(pid)
            log(f"  MAPDL process pid {pid}")
        return mapdl

    def _step1_cleanup(self, job, opts, log):
        """PyMAPDL: cleanup model and CDWRITE."""
        log("=== Step 1: PyMAPDL cleanup + CDWRITE ===")

        # grpc 는 import 이후 채널 생성 시점에 프록시 환경변수를 읽으므로,
        # ansys.mapdl.core(=grpc) 를 불러오기 전에 환경을 먼저 정리한다.
        with self._launch_lock:
            self._prepare_mapdl_env(opts, log)

        from ansys.mapdl.core import launch_mapdl

        out_dir = job.data_dir
        os.makedirs(out_dir, exist_ok=True)
        self._raise_if_stopped()

        mapdl = self._launch_mapdl(launch_mapdl, out_dir, opts, log)
        # 여기서부터는 어떤 경로로 빠져나가든 인스턴스를 반드시 닫는다.
        # (안 닫고 새면 다음 실행이 포트를 못 잡아 기동 자체가 막힌다.)
        try:
            log(f"MAPDL launched (v{mapdl.version})")

            step1_log_path = os.path.join(out_dir, "step1_apdl.log")
            self._step1_log_path = step1_log_path
            try:
                mapdl.open_apdl_log(step1_log_path, mode="w")
                log(f"APDL command log: {step1_log_path}")
            except Exception as e:
                log(f"  (APDL log not started: {e})")

            db_src = job.db_path
            db_dst = os.path.join(out_dir, os.path.basename(db_src))
            if os.path.normpath(db_src) != os.path.normpath(db_dst):
                shutil.copy2(db_src, db_dst)
                log(f"Copied .db to run_location: {db_dst}")
            db_name = os.path.splitext(os.path.basename(db_src))[0]
            mapdl.resume(db_name, "db")
            log(f"Resumed: {db_name}")

            mapdl.prep7()

            log("Merging duplicate nodes...")
            mapdl.nummrg("NODE", opts["node_tol"])
            self._raise_if_stopped()

            log("Processing tie (CE) conditions and loads...")
            mapdl_ops.handle_ties_and_loads(mapdl, log, is_submodel=job.is_submodel)
            self._raise_if_stopped()

            log("Removing unused material properties...")
            mapdl_ops.remove_unused_mats(mapdl, log)
            self._raise_if_stopped()

            mapdl.allsel("ALL")

            if opts["save_clean_db"]:
                db_name = "clean_model"
                log(f"Saving cleaned model as {db_name}.db ...")
                mapdl.save(db_name, "db")
                log(f"{db_name}.db saved.")
            else:
                log("Skipping clean_model.db save (option off).")

            cdb_name = "clean_model"
            is_full_run = not opts["stop_after_step1"]
            user_wants_unblocked = opts["cdwrite_unblocked"]
            use_unblocked = user_wants_unblocked and not is_full_run
            if user_wants_unblocked and is_full_run:
                log(
                    "  (UNBLOCKED requested, but full Step 2 run requires "
                    "BLOCKED for the CDB parser — overriding.)"
                )
            fmat = "UNBLOCKED" if use_unblocked else ""
            log(
                f"Writing {cdb_name}.cdb "
                f"({'UNBLOCKED' if use_unblocked else 'BLOCKED'} format) ..."
            )
            mapdl.cdwrite("DB", cdb_name, "cdb", fmat=fmat)
            log("CDWRITE complete.")

            if not use_unblocked:
                cdb_path = os.path.join(out_dir, f"{cdb_name}.cdb")
                expanded = cdb_utils.expand_etblock(cdb_path)
                if expanded:
                    log(f"  Expanded ETBLOCK -> {expanded} ET/KEYOPT card(s).")
                rewritten = cdb_utils.rewrite_mp_mpdata_to_classic(cdb_path)
                if rewritten:
                    log(
                        f"  Rewrote {rewritten} MP/MPDATA line(s) to "
                        f"classic format (abaqus fromansys compatible)."
                    )

            self._export_step1_metadata(mapdl, job, opts, log)

        finally:
            self._shutdown_mapdl(mapdl, log)
            log("MAPDL closed.")

    def _export_step1_metadata(self, mapdl, job, opts, log):
        """Save nset/material metadata from MAPDL to text files."""
        nset_path = os.path.join(job.data_dir, "step1_nsets.txt")
        mplist_path = os.path.join(job.data_dir, "step1_mplist.txt")

        nset_data = mapdl_ops.collect_nset_data(
            mapdl, log,
            is_submodel=job.is_submodel,
            symmetry_mode=opts["symmetry_mode"],
        )
        with open(nset_path, "w") as f:
            for name, ids in nset_data.items():
                f.write(f"[{name}]\n")
                for i in range(0, len(ids), 16):
                    f.write(", ".join(str(v) for v in ids[i:i + 16]) + "\n")
                f.write("\n")
        log(f"Saved nset metadata: {nset_path}")

        mapdl_ops.dump_mapdl_mplist(mapdl, mplist_path)
        log(f"Saved material metadata: {mplist_path}")

        if job.is_submodel:
            init_stress = mapdl_ops.get_initial_stress(mapdl, log)
            # 이전 실행에서 남은 값을 그대로 쓰지 않도록 비어 있어도 덮어쓴다.
            inistate_path = os.path.join(job.data_dir, "step1_inistate.txt")
            with open(inistate_path, "w") as f:
                for mid in sorted(init_stress):
                    f.write(f"[{mid}]\n")
                    f.write(", ".join(str(v) for v in init_stress[mid]) + "\n\n")
            if init_stress:
                log(f"Saved initial stress metadata: {inistate_path}")

    def _step2_build_inp(self, job, opts, cdb_path, log):
        """CDB 직접 파싱 → Abaqus INP 템플릿 생성."""
        log("\n=== Step 2: direct text INP build (no fromansys) ===")

        data_dir = job.data_dir
        inp_path = job.inp_path
        os.makedirs(os.path.dirname(inp_path), exist_ok=True)

        init_temp = opts["init_temp"]
        final_temp = opts["final_temp"]
        ortho_mat_range = opts["ortho_mat_range"]

        nodes = cdb_utils.parse_cdb_nodes(cdb_path)
        elems_by_mat = cdb_utils.parse_cdb_elements_by_mat(cdb_path)
        nset_txt = os.path.join(data_dir, "step1_nsets.txt")
        mplist_txt = os.path.join(data_dir, "step1_mplist.txt")
        cdb_nsets = cdb_utils.parse_cdb_nsets(cdb_path)

        if os.path.exists(nset_txt):
            nsets = cdb_utils.read_nsets_txt(nset_txt)
            for k, vals in cdb_nsets.items():
                if not nsets.get(k):
                    nsets[k] = vals
        else:
            nsets = cdb_nsets

        mat_info = (
            cdb_utils.read_materials_from_mplist_txt(mplist_txt)
            if os.path.exists(mplist_txt) else {}
        )

        inistate_txt = os.path.join(data_dir, "step1_inistate.txt")
        init_stress = (
            cdb_utils.read_inistate_txt(inistate_txt)
            if job.is_submodel and os.path.exists(inistate_txt) else {}
        )
        if init_stress:
            log(f"Initial stress for material(s): "
                f"{', '.join(str(m) for m in sorted(init_stress))}")

        mat_ids = sorted(mat_info.keys()) if mat_info else sorted(elems_by_mat.keys())

        if not nodes:
            raise RuntimeError("NBLOCK에서 노드를 읽지 못했습니다.")
        if not elems_by_mat:
            raise RuntimeError("EBLOCK에서 요소를 읽지 못했습니다.")

        utils.log_node_coordinate_stats(nodes, "NBLOCK raw", log)
        nodes = utils.scale_nodes(nodes, 1000.0)
        utils.log_node_coordinate_stats(nodes, "Scaled x1000", log)
        log("Applied coordinate scale-up: x1000")

        inp_writer.write_template_inp(
            inp_path, nodes, elems_by_mat, mat_ids, nsets, mat_info, log,
            is_submodel=job.is_submodel,
            symmetry_mode=opts["symmetry_mode"],
            init_temp=init_temp,
            final_temp=final_temp,
            has_orthotropic=opts["has_orthotropic"],
            ortho_mat_range=ortho_mat_range,
            init_stress=init_stress,
        )
        log(f"INP created: {inp_path}")
        log(
            "NOTE: 재료 상세(온도의존/ENG CONSTANTS/CTE)는 템플릿 자리만 생성됩니다. "
            "실제 값은 INP에서 채워주세요."
        )


def build_gui(parent):
    """tool_box 런처가 넘겨준 parent 프레임 안에 GUI 를 구성한다."""
    return ConverterApp(parent)


def main():
    """단독 실행용 (python -m tools.db_to_inp.gui)."""
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
