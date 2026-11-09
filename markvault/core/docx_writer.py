"""외부 프로그램 없이 .docx 만들기 (노트정리용).

구조: 덱 경로 → 제목 1/2/3 단계, 카드 제목 → 제목 4, 본문(굵게·기울임·Cloze 형광펜·목록·이미지),
메타 줄(작게, 회색), '내 메모' 칸(기존 메모가 있으면 채워서). Word 탐색 창에서 목차처럼 넘겨 볼 수 있다.
"""
import html as htmllib
import os
import re
import struct
import zipfile
from collections import OrderedDict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup, NavigableString, Tag

from .collector import CardInfo


def _find_memo(memos, c):
    return memos.get(-c.nid) or memos.get(c.cid) or next((memos[x] for x in (c.cids or []) if x in memos), "")
from .exporter import card_parts
from .renderer import _HR, _RE_IO, _RE_SOUND, Renderer

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MAX_IMG_CM = 15.0      # 본문 폭
EMU_PER_CM = 360000
_RE_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_RE_MATH = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
BLOCKS = {"div", "p", "li", "ul", "ol", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr"}


# ---- 이미지 크기 (PNG/JPEG/GIF 헤더만 읽음) ----------------------------------
def _img_size(path: str) -> Optional[Tuple[int, int]]:
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff":
                        b = f.read(1)
                    while b == b"\xff":
                        b = f.read(1)
                    if not b:
                        return None
                    marker = b[0]
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return w, h
                    seg = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg - 2, 1)
    except Exception:
        return None
    return None


class _Doc:
    def __init__(self, media_dir: str):
        self.media_dir = media_dir
        self.body: List[str] = []
        self.images: "OrderedDict[str, str]" = OrderedDict()   # 원본 파일명 → word/media/imageN.ext
        self.rels: List[Tuple[str, str]] = []                  # (rId, target)
        self._pic_id = 0

    # ---- 런(글자 조각) ----
    @staticmethod
    def run(text: str, b=False, i=False, u=False, hl=None, color=None, size=None) -> str:
        if not text:
            return ""
        rpr = ""
        if b:
            rpr += "<w:b/>"
        if i:
            rpr += "<w:i/>"
        if color:
            rpr += f'<w:color w:val="{color}"/>'
        if size:
            rpr += f'<w:sz w:val="{size}"/>'
        if hl:
            rpr += f'<w:highlight w:val="{hl}"/>'
        if u:
            rpr += '<w:u w:val="single"/>'
        rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
        return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(_RE_CTRL.sub("", text))}</w:t></w:r>'

    def para(self, runs: str, style: Optional[str] = None, numbered: bool = False, extra_ppr: str = "") -> None:
        ppr = ""
        if style:
            ppr += f'<w:pStyle w:val="{style}"/>'
        if numbered:
            ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        ppr += extra_ppr
        self.body.append(f"<w:p>{f'<w:pPr>{ppr}</w:pPr>' if ppr else ''}{runs}</w:p>")

    def image(self, name: str) -> str:
        src = os.path.join(self.media_dir, htmllib.unescape(name))
        if not os.path.exists(src):
            return self.run(f"[이미지 없음: {name}]", i=True, color="999999")
        if os.path.splitext(name)[1].lower() not in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
            return self.run(f"[그림: {name} — Word 에서 못 여는 형식]", i=True, color="999999")
        if name not in self.images:
            ext = os.path.splitext(name)[1].lower() or ".png"
            self.images[name] = f"media/image{len(self.images) + 1}{ext}"
            self.rels.append((f"rIdImg{len(self.images)}", self.images[name]))
        rid = next(r for r, t in self.rels if t == self.images[name])
        w, h = _img_size(src) or (800, 600)
        cm_w = min(MAX_IMG_CM, w / 96 * 2.54)
        cm_h = cm_w * h / max(w, 1)
        if cm_h > 12:                      # 너무 긴 그림은 높이로 제한
            cm_w, cm_h = cm_w * 12 / cm_h, 12
        cx, cy = int(cm_w * EMU_PER_CM), int(cm_h * EMU_PER_CM)
        self._pic_id += 1
        pid = self._pic_id
        return (
            '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{pid}" name="Picture {pid}"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{pid}" name="{escape(os.path.basename(name))}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rid}"/>'
            '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )

    # ---- HTML → 문단 ----
    def html(self, html: str, prefix_runs: str = "") -> None:
        html = _RE_SOUND.sub("", html)
        if "image-occlusion" in html:
            html = _RE_IO.sub("", html)
        html = _RE_MATH.sub(lambda m: (m.group(1) or m.group(2)).strip(), html)
        soup = BeautifulSoup(html, "html.parser")
        state = {"runs": prefix_runs, "list": None}

        def flush(numbered=False):
            if state["runs"].strip():
                self.para(state["runs"], style="ListParagraph" if numbered else None, numbered=numbered)
            state["runs"] = ""

        def walk(node, fmt):
            if isinstance(node, NavigableString):
                t = re.sub(r"\s+", " ", str(node))
                if t.strip() or (t == " " and state["runs"]):
                    state["runs"] += self.run(t, **fmt)
                return
            if not isinstance(node, Tag):
                return
            name = node.name.lower()
            if name in ("script", "style"):
                return
            cls = " ".join(node.get("class") or [])
            f = dict(fmt)
            if name in ("b", "strong"):
                f["b"] = True
            elif name in ("i", "em"):
                f["i"] = True
            elif name == "u":
                f["u"] = True
            elif name == "span" and "cloze" in cls.split():
                f["b"] = True
                f["hl"] = "yellow"
            if name == "br":
                flush()
                return
            if name == "img":
                src = node.get("src") or ""
                if src and "://" not in src and not src.startswith("data:"):
                    flush()
                    state["runs"] = self.image(src)
                    flush()
                return
            if name == "hr":
                flush()
                return
            if name == "li":
                flush()
                for c in node.children:
                    walk(c, f)
                flush(numbered=True)
                return
            block = name in BLOCKS
            if block:
                flush()
            for c in node.children:
                walk(c, f)
            if block:
                flush()

        for c in soup.children:
            walk(c, {})
        flush()


def _answer_part(info: CardInfo) -> str:
    parts = _HR.split(info.answer_html, maxsplit=1)
    return parts[1] if len(parts) == 2 else info.answer_html


def build_docx(cards: List[CardInfo], cfg: dict, r: Renderer, path: str, media_dir: str,
               memos: Optional[Dict[int, str]] = None, title: str = "Anki 복습") -> None:
    memos = memos or {}
    d = _Doc(media_dir)
    d.para(d.run(title), style="Title")
    d.para(d.run(f"카드 {sum(len(c.cids or [c.cid]) for c in cards)}장 · 노트 {len(cards)}개 · {datetime.now().strftime('%Y-%m-%d %H:%M')}", color="888888", size=18))

    printed: List[str] = []
    for c in cards:
        parts = c.deck.split("::")
        # 덱 경로: 바뀐 단계부터 제목 1~3 (3단계 넘으면 마지막 단계에 합쳐 붙임)
        levels = parts[:2] + ([" › ".join(parts[2:])] if len(parts) > 2 else [])
        for depth, name in enumerate(levels):
            if levels[: depth + 1] != printed[: depth + 1]:
                d.para(d.run(name), style=f"Heading{depth + 1}")
        printed = levels

        d.para(d.run(r.title_for(c)), style="Heading4")
        q_html, a_html, extras = card_parts(c, "read")
        if a_html is None:
            d.html(q_html)
        else:
            d.html(q_html, prefix_runs=d.run("Q. ", b=True, color="888888"))
            d.html(a_html, prefix_runs=d.run("A. ", b=True, color="888888"))
        for name, html in extras:
            d.html(html, prefix_runs=d.run(f"{name} · ", b=True, color="888888"))
        if cfg.get("show_meta", True):
            meta = r.meta_for(c).lstrip("> ").replace("`", "")
            d.para(d.run(meta, color="999999", size=16))
        # 내 메모 칸
        memo = _find_memo(memos, c)
        memo_lines = [l.lstrip(">").strip() for l in memo.split("\n")[1:]] if memo else []
        d.para(d.run("내 메모", b=True, color="5B8DEF", size=18), style="Memo")
        for line in (memo_lines or [""]):
            d.para(d.run(line), style="Memo")

    _write_package(d, path)


# ---- 패키지 ------------------------------------------------------------------
STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Apple SD Gothic Neo" w:hAnsi="Apple SD Gothic Neo" w:eastAsia="Apple SD Gothic Neo"/><w:sz w:val="21"/><w:lang w:eastAsia="ko-KR"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="2" w:color="333333"/></w:pBdr><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="220" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:color w:val="444444"/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:pBdr><w:top w:val="single" w:sz="4" w:space="6" w:color="DDDDDD"/></w:pBdr><w:spacing w:before="240" w:after="60"/><w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="400"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Memo"><w:name w:val="내 메모"/><w:basedOn w:val="Normal"/><w:pPr><w:pBdr><w:left w:val="single" w:sz="18" w:space="6" w:color="5B8DEF"/></w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="F3F6FB"/><w:spacing w:after="0"/><w:ind w:left="120" w:right="120"/></w:pPr></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W_NS}">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="400" w:hanging="200"/></w:pPr></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


def _write_package(d: _Doc, path: str) -> None:
    types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".svg": "image/svg+xml", ".webp": "image/webp", ".bmp": "image/bmp"}
    used = {os.path.splitext(t)[1] for t in d.images.values()}
    defaults = "".join(f'<Default Extension="{e[1:]}" ContentType="{types.get(e, "application/octet-stream")}"/>'
                       for e in sorted(used))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>' + defaults +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        "</Types>")
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>")
    rels = "".join(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{t}"/>'
                   for rid, t in d.rels)
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rIdNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
        + rels + "</Relationships>")
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_NS}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>'
        + "".join(d.body) +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1021" w:bottom="1134" w:left="1021" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/numbering.xml", NUMBERING)
        for name, target in d.images.items():
            z.write(os.path.join(d.media_dir, htmllib.unescape(name)), "word/" + target)
