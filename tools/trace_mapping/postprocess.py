"""Trace Mapping CSV 후처리.

trace_mapping 의 Run 결과 CSV (np.savetxt 형식, '#' 주석 헤더 + 숫자 본문) 를
ANSYS APDL 테이블 형식으로 가공한다:
  1. (row_range, col_range) 로 잘라낸 값 영역
  2. 0~1 구간을 N 등분 격자점으로 스냅 (custom_round)
  3. 1열 인덱스 + 1행 헤더를 덧붙여 저장 (*_rounded.txt)

외부에서 row/col 개수는 Custom Grid 의 Y/X coords CSV 데이터 개수
(= 격자 edge 개수) 를 그대로 사용한다. CSV 본문은 (edge-1) 개의 셀을 담으므로
최종 출력 shape 는 (row_range_len, col_range_len) 이 된다.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def count_comment_lines(csv_path: str, marker: str = "#") -> int:
    """CSV 파일 앞부분에서 주석 줄(기본: '#' 로 시작) 개수를 센다."""
    count = 0
    try:
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lstrip().startswith(marker):
                    count += 1
                else:
                    break
    except OSError:
        return 0
    return count


def count_csv_rows(csv_path: str) -> int:
    """열 벡터 CSV 의 데이터 개수(공백/빈줄 제외)."""
    n = 0
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def custom_round(values, n: int):
    """0~1 구간을 N+1개 격자점으로 나누고 가장 가까운 격자점으로 스냅.

    - N=10: {0, 0.1, 0.2, ..., 1.0}
    - N=100: {0, 0.01, 0.02, ..., 1.0}

    입력이 [0,1] 을 벗어나도 클리핑하지 않고 격자 간격을 그대로 연장 적용한다.
    """
    import numpy as np
    arr = np.asarray(values, dtype=float)
    return np.round(arr * n) / n


def read_region_and_round(
    csv_path: str,
    row_range: Tuple[int, int],
    col_range: Tuple[int, int],
    n: int,
    header=None,
    index_col=None,
    skiprows: int = 0,
    output_path: Optional[str] = None,
):
    """CSV 값 영역을 잘라 N 격자 스냅 후 APDL 테이블 형식으로 저장/반환.

    최종 shape = (row_range_len, col_range_len). 입력 CSV 본문이
    (row_range_len - 1, col_range_len - 1) 인 경우에 맞춰 헤더/인덱스를 덧붙인다.
    """
    import numpy as np
    import pandas as pd

    df = pd.read_csv(csv_path, header=header, index_col=index_col,
                     skiprows=skiprows)

    r0, r1 = row_range
    c0, c1 = col_range
    region = df.iloc[r0:r1, c0:c1].to_numpy(dtype=float)

    # 열 헤더(1행): 값은 1..(c1-c0-1) 이고 길이는 region 의 열 수와 일치해야 한다.
    # trace_mapping CSV 는 본문이 (edge-1) 개이므로 region.shape[1] == c1-c0-1 이다.
    col_header = np.arange(1, region.shape[1] + 1).reshape(1, -1)
    region = np.vstack([col_header, region])

    # 행 인덱스(1열): 0..(r1-r0-1) — 길이는 header 붙인 뒤의 region 행 수와 일치.
    row_index = np.arange(0, region.shape[0]).reshape(-1, 1)
    region = np.hstack([row_index, region])

    rounded = custom_round(region, n)

    if output_path is not None:
        pd.DataFrame(rounded).to_csv(output_path, index=False, header=False)

    return rounded


def iter_target_csvs(input_dirs: Iterable[str],
                     exclude: Iterable[str] = ()) -> List[str]:
    """input_dirs 들 안에서 후처리 대상 CSV 를 수집한다.

    이미 후처리된 '*_rounded.csv' / '*_rounded.txt' 및 exclude 로 지정된
    파일(예: X/Y coords CSV)은 제외한다.
    """
    excl = {os.path.abspath(p) for p in exclude if p}
    seen: set[str] = set()
    targets: List[str] = []
    for d in input_dirs:
        if not d or not os.path.isdir(d):
            continue
        for csv_file in sorted(glob.glob(os.path.join(d, "*.csv"))):
            abs_fp = os.path.abspath(csv_file)
            if abs_fp in seen or abs_fp in excl:
                continue
            name = os.path.basename(csv_file).lower()
            if name.endswith("_rounded.csv"):
                continue
            seen.add(abs_fp)
            targets.append(csv_file)
    return targets


def output_path_for(csv_file: str, suffix: str = "_rounded.txt") -> str:
    """입력 CSV 옆에 결과를 저장할 경로를 만든다 (base + suffix)."""
    base, _ = os.path.splitext(csv_file)
    return f"{base}{suffix}"
