#!/usr/bin/env python3
"""도구 클래스의 summary / help_text 를 모아 docs/TOOLS.md 를 만든다.

도움말의 원본은 각 도구 클래스이고, 이 스크립트는 그것을 마크다운으로 옮길
뿐이다. 도움말을 고쳤으면 이 스크립트를 다시 실행해 문서를 맞춰 준다.

    python scripts/gen_tool_docs.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "docs", "TOOLS.md")

HEADER = """\
# Tool Box 도구 설명서

> 이 파일은 `python scripts/gen_tool_docs.py` 로 자동 생성된다.
> 내용을 고치려면 각 도구 클래스의 `summary` / `help_text` 를 수정한 뒤
> 스크립트를 다시 실행할 것. 같은 내용을 프로그램 안에서도 볼 수 있다
> (런처의 **도움말** 버튼, 도구 이름 옆 **?** 버튼, 도구 창의 **도움말** 버튼).

"""


def _slug(title: str) -> str:
    """GitHub 방식의 헤딩 앵커: 소문자 + 공백은 하이픈 + 그 외 기호 제거."""
    out = []
    for ch in title.lower():
        if ch.isalnum() or ch == "-":
            out.append(ch)
        elif ch in " _":
            out.append("-")
    return "".join(out)


def main() -> None:
    # tkinter 없이도 문서를 뽑을 수 있게, import 실패는 그대로 알린다.
    import main as launcher
    from tools.help_browser import OVERVIEW, OVERVIEW_TITLE

    tools = launcher.TOOLS
    lines = [HEADER, "## 목차\n"]
    for t in tools:
        lines.append(f"- [{t.name}](#{_slug(t.name)}) — {t.summary}")
    lines.append("")

    lines.append(f"## {OVERVIEW_TITLE}\n")
    lines.append("```")
    lines.append(OVERVIEW.rstrip())
    lines.append("```\n")

    for t in tools:
        lines.append(f"## {t.name}\n")
        if t.summary:
            lines.append(f"**{t.summary}**\n")
        lines.append("```")
        lines.append((t.help_text or "설명이 아직 없습니다.").rstrip())
        lines.append("```\n")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{OUT} 생성 완료 — 도구 {len(tools)}개")


if __name__ == "__main__":
    main()
