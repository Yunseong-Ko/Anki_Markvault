"""PDF/docx 용 HTML 만들기 (GUI 없음). 실제 PDF 인쇄는 gui.py 가 QtWebEngine 으로."""
import html as htmllib
import re
import shutil
import subprocess
from collections import OrderedDict
from datetime import date, datetime
from typing import List, Optional

from . import config as C
from . import content as CT
from .collector import CardInfo


def _find_memo(memos, c):
    return memos.get(-c.nid) or memos.get(c.cid) or next((memos[x] for x in (c.cids or []) if x in memos), "")
from .renderer import _HR, _RE_CLOZE, _RE_CLOZE_INACTIVE, _RE_IO, _RE_SOUND, Renderer

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
       font-size: 11pt; line-height: 1.55; color: #222; }
h1 { font-size: 20pt; margin: 0 0 4pt; }
.sub { color: #777; font-size: 9.5pt; margin-bottom: 18pt; }
h2 { font-size: 15pt; margin: 26pt 0 8pt; padding-bottom: 3pt; border-bottom: 2px solid #222; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 18pt 0 6pt; color: #333; page-break-after: avoid; }
h4 { font-size: 11pt; margin: 12pt 0 4pt; color: #666; font-weight: 600; page-break-after: avoid; }
.no { color: #aaa; font-size: 8.5pt; margin-right: 4pt; }
.card { page-break-inside: avoid; padding: 8pt 0 10pt; border-bottom: 1px solid #e3e3e3; }
.card h3 { font-size: 11.5pt; margin: 0 0 5pt; font-weight: 600; }
.body { margin-left: 2pt; }
.body img { max-width: 100% !important; width: auto !important; height: auto !important; }
.imgs { display: grid; grid-template-columns: 1fr 1fr; gap: 6pt; margin: 6pt 0 2pt; }
.imgs.one { grid-template-columns: 1fr; }
.imgs div { display: flex; align-items: flex-start; justify-content: center; }
.imgs img { max-width: 100% !important; max-height: 75mm !important; width: auto !important; height: auto !important;
            object-fit: contain; page-break-inside: avoid; }
.imgs.one img { max-height: 95mm !important; }
.cloze { background: #fff3a3; padding: 0 2px; border-radius: 2px; font-weight: 600; }
.cloze-inactive { color: inherit; }
.hidden .cloze { background: #333; color: #333; }
.q { margin-bottom: 4pt; } .a { padding-left: 10pt; border-left: 3px solid #ddd; } .extra { margin-top: 4pt; font-size: 10pt; color: #444; }
.lbl { color: #999; font-size: 9pt; margin-right: 4pt; }
.meta { color: #888; font-size: 8.5pt; margin-top: 5pt; }
.memo { background: #f3f6fb; border-left: 3px solid #5b8def; padding: 5pt 8pt; margin-top: 6pt; font-size: 10pt; }
.toc li { margin: 1pt 0; } .toc .n { color: #888; }
.pagebreak { page-break-after: always; }
.answers h4 { margin: 10pt 0 2pt; font-size: 10.5pt; }
"""


_RE_IMG = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*["\'])([^"\']+)(["\'])', re.I)
def _strip(html: str, media_base: str = "") -> str:
    html = _RE_SOUND.sub("", html)
    if media_base:
        html = _RE_IMG.sub(lambda m: m.group(1) + (m.group(2) if "://" in m.group(2) or m.group(2).startswith("data:")
                                                  else media_base + m.group(2)) + m.group(3), html)
    if "image-occlusion" in html:
        html = _RE_IO.sub("", html)
    return html


def _answer_part(info: CardInfo) -> str:
    parts = _HR.split(info.answer_html, maxsplit=1)
    return parts[1] if len(parts) == 2 else info.answer_html


def card_parts(c: CardInfo, mode: str, media_base: str = ""):
    """(문제 html, 정답 html 또는 None, 추가 필드들). media_base 를 주면 이미지 경로를 절대경로로."""
    ct = c.content
    fix = lambda h: _strip(h, media_base)  # noqa: E731
    if ct is None or ct.kind == "template":
        return fix(_answer_part(c)), None, []
    extras = [(n, fix(h)) for n, h in ct.extras]
    if ct.kind == "cloze":
        if mode == "check":
            return (fix(CT.cloze_to_html(ct.question_html, c.ords or [c.ord], hidden=True)),
                    fix(CT.cloze_to_html(ct.question_html, c.ords or [c.ord])), extras)
        return fix(CT.cloze_to_html(ct.question_html, c.ords or [c.ord])), None, extras
    if ct.kind == "io":
        return fix(ct.question_html), None, extras
    return fix(ct.question_html), fix(ct.answer_html), extras


def filter_cards(cards: List[CardInfo], scope: str, deck: str = "", min_lapses: int = 3,
                 first_seen: Optional[dict] = None) -> List[CardInfo]:
    """scope: all | deck | week | lapses"""
    if scope == "deck" and deck:
        return [c for c in cards if c.deck == deck or c.deck.startswith(deck + "::")]
    if scope == "lapses":
        return [c for c in cards if c.lapses >= min_lapses]
    if scope == "week" and first_seen:
        y, w, _ = date.today().isocalendar()
        out = []
        for c in cards:
            fs = (first_seen.get(str(c.cid)) or {}).get("first_seen")
            if fs and date.fromisoformat(fs).isocalendar()[:2] == (y, w):
                out.append(c)
        return out
    return cards


_RE_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_RE_EMPTY_BLOCK = re.compile(r"<(div|p|span)\b[^>]*>\s*(<br\s*/?>|&nbsp;|\s)*</\1>", re.I)


def pull_images(html: str):
    """html 에서 <img> 를 빼서 따로 모은다 (사진은 카드 끝에 2열로 배치하기 위해)."""
    imgs = _RE_IMG_TAG.findall(html)
    rest = _RE_IMG_TAG.sub("", html)
    for _ in range(3):
        rest = _RE_EMPTY_BLOCK.sub("", rest)
    return rest, imgs


def _strip_size(img: str) -> str:
    """AnKing 그림의 width/height/style 은 비율을 깨므로 지운다."""
    return re.sub(r'\s(width|height|style)\s*=\s*("[^"]*"|\'[^\']*\'|\S+)', "", img, flags=re.I)


def build_html(cards: List[CardInfo], cfg: dict, r: Renderer, mode: str = "read",
               memos: Optional[dict] = None, title: str = "Anki 복습", media_dir: str = "",
               extra_head: str = "") -> str:
    """mode: read(정답 보임) | check(빈칸·문제만, 정답은 끝에)
    덱은 공통 앞부분을 빼고 단계별 제목(계통 → 주제 → 소주제)으로. 카드 제목 줄은 본문과 중복이라 넣지 않는다.
    사진은 비율을 지키며 카드 끝에 2열로."""
    from .decknames import common_prefix, heading_levels
    memos = memos or {}
    base = ("file://" + media_dir.replace("\\", "/").rstrip("/") + "/") if media_dir else ""
    if base and not base.startswith("file:///"):
        base = base.replace("file://", "file:///", 1)
    prefix = common_prefix((c.deck for c in cards), C.prefix_base(cfg))

    out = [f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style>", extra_head, "</head><body>"]
    out.append(f"<h1>{htmllib.escape(title)}</h1>")
    scope = " › ".join(prefix) if prefix else "전체"
    out.append(f"<div class='sub'>{htmllib.escape(scope)} · 카드 {sum(len(c.cids or [c.cid]) for c in cards)}장 · "
               f"노트 {len(cards)}개 · {datetime.now().strftime('%Y-%m-%d')}</div>")

    answers = []
    printed: List[str] = []
    for no, c in enumerate(cards, 1):
        levels = heading_levels(c.deck, prefix)
        for depth, name in enumerate(levels):
            if levels[: depth + 1] != printed[: depth + 1]:
                tag = ("h2", "h3", "h4")[min(depth, 2)]
                out.append(f"<{tag}>{htmllib.escape(name)}</{tag}>")
        printed = levels

        q_html, a_html, extras = card_parts(c, mode, base)
        imgs: List[str] = []
        q_html, i1 = pull_images(q_html)
        imgs += i1
        out.append("<div class='card'><div class='body'>")
        num = f"<span class='no'>{no}</span>" if mode == "check" else ""
        if a_html is None:
            out.append(f"<div>{num}{q_html}</div>")
        else:
            a_html, i2 = pull_images(a_html)
            out.append(f"<div class='q'>{num}<span class='lbl'>Q</span>{q_html}</div>")
            if mode == "check":
                answers.append((no, a_html, i2))
            else:
                imgs += i2
                out.append(f"<div class='a'><span class='lbl'>A</span>{a_html}</div>")
        if mode != "check":
            for name, html in extras:
                html, i3 = pull_images(html)
                imgs += i3
                if CT.plain(html).strip():
                    out.append(f"<div class='extra'><span class='lbl'>{htmllib.escape(name)}</span>{html}</div>")
        if imgs:
            cls = "imgs one" if len(imgs) == 1 else "imgs"
            out.append(f"<div class='{cls}'>" + "".join(f"<div>{_strip_size(i)}</div>" for i in imgs) + "</div>")
        out.append("</div>")
        if cfg.get("show_meta", True):
            meta = r.meta_for(c).lstrip("> ").replace("`", "")
            out.append(f"<div class='meta'>{htmllib.escape(meta)}</div>")
        memo = _find_memo(memos, c)
        if memo:
            body = "<br>".join(htmllib.escape(l.lstrip("> ")) for l in memo.split("\n")[1:])
            out.append(f"<div class='memo'>{body}</div>")
        out.append("</div>")
    if mode == "check" and answers:
        out.append("<div class='pagebreak'></div><h2>정답</h2><div class='answers'>")
        for no, a, ims in answers:
            out.append(f"<div class='card'><span class='no'>{no}</span>{a}")
            if ims:
                out.append("<div class='imgs'>" + "".join(f"<div>{_strip_size(i)}</div>" for i in ims) + "</div>")
            out.append("</div>")
        out.append("</div>")
    out.append("</body></html>")
    return "\n".join(out)


def md_to_docx(md_path: str, docx_path: str, resource_dir: str) -> Optional[str]:
    """pandoc 있으면 변환, 없으면 안내 문구 반환."""
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return "pandoc 이 설치되어 있지 않아요. https://pandoc.org/installing.html 에서 설치하면 docx 로도 뽑을 수 있어요."
    # 옵시디언 전용 문법은 pandoc 이 모르니 바꿔 준다
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    md = re.sub(r"==(.+?)==", r"**\1**", md)
    md = re.sub(r"^%% .*? %%\n", "", md, flags=re.M)
    md = re.sub(r"^> \[!note\].*$", "> **내 메모**", md, flags=re.M)
    tmp = md_path + ".pandoc.md"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(md)
    try:
        subprocess.run([pandoc, tmp, "-o", docx_path, "--resource-path", resource_dir], check=True,
                       capture_output=True, timeout=120)
    except subprocess.CalledProcessError as e:
        return f"pandoc 오류: {e.stderr.decode(errors='ignore')[:300]}"
    finally:
        try:
            import os
            os.remove(tmp)
        except OSError:
            pass
    return None
