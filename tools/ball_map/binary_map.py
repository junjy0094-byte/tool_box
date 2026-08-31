# -*- coding: utf-8 -*-
"""볼 좌표 목록 -> 0/1 격자 변환.

좌표(x, y) 목록을 받아 x/y 각 축의 최소 간격을 pitch 로 하는 균일 격자를
만들고, 볼이 있는 칸을 1, 없는 칸을 0 으로 채운다.
결과는 행/열 인덱스를 붙인 텍스트로 저장한다.
"""

import numpy as np


def parse_input_string_to_array(raw_input: str) -> np.ndarray:
    """붙여넣은 텍스트에서 (x, y) 좌표 배열을 만든다.

    탭/콤마/공백 어느 구분자든 받아들이고, 숫자가 아닌 줄(헤더 등)은 건너뛴다.
    한 줄에 값이 3개 이상이면 마지막 두 개를 (x, y) 로 본다
    (Ball Map 생성기의 'index, x, y' 출력을 그대로 붙여넣을 수 있도록).
    """
    import re

    data = []
    first = True
    for line in raw_input.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            vals = [float(tok) for tok in re.split(r"[,\t\s]+", line) if tok]
        except ValueError:
            first = False
            continue          # 숫자가 아닌 줄(헤더 등)
        if first:
            first = False
            # Ball Map 생성기의 열 인덱스 헤더 '0,1,2' 는 좌표가 아니다.
            # (실제 첫 데이터 줄은 인덱스 1 로 시작하므로 혼동되지 않는다)
            if vals == [0.0, 1.0, 2.0]:
                continue
        if len(vals) >= 2:
            data.append(vals[-2:])
    return np.array(data, dtype=float)


def _axis_grid(values: np.ndarray, name: str):
    """1축의 (시작값, pitch, 개수) 를 구한다. pitch = 고유값 간 최소 간격."""
    uniq = np.sort(np.unique(values))
    if uniq.size < 2:
        raise ValueError(f"{name} 좌표의 서로 다른 값이 1개뿐입니다. 격자를 만들 수 없습니다.")
    pitch = float(np.min(np.diff(uniq)))
    if pitch <= 0:
        raise ValueError(f"{name} pitch 를 계산할 수 없습니다.")
    n = int(round((uniq[-1] - uniq[0]) / pitch)) + 1
    return float(uniq[0]), pitch, n


def make_grid_binary_array(points: np.ndarray):
    """좌표 배열 -> 0/1 격자.

    Returns:
        (grid, info) — grid 는 (rows, cols) int 배열이며 grid[0] 이 y 최소 행이다.
        info 는 pitch/범위/격자에서 벗어난 점 개수 등의 요약 dict.

    원본 구현은 numpy.arange 로 만든 좌표를 dict 키로 써서 부동소수 오차가
    있으면 점이 조용히 누락됐다. 여기서는 인덱스를 반올림으로 계산해
    같은 격자 정의를 유지하면서 누락을 없앤다.
    """
    if points.size == 0:
        raise ValueError("좌표를 하나도 읽지 못했습니다. 입력 형식을 확인하세요.")
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("좌표는 (x, y) 2열이어야 합니다.")

    x0, x_pitch, ncols = _axis_grid(points[:, 0], "X")
    y0, y_pitch, nrows = _axis_grid(points[:, 1], "Y")

    xi = np.rint((points[:, 0] - x0) / x_pitch).astype(int)
    yi = np.rint((points[:, 1] - y0) / y_pitch).astype(int)

    # 격자점에서 얼마나 벗어났는지 (pitch 의 1% 초과면 어긋난 점으로 센다)
    dx = np.abs(points[:, 0] - (x0 + xi * x_pitch))
    dy = np.abs(points[:, 1] - (y0 + yi * y_pitch))
    off_grid = int(np.count_nonzero((dx > x_pitch * 0.01) | (dy > y_pitch * 0.01)))

    grid = np.zeros((nrows, ncols), dtype=int)
    grid[yi, xi] = 1

    info = {
        "rows": nrows,
        "cols": ncols,
        "points": int(points.shape[0]),
        "ones": int(grid.sum()),
        # 같은 칸에 두 번 이상 찍힌 좌표 개수
        "duplicates": int(points.shape[0] - grid.sum()),
        "x_pitch": x_pitch,
        "y_pitch": y_pitch,
        "x_range": (x0, x0 + (ncols - 1) * x_pitch),
        "y_range": (y0, y0 + (nrows - 1) * y_pitch),
        "off_grid": off_grid,
    }
    return grid, info


def format_grid_with_index(grid: np.ndarray) -> str:
    """행/열 인덱스를 붙인 저장용 텍스트를 만든다 (원본 파일 형식 그대로)."""
    rows, cols = grid.shape
    lines = [(",\t" + "".join("%d,\t" % i for i in range(cols))).strip()]
    for i in range(rows):
        lines.append(("%d,\t" % i + "".join("%d,\t" % v for v in grid[i])).strip())
    return "\n".join(lines)


def save_grid_with_index_to_file(grid: np.ndarray, filename: str) -> None:
    """행/열 인덱스를 붙여 텍스트 파일로 저장한다."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(format_grid_with_index(grid))
        f.write("\n")
