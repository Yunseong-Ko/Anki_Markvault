"""PDF/docx 용 HTML 만들기 (GUI 없음). 실제 PDF 인쇄는 gui.py 가 QtWebEngine 으로."""
import html as htmllib
import re
import shutil
import subprocess
from collections import OrderedDict
from datetime import date, datetime
from typing import List, Optional

from . import config as C
from .collector import CardInfo
from .renderer import _HR, _RE_CLOZE, _RE_CLOZE_INACTIVE, _RE_IO, _RE_SOUND, Renderer

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
       font-size: 11pt; line-height: 1.55; color: #222; }
h1 { font-size: 20pt; margin: 0 0 4pt; }
.sub { color: #777; font-size: 9.5pt; margin-bottom: 18pt; }
h2 { font-size: 13pt; margin: 22pt 0 8pt; padding-bottom: 3pt; border-bottom: 1.5px solid #333; page-break-after: avoid; }
.card { page-break-inside: avoid; padding: 8pt 0 10pt; border-bottom: 1px solid #e3e3e3; }
.card h3 { font-size: 11.5pt; margin: 0 0 5pt; font-weight: 600; }
.body { margin-left: 2pt; }
.body img { max-width: 100%; max-height: 70mm; display: block; margin: 4pt 0; }
.cloze { background: #fff3a3; padding: 0 2px; border-radius: 2px; font-weight: 600; }
.cloze-inactive { color: inherit; }
.hidden .cloze { background: #333; color: #333; }
.q { margin-bottom: 4pt; } .a { padding-left: 10pt; border-left: 3px solid #ddd; }
.lbl { color: #999; font-size: 9pt; margin-right: 4pt; }
.meta { color: #888; font-size: 8.5pt; margin-top: 5pt; }
.memo { background: #f3f6fb; border-left: 3px solid #5b8def; padding: 5pt 8pt; margin-top: 6pt; font-size: 10pt; }
.toc li { margin: 1pt 0; } .toc .n { color: #888; }
.pagebreak { page-break-after: always; }
.answers h4 { margin: 10pt 0 2pt; font-size: 10.5pt; }
"""


_RE_IMG = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*["\'])([^"\']+)(["\'])', re.I)
_MEDIA_BASE = ""


def _strip(html: str) -> str:
    html = _RE_SOUND.sub("", html)
    if _MEDIA_BASE:
        html = _RE_IMG.sub(lambda m: m.group(1) + (m.group(2) if "://" in m.group(2) or m.group(2).startswith("data:")
                                                  else _MEDIA_BASE + m.group(2)) + m.group(3), html)
    if "image-occlusion" in html:
        html = _RE_IO.sub("", html)
    return html


def _answer_part(info: CardInfo) -> str:
    parts = _HR.split(info.answer_html, maxsplit=1)
    return parts[1] if len(parts) == 2 else info.answer_html


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


def build_html(cards: List[CardInfo], cfg: dict, r: Renderer, mode: str = "read",
               memos: Optional[dict] = None, title: str = "Anki 복습", media_dir: str = "",
               extra_head: str = "") -> str:
    """mode: read(정답 보임) | check(문제만, 정답은 끝에) | anki(카드 CSS 그대로)
    media_dir 를 주면 이미지가 file:// 절대경로로 바뀐다. extra_head 는 MathJax 등 스크립트."""
    global _MEDIA_BASE
    memos = memos or {}
    _MEDIA_BASE = ("file://" + media_dir.replace("\\", "/").rstrip("/") + "/") if media_dir else ""
    if _MEDIA_BASE and not _MEDIA_BASE.startswith("file:///"):
        _MEDIA_BASE = _MEDIA_BASE.replace("file://", "file:///", 1)
    by_deck: "OrderedDict[str, List[CardInfo]]" = OrderedDict()
    for c in cards:
        by_deck.setdefault(c.deck, []).append(c)

    out = [f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style>"]
    if mode == "anki":
        seen = set()
        for c in cards:
            if c.css and c.notetype not in seen:
                seen.add(c.notetype)
                out.append(f"<style>{c.css}</style>")
    out.append(extra_head)
    out.append("</head><body>")
    out.append(f"<h1>{htmllib.escape(title)}</h1>")
    out.append(f"<div class='sub'>{len(cards)}장 · {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
               f"{htmllib.escape(C.effective_query(cfg))}</div>")

    # 목차
    out.append("<div class='toc'><ul>")
    for deck, cs in by_deck.items():
        out.append(f"<li>{htmllib.escape(deck.replace('::', ' › '))} <span class='n'>({len(cs)}장)</span><ul>")
        for c in cs:
            out.append(f"<li>{htmllib.escape(r.title_for(c))}</li>")
        out.append("</ul></li>")
    out.append("</ul></div><div class='pagebreak'></div>")

    answers = []
    for deck, cs in by_deck.items():
        out.append(f"<h2>{htmllib.escape(deck.replace('::', ' › '))}</h2>")
        for c in cs:
            q_html = _strip(c.question_html)
            a_html = _strip(_answer_part(c))
            meta = r.meta_for(c).lstrip("> ").replace("`", "")
            out.append(f"<div class='card'><h3>{htmllib.escape(r.title_for(c))}</h3>")
            if mode == "anki":
                out.append(f"<div class='body card'>{_strip(c.answer_html)}</div>")
            elif c.is_cloze:
                if mode == "check":
                    out.append(f"<div class='body hidden'>{a_html}</div>")
                    answers.append((r.title_for(c), a_html))
                else:
                    out.append(f"<div class='body'>{a_html}</div>")
            else:
                out.append(f"<div class='body'><div class='q'><span class='lbl'>Q</span>{q_html}</div>")
                if mode == "check":
                    answers.append((r.title_for(c), a_html))
                else:
                    out.append(f"<div class='a'><span class='lbl'>A</span>{a_html}</div>")
                out.append("</div>")
            if cfg.get("show_meta", True):
                out.append(f"<div class='meta'>{htmllib.escape(meta)}</div>")
            memo = memos.get(c.cid)
            if memo:
                body = "<br>".join(htmllib.escape(l.lstrip("> ")) for l in memo.split("\n")[1:])
                out.append(f"<div class='memo'>{body}</div>")
            out.append("</div>")
    if mode == "check" and answers:
        out.append("<div class='pagebreak'></div><h2>정답</h2><div class='answers'>")
        for t, a in answers:
            out.append(f"<h4>{htmllib.escape(t)}</h4><div class='body'>{a}</div>")
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
