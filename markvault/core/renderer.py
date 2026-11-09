"""카드 HTML → Markdown.

Anki 가 실제로 그린 question/answer HTML 을 받아서 변환하므로 노트 유형에 상관없이 동작.
- Cloze: highlight 모드면 정답 면 한 줄에 빈칸을 ==…== 로, qa 모드면 문제/정답 분리
- 이미지: collection.media → <out>/_media 로 복사, 링크 교체
- MathJax \\(…\\) → $…$, \\[…\\] → $$…$$
- [sound:…] 제거, Image Occlusion 은 원본 이미지만 (가림막은 JS 라 정적 변환 불가)
"""
import html as htmllib
import os
import re
import shutil
from datetime import datetime
from typing import Dict, List

from . import config as C
from . import content as CT
from .collector import CardInfo

from markdownify import MarkdownConverter  # noqa: E402  (vendor path 는 core/__init__ 에서)


def _cloze_md(html: str) -> str:
    """content 가 만든 <span class="cloze">x</span> → 형광펜 토큰 (markdownify 가 span 을 지우므로 미리)."""
    return _RE_CLOZE.sub(lambda m: f"=={m.group(1)}==", html)


class _Conv(MarkdownConverter):
    class Options(MarkdownConverter.DefaultOptions):
        heading_style = "ATX"
        bullets = "-"
        strip = ["script", "style"]
        escape_underscores = False
        escape_asterisks = False
        escape_misc = False
        newline_style = "BACKSLASH"

    def convert_hr(self, el, text, parent_tags):
        return "\n\n---\n\n"


_converter = _Conv()

_RE_IMG = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\'][^>]*>', re.I)
_RE_SOUND = re.compile(r"\[sound:[^\]]+\]")
_RE_MATH = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]|\[\$\](.+?)\[/\$\]|\[\$\$\](.+?)\[/\$\$\]", re.S)
_RE_CLOZE = re.compile(r'<span\b[^>]*class="cloze"[^>]*>(.*?)</span>', re.S)
_RE_CLOZE_INACTIVE = re.compile(r'<span\b[^>]*class="cloze-inactive"[^>]*>(.*?)</span>', re.S)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_IO = re.compile(r'<div\b[^>]*id="image-occlusion-canvas"[^>]*>.*?</div>', re.S)
_HR = re.compile(r"<hr\s+id=['\"]?answer['\"]?\s*/?>", re.I)


def _plain(html: str) -> str:
    t = _RE_TAG.sub("", html)
    t = htmllib.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


class Renderer:
    def __init__(self, cfg: dict, media_dir: str, out_dir: str):
        self.cfg = cfg
        self.media_dir = media_dir
        self.media_out = os.path.join(out_dir, "_media")
        self.copied = 0

    # ---- 미디어 -------------------------------------------------------
    def _copy_media(self, name: str) -> str:
        name = htmllib.unescape(name)
        if "://" in name or name.startswith("data:"):
            return name
        src = os.path.join(self.media_dir, name)
        dst = os.path.join(self.media_out, name)
        if os.path.exists(src) and (not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst)):
            os.makedirs(self.media_out, exist_ok=True)
            shutil.copy2(src, dst)
            self.copied += 1
        return name

    def _img_link(self, name: str) -> str:
        if self.cfg["image_link_style"] == "wikilink":
            return f"![[_media/{name}]]"
        return f"![](_media/{name.replace(' ', '%20')})"

    # ---- HTML → Markdown ----------------------------------------------
    def html_to_md(self, html: str) -> str:
        tokens: Dict[str, str] = {}

        def tok(value: str) -> str:
            key = f"MVTOK{len(tokens)}X"
            tokens[key] = value
            return key

        html = _RE_SOUND.sub("", html)
        # Image Occlusion: 가림막 캔버스 제거, 이미지는 남김
        is_io = "image-occlusion" in html
        if is_io:
            html = _RE_IO.sub("", html)
        # 수식 보호
        def _math(m):
            inline, block = (m.group(1) or m.group(3)), (m.group(2) or m.group(4))
            if inline is not None:
                return tok(f"${htmllib.unescape(inline).strip()}$")
            return tok(f"$${htmllib.unescape(block).strip()}$$")
        html = _RE_MATH.sub(_math, html)
        # 이미지 → 복사 + 토큰
        html = _RE_IMG.sub(lambda m: tok(self._img_link(self._copy_media(m.group(1)))), html)

        md = _converter.convert(html)
        for k, v in tokens.items():
            md = md.replace(k, v)
        md = re.sub(r"[ \t]+\n", "\n", md)
        md = re.sub(r"(\\\n)+(?=\n|$)", "\n", md)   # 끝에 남은 줄바꿈 표시(\) 제거
        md = re.sub(r"\\$", "", md.strip())
        md = re.sub(r"\n{3,}", "\n\n", md).strip()
        if is_io:
            md += "\n\n*(Image Occlusion 카드 — 가림막은 Anki 에서 확인)*"
        return md

    # ---- 카드 한 장 ----------------------------------------------------
    def _split_qa(self, info: CardInfo):
        """템플릿 결과의 answer_text 는 보통 '문제 <hr id=answer> 정답'."""
        parts = _HR.split(info.answer_html, maxsplit=1)
        if len(parts) == 2:
            return info.question_html, parts[1]
        return info.question_html, info.answer_html

    def title_for(self, info: CardInfo) -> str:
        t = (info.content.title if info.content else "") or ""
        return t.replace("[", "(").replace("]", ")") or "(내용 없음)"

    def body_for(self, info: CardInfo) -> str:
        ct = info.content
        out = []
        if ct is None or ct.kind == "template":
            q_html, a_html = self._split_qa(info)
            a = _RE_CLOZE.sub(lambda m: f"=={m.group(1)}==", a_html)
            a = _RE_CLOZE_INACTIVE.sub(lambda m: m.group(1), a)
            out.append(self.html_to_md(a))
        elif ct.kind == "cloze":
            if self.cfg["cloze_mode"] == "highlight":
                out.append(self.html_to_md(_cloze_md(CT.cloze_to_html(ct.question_html, info.ords or [info.ord]))))
            else:
                out.append("**Q.** " + self.html_to_md(_cloze_md(CT.cloze_to_html(ct.question_html, info.ords or [info.ord], hidden=True))))
                out.append("**A.** " + self.html_to_md(_cloze_md(CT.cloze_to_html(ct.question_html, info.ords or [info.ord]))))
        elif ct.kind == "io":
            out.append(self.html_to_md(ct.question_html))
            out.append("*(Image Occlusion 카드 — 가림막은 Anki 에서)*")
        else:
            q_md, a_md = self.html_to_md(ct.question_html), self.html_to_md(ct.answer_html)
            sep = lambda m: "\n\n" if ("\n" in m or m.startswith(("-", "1.", "!["))) else " "
            out.append(f"**Q.**{sep(q_md)}{q_md}")
            if a_md:
                out.append(f"**A.**{sep(a_md)}{a_md}")
        for name, html in (ct.extras if ct else []):
            md = self.html_to_md(html)
            if md:
                out.append(f"**{name}** · {md}")
        return "\n\n".join(x for x in out if x.strip())

    def meta_for(self, info: CardInfo) -> str:
        names = self.cfg["flag_names"]
        parts = []
        if info.flag:
            parts.append(f"{C.FLAG_EMOJI.get(info.flag, '🚩')} {names.get(str(info.flag), '')}".strip())
        if info.marked:
            parts.append(f"{C.FLAG_EMOJI['marked']} {names.get('marked', 'Mark')}".strip())
        if not info.flag and not info.marked:
            parts.append(f"⚠ {names.get('0', '자동 포함')}")
        if len(info.cids or []) > 1:
            parts.append(f"카드 {len(info.cids)}장")
        if info.reps:
            parts.append(f"복습 {info.reps}회")
        if info.lapses:
            parts.append(f"실패 {info.lapses}회")
        if info.last_review:
            parts.append("마지막 " + datetime.fromtimestamp(info.last_review).strftime("%m-%d"))
        parts.append(f"`cid:{info.cid}`")
        return "> " + " · ".join(parts)

    def render_block(self, info: CardInfo) -> str:
        lines = [f"### {self.title_for(info)}", f"%% cid:{info.cid} nid:{info.nid} %%", "", self.body_for(info)]
        if self.cfg.get("show_meta", True):
            lines += ["", self.meta_for(info)]
        return "\n".join(lines).rstrip() + "\n"
