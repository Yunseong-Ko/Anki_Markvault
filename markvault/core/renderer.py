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
from .collector import CardInfo

from markdownify import MarkdownConverter  # noqa: E402  (vendor path 는 core/__init__ 에서)


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
        md = re.sub(r"\n{3,}", "\n\n", md).strip()
        if is_io:
            md += "\n\n*(Image Occlusion 카드 — 가림막은 Anki 에서 확인)*"
        return md

    # ---- 카드 한 장 ----------------------------------------------------
    def _split_qa(self, info: CardInfo):
        """answer_text 는 보통 '문제 <hr id=answer> 정답'. 갈라서 정답 부분만 얻는다."""
        parts = _HR.split(info.answer_html, maxsplit=1)
        if len(parts) == 2:
            return info.question_html, parts[1]
        return info.question_html, info.answer_html

    def title_for(self, info: CardInfo) -> str:
        if info.is_cloze:
            src = _RE_CLOZE.sub(lambda m: m.group(1), _HR.split(info.answer_html)[-1])
            src = _RE_CLOZE_INACTIVE.sub(lambda m: m.group(1), src)
        else:
            src = info.question_html
        # 첫 줄만 제목으로
        src = re.split(r"<br\s*/?>|<div\b|<p\b|<li\b|<hr\b|\n", src, maxsplit=1)[0]
        t = _plain(src)
        t = t.replace("[...]", "…")
        return (t[:70] + "…") if len(t) > 70 else (t or "(제목 없음)")

    def body_for(self, info: CardInfo) -> str:
        q_html, a_html = self._split_qa(info)
        if info.is_cloze and self.cfg["cloze_mode"] == "highlight":
            a = _RE_CLOZE.sub(lambda m: f"=={m.group(1)}==", a_html)
            a = _RE_CLOZE_INACTIVE.sub(lambda m: m.group(1), a)
            return self.html_to_md(a)
        if info.is_cloze:
            q = _RE_CLOZE_INACTIVE.sub(lambda m: m.group(1), q_html)
            a = _RE_CLOZE.sub(lambda m: f"**{m.group(1)}**", a_html)
            a = _RE_CLOZE_INACTIVE.sub(lambda m: m.group(1), a)
            return f"**Q.** {self.html_to_md(q)}\n\n**A.** {self.html_to_md(a)}"
        q_md, a_md = self.html_to_md(q_html), self.html_to_md(a_html)
        if not a_md:
            return q_md
        return f"**Q.** {q_md}\n\n**A.** {a_md}"

    def meta_for(self, info: CardInfo) -> str:
        names = self.cfg["flag_names"]
        parts = []
        if info.flag:
            parts.append(f"{C.FLAG_EMOJI.get(info.flag, '🚩')} {names.get(str(info.flag), '')}".strip())
        if info.marked:
            parts.append(f"{C.FLAG_EMOJI['marked']} {names.get('marked', 'Mark')}".strip())
        if not info.flag and not info.marked:
            parts.append(f"⚠ {names.get('0', '자동 포함')}")
        if info.reps:
            parts.append(f"복습 {info.reps}회")
        if info.lapses:
            parts.append(f"실패 {info.lapses}회")
        if info.last_review:
            parts.append("마지막 " + datetime.fromtimestamp(info.last_review).strftime("%m-%d"))
        parts.append(f"`cid:{info.cid}`")
        return "> " + " · ".join(parts)

    def render_block(self, info: CardInfo) -> str:
        lines = [f"### {self.title_for(info)}", f"%% cid:{info.cid} %%", "", self.body_for(info)]
        if self.cfg.get("show_meta", True):
            lines += ["", self.meta_for(info)]
        return "\n".join(lines).rstrip() + "\n"
