# Tool Box

반도체 패키지 해석 업무에서 반복되는 작업들을 도구 하나씩으로 묶어 둔 GUI 모음이다.
런처에서 도구 이름을 누르면 그 도구만 별도 창으로 열리고, 창을 닫으면 해제된다.

```bash
pip install -r requirements.txt
python main.py
```

## 도구 목록

| 도구 | 하는 일 |
| --- | --- |
| 스크린샷 | 화면 영역을 드래그로 캡처해 클립보드에 복사 (영역 기억 → 반복 캡처) |
| input 변수 비교 | 여러 APDL 입력 파일의 변수 값을 한 표에서 비교 (차이 강조) |
| 파일 비교 | 여러 텍스트 파일의 동일 여부를 해시로 묶고, 두 파일을 줄 단위로 비교·동기화 |
| Trace Mapping | Gerber 배선 도면을 NxM 격자의 동박 면적 비율로 변환 (CSV/PNG/APDL) |
| Strain → CTE 변환 | APDL 열변형(THSX) 물성을 온도별 CTE 로 변환 (표·그래프·APDL 코드) |
| Ball Map 생성기 (좌표) | 패키지 크기·pitch 로 BGA 볼 좌표를 생성하고 txt 로 저장 |
| Ball Map 변환기 (0,1) | 볼 좌표 목록을 0/1 격자 맵으로 변환 (그림·텍스트) |
| DB → INP 변환기 (ANSYS→Abaqus) | ANSYS .db 를 정리해 .cdb 로 뽑고 Abaqus .inp 로 변환 |
| Bump array 내 sub zone 생성기 | 범프 배열 위에 zone 폴리곤을 그려 ANSYS APDL 매크로로 출력 |
| Leadframe 그리기 | 이미지를 따라 그려 APDL area 매크로 생성 (픽셀→um 환산) |

## 도움말 보는 법

도구마다 입력·출력·사용 순서·주의사항을 정리한 설명이 있다. 세 곳에서 같은 내용을 본다.

- **프로그램 안** — 런처의 `도움말` 버튼, 도구 이름 옆 `?` 버튼, 도구 창 위쪽 `도움말` 버튼
- **문서** — [docs/TOOLS.md](docs/TOOLS.md)
- 목록에서 도구 이름 위에 마우스를 올리면 한 줄 요약이 뜬다

## 새 도구 추가하기

1. `tools/` 아래에 `BaseTool` 을 상속한 클래스를 만들고 `name`, `summary`,
   `help_text`, `build_ui(parent)` 를 채운다. (`summary` / `help_text` 가 그대로
   도움말이 된다 — 입력 / 출력 / 사용 순서 / 참고 순서로 적는다)
2. `main.py` 의 `TOOLS` 리스트에 클래스를 추가한다.
3. `python scripts/gen_tool_docs.py` 로 `docs/TOOLS.md` 를 다시 만든다.

무거운 의존성(numpy, scipy, matplotlib, shapely, pcb-tools, PyMAPDL)은 해당 도구를
열 때만 로드되도록 `build_ui` 안에서 import 한다.
