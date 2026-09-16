#!/usr/bin/env python3
"""PyMAPDL 이 이 PC 에서 MAPDL 을 띄울 수 있는지만 확인하는 최소 스크립트.

DB → INP 변환기와 무관하게, PyMAPDL + ANSYS 설치 자체를 점검하기 위한 것이다.
tool_box 를 거치지 않으므로 여기서도 실패하면 원인은 변환기 코드가 아니다.

    python scripts/mapdl_smoke_test.py            # 기본 (버전 242)
    python scripts/mapdl_smoke_test.py 251        # 버전 지정
    python scripts/mapdl_smoke_test.py 242 50100  # 버전 + 포트 지정

확인 순서
  1. ANSYS 관련 환경변수
  2. 기동에 쓸 포트가 비어 있는지
  3. launch_mapdl 로 실제 기동 → 버전 출력 → 종료
실패하면 작업 폴더의 .out/.err 마지막 줄들을 그대로 찍어 준다.
"""

import os
import socket
import sys
import tempfile


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        sk.settimeout(0.3)
        try:
            return sk.connect_ex(("127.0.0.1", port)) != 0
        except OSError:
            return False


def dump_run_files(run_dir):
    print(f"\n--- {run_dir} 의 .out / .err ---")
    found = False
    for name in sorted(os.listdir(run_dir)):
        if not name.lower().endswith((".out", ".err")):
            continue
        found = True
        path = os.path.join(run_dir, name)
        try:
            with open(path, "r", errors="replace") as f:
                lines = [ln.rstrip() for ln in f.read().splitlines() if ln.strip()]
        except OSError as e:
            print(f"[{name}] 읽기 실패: {e}")
            continue
        print(f"\n[{name}] 마지막 {min(len(lines), 40)}줄")
        for ln in lines[-40:]:
            print("   ", ln)
    if not found:
        print("(.out / .err 파일이 없다 — MAPDL 이 아예 시작되지 않았다는 뜻)")


def main():
    version = int(sys.argv[1]) if len(sys.argv) > 1 else 242
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 50052

    print("=== 1. 환경변수 ===")
    for var in (f"AWP_ROOT{version}", f"CADOE_LIBDIR{version}", "ANSYS_LANG",
                "ANSYS_SYSDIR", "ANSYSLMD_LICENSE_FILE",
                "PYMAPDL_START_INSTANCE", "PYMAPDL_PORT", "PYMAPDL_IP"):
        print(f"  {var} = {os.environ.get(var, '(설정 안 됨)')}")

    print("\n=== 2. 포트 ===")
    print(f"  {port}: {'비어 있음' if port_is_free(port) else '사용 중 (다른 것이 물고 있음)'}")

    run_dir = os.path.join(tempfile.gettempdir(), f"mapdl_smoke_{port}")
    os.makedirs(run_dir, exist_ok=True)
    for name in os.listdir(run_dir):
        if name.lower().endswith((".out", ".err", ".lock")):
            try:
                os.remove(os.path.join(run_dir, name))
            except OSError:
                pass

    print(f"\n=== 3. 기동 (run_location={run_dir}) ===")
    from ansys.mapdl.core import launch_mapdl
    import ansys.mapdl.core as pymapdl
    print(f"  ansys-mapdl-core {getattr(pymapdl, '__version__', '?')}")

    mapdl = None
    try:
        mapdl = launch_mapdl(
            run_location=run_dir,
            override=True,
            version=version,
            nproc=4,
            license_type="preppost",
            additional_switches="-smp",
            port=port,
        )
        print(f"  OK — MAPDL {mapdl.version} 기동/접속 성공")
        print(f"  실제 접속 포트: {getattr(mapdl, '_port', '?')}")
        print("\n성공. PyMAPDL 과 ANSYS 설치는 정상이다.")
        return 0
    except Exception as e:
        print(f"  실패: {type(e).__name__}: {e}")
        dump_run_files(run_dir)
        print(
            "\n여기서 실패하면 변환기 코드와 무관한 PyMAPDL/ANSYS 문제다.\n"
            "위 .out 에 'Server listening on ... :<포트>' 가 찍혀 있는데 그 포트가\n"
            f"{port} 가 아니라면, MAPDL 이 다른 포트에 붙은 것이다."
        )
        return 1
    finally:
        if mapdl is not None:
            try:
                mapdl.exit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
