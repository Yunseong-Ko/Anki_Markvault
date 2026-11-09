"""카드 내용을 노트 '필드'에서 직접 뽑는다.

render_output() 은 카드 템플릿 전체(숨김 버튼, 스크립트, AnKing 의 자료 칸 등)를 그려서
읽기용으로는 지저분하다. 그래서 본문은 필드에서 만들고, 템플릿은 필드를 못 찾을 때만 쓴다.

- Cloze: '{{c1::…}}' 가 든 필드 → 이 카드 번호의 빈칸은 <span class="cloze">, 나머지는 그냥 글자
- 기본 카드: 첫 필드 = 문제, 둘째 필드 = 정답
- Image Occlusion: Header + Image 필드
- 그 밖에 이름이 '추가 필드' 목록에 있는 필드(Extra, Back Extra, Lecture Notes …)는 이름표를 붙여 덧붙임
"""
import html as htmllib
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

DEFAULT_EXTRA_FIELDS = ["Extra", "Back Extra", "Lecture Notes", "Missed Questions", "Personal Notes",
                        "Notes", "Comments", "Explanation", "추가", "메모", "해설"]

_RE_CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)
_RE_SOUND = re.compile(r"\[sound:[^\]]+\]")
_RE_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_RE_BLOCK = re.compile(r"<\s*(br|/div|/p|/li|li|/h\d|/tr|hr)\b[^>]*>", re.I)
_RE_TAG = re.compile(r"<[^>]+>")
# XML/HTML 에 들어가면 안 되는 제어 문자 (탭·줄바꿈 제외)
_RE_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


@dataclass
class Content:
    title: str = ""
    kind: str = "basic"            # basic | cloze | io | template
    question_html: str = ""        # 기본 카드의 문제 / cloze 의 빈칸 문장 / io 의 머리말+그림
    answer_html: str = ""          # 기본 카드의 정답
    extras: List[Tuple[str, str]] = field(default_factory=list)   # (필드 이름, html)


def clean(html: str) -> str:
    html = _RE_CTRL.sub("", html or "")
    html = _RE_SCRIPT.sub("", html)
    html = _RE_SOUND.sub("", html)
    return html.strip()


def plain(html: str) -> str:
    t = _RE_BLOCK.sub("\n", html)
    t = _RE_TAG.sub("", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    return t


def is_empty(html: str) -> bool:
    if re.search(r"<img\b", html or "", re.I):
        return False
    return not plain(html).strip()


def cloze_to_html(text: str, ords, hidden: bool = False) -> str:
    """{{cN::답::힌트}} → 표시한 카드들(ords, 0부터)의 빈칸은 강조, 다른 번호는 그냥 답."""
    targets = {o + 1 for o in (ords if isinstance(ords, (list, tuple, set)) else [ords])}

    def rep(m):
        n, ans, hint = int(m.group(1)), m.group(2), m.group(3)
        if n in targets:
            if hidden:
                return f'<span class="cloze">[{hint or "…"}]</span>'
            return f'<span class="cloze">{ans}</span>'
        return ans
    # 중첩 cloze 대비 몇 번 반복
    for _ in range(3):
        new = _RE_CLOZE.sub(rep, text)
        if new == text:
            break
        text = new
    return text


def first_line(html: str, limit: int = 70) -> str:
    for line in plain(_RE_CLOZE.sub(lambda m: m.group(2), html)).split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return (line[:limit] + "…") if len(line) > limit else line
    return ""


def build(note, notetype: dict, ord_: int, extra_names: Optional[List[str]] = None) -> Content:
    names = [f["name"] for f in notetype["flds"]]
    vals = [clean(v) for v in note.fields]
    by_name = {n.lower(): (n, v) for n, v in zip(names, vals)}
    wanted = {n.lower() for n in (extra_names or DEFAULT_EXTRA_FIELDS)}
    used = set()
    c = Content()

    # Image Occlusion (Anki 23.10+ 내장)
    if "occlusion" in by_name and "image" in by_name:
        c.kind = "io"
        header = by_name.get("header", ("", ""))[1]
        c.question_html = (f"<div>{header}</div>" if header else "") + by_name["image"][1]
        used |= {"occlusion", "image", "header"}
        c.title = first_line(header) or "Image Occlusion"
    elif notetype.get("type") == 1:
        c.kind = "cloze"
        idx = next((i for i, v in enumerate(vals) if _RE_CLOZE.search(v)), 0)
        c.question_html = vals[idx] if vals else ""
        used.add(names[idx].lower() if names else "")
        c.title = first_line(c.question_html)
    else:
        c.kind = "basic"
        c.question_html = vals[0] if vals else ""
        c.answer_html = vals[1] if len(vals) > 1 else ""
        used |= {n.lower() for n in names[:2]}
        c.title = first_line(c.question_html)

    for n, v in zip(names, vals):
        if n.lower() in used or n.lower() not in wanted or is_empty(v):
            continue
        c.extras.append((n, v))
    return c
