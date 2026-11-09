"""Markdown 파일 쓰기. 사용자 메모 보존, 변화 없으면 파일을 건드리지 않음, 해제 카드 보관, 주간 스냅샷."""
import json
import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List

from . import config as C
from .collector import CardInfo
from .renderer import Renderer

_RE_CID = re.compile(r"^%% cid:(\d+)(?: nid:(\d+))? %%\s*$", re.M)
_RE_STAMP = re.compile(r"갱신 \d{4}-\d{2}-\d{2} \d{2}:\d{2}")
_RE_MEMO_START = re.compile(r"^> \[!(?:note|memo|메모)\]", re.I)
HEADER_NOTE = "<!-- MarkVault 가 자동으로 만든 파일. 카드 블록은 다음 갱신 때 덮어써지지만 `> [!note]` 콜아웃은 cid 기준으로 보존됩니다. -->"
STATE_FILE = "state.json"


@dataclass
class Result:
    total: int = 0
    files_written: List[str] = field(default_factory=list)
    files_removed: List[str] = field(default_factory=list)
    removed_cards: int = 0
    new_cards: int = 0
    media_copied: int = 0

    total_cards: int = 0

    def summary(self) -> str:
        s = f"카드 {self.total_cards or self.total}장"
        if self.total_cards and self.total_cards != self.total:
            s += f"(노트 {self.total}개)"
        if self.new_cards:
            s += f" (+{self.new_cards})"
        if self.removed_cards:
            s += f" (−{self.removed_cards})"
        s += f", 파일 {len(self.files_written)}개 갱신" if self.files_written else ", 변화 없음"
        return s


def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "·", s).strip() or "_"


def parse_blocks(text: str) -> "OrderedDict[int, str]":
    """기존 파일에서 cid → 블록 본문(### 제목 포함) 을 뽑는다."""
    blocks: "OrderedDict[int, str]" = OrderedDict()
    lines = text.split("\n")
    # 각 블록은 '### ' 제목 줄에서 시작해 다음 '### ' / '## ' 전까지
    starts = [i for i, l in enumerate(lines) if l.startswith("### ")]
    for n, i in enumerate(starts):
        j = len(lines)
        for k in range(i + 1, len(lines)):
            if lines[k].startswith("### ") or lines[k].startswith("## "):
                j = k
                break
        seg = "\n".join(lines[i:j])
        m = _RE_CID.search(seg)
        if m:
            blocks[int(m.group(1))] = seg.rstrip()
            if m.group(2):  # nid 로도 찾을 수 있게
                blocks.setdefault(-int(m.group(2)), seg.rstrip())
    return blocks


def find_memo(memos: Dict[int, str], c: CardInfo) -> str:
    """메모는 노트(nid, 음수 키) → 대표 cid → 합쳐진 cid 순으로 찾는다."""
    return memos.get(-c.nid) or memos.get(c.cid) or next((memos[x] for x in (c.cids or []) if x in memos), "")


def extract_memo(block: str) -> str:
    """블록 안의 `> [!note]` 콜아웃(연속된 > 줄)을 원문 그대로 돌려준다. 없으면 ''."""
    lines = block.split("\n")
    for i, l in enumerate(lines):
        if _RE_MEMO_START.match(l):
            j = i + 1
            while j < len(lines) and lines[j].startswith(">"):
                j += 1
            return "\n".join(lines[i:j]).rstrip()
    return ""


class Writer:
    def __init__(self, cfg: dict, renderer: Renderer, state_dir: str):
        self.cfg = cfg
        self.r = renderer
        self.out = cfg["output_dir"]
        self.state_path = os.path.join(state_dir, STATE_FILE)
        self.state = self._load_state()

    # ---- state -------------------------------------------------------
    def _load_state(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
        st.setdefault("cards", {})
        st.setdefault("files", [])
        return st

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)

    # ---- 분류 --------------------------------------------------------
    def _file_for(self, info: CardInfo) -> List[str]:
        mode = self.cfg["split_by"]
        if mode == "flag":
            names = self.cfg["flag_names"]
            out = []
            for k in info.group_keys:
                emoji = C.FLAG_EMOJI.get(int(k) if k.isdigit() else k, "")
                out.append(_safe_name(f"{emoji} {names.get(k, k)}".strip()) + ".md")
            return out
        if mode == "deck":
            return [_safe_name(info.deck.split("::")[0]) + ".md"]
        return [_safe_name(self.cfg["single_file_name"]) + ".md"]

    # ---- 파일 내용 ---------------------------------------------------
    def _compose(self, cards: List[CardInfo], memos: Dict[int, str], title: str) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        parts = [HEADER_NOTE, f"# {title}", f"*{len(cards)}장 · 갱신 {now} · 검색식 `{C.effective_query(self.cfg)}`*", ""]
        by_deck: "OrderedDict[str, List[CardInfo]]" = OrderedDict()
        for c in cards:
            by_deck.setdefault(c.deck, []).append(c)
        for deck, cs in by_deck.items():
            parts.append("## " + deck.replace("::", " › "))
            parts.append("")
            for c in cs:
                block = self.r.render_block(c)
                memo = find_memo(memos, c)
                if memo:
                    block = block.rstrip() + "\n\n" + memo + "\n"
                parts.append(block)
        return "\n".join(parts).rstrip() + "\n"

    def _write_if_changed(self, path: str, content: str, res: Result):
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = f.read()
        if old is not None and _RE_STAMP.sub("", old) == _RE_STAMP.sub("", content):
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        res.files_written.append(os.path.relpath(path, self.out))

    # ---- 메인 --------------------------------------------------------
    def write(self, cards: List[CardInfo]) -> Result:
        res = Result(total=len(cards), total_cards=sum(len(c.cids or [c.cid]) for c in cards))
        os.makedirs(self.out, exist_ok=True)
        today = date.today().isoformat()

        # 파일별로 카드 묶기
        files: "OrderedDict[str, List[CardInfo]]" = OrderedDict()
        for c in cards:
            for fn in self._file_for(c):
                files.setdefault(fn, []).append(c)

        # 기존 파일에서 메모·블록 회수 (지금 추적 중인 파일 + 이번에 쓸 파일)
        old_blocks: Dict[int, str] = {}
        memos: Dict[int, str] = {}
        for fn in set(self.state["files"]) | set(files.keys()) | {"_해제됨.md"}:
            p = os.path.join(self.out, fn)
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    for cid, blk in parse_blocks(f.read()).items():
                        old_blocks.setdefault(cid, blk)
                        m = extract_memo(blk)
                        if m:
                            memos.setdefault(cid, m)

        # 추가/해제 집계
        cur = {c.cid for c in cards}
        known = {int(k) for k in self.state["cards"]}
        new_ids = cur - known
        removed_ids = known - cur
        res.new_cards, res.removed_cards = len(new_ids), len(removed_ids)
        for c in cards:
            ent = self.state["cards"].setdefault(str(c.cid), {"first_seen": today})
            ent["title"] = self.r.title_for(c)
            ent["deck"] = c.deck

        # 해제된 카드 보관
        if removed_ids and self.cfg.get("archive_removed"):
            arch = [f"\n## 해제 {today}\n"]
            for cid in sorted(removed_ids):
                blk = old_blocks.get(cid)
                if blk:
                    arch.append(blk + "\n")
                else:
                    ent = self.state["cards"].get(str(cid), {})
                    arch.append(f"### {ent.get('title', cid)}\n%% cid:{cid} %%\n\n(내용 없음)\n")
            p = os.path.join(self.out, "_해제됨.md")
            with open(p, "a", encoding="utf-8") as f:
                if f.tell() == 0:
                    f.write("# 플래그가 풀린 카드\n")
                f.write("\n".join(arch))
            res.files_written.append("_해제됨.md")
        for cid in removed_ids:
            self.state["cards"].pop(str(cid), None)

        # 본 파일들
        for fn, cs in files.items():
            title = os.path.splitext(fn)[0]
            self._write_if_changed(os.path.join(self.out, fn), self._compose(cs, memos, title), res)
        # 비어 버린(예: 그 색 플래그가 다 풀린) 추적 파일 삭제
        for fn in self.state["files"]:
            if fn not in files:
                p = os.path.join(self.out, fn)
                if os.path.exists(p):
                    # 메모가 남아 있으면 지우지 않고 비운 표시만
                    with open(p, encoding="utf-8") as f:
                        has_memo = any(extract_memo(b) for b in parse_blocks(f.read()).values())
                    if has_memo:
                        self._write_if_changed(p, HEADER_NOTE + f"\n# {os.path.splitext(fn)[0]}\n*0장 — 메모가 있어 파일은 남겨 둠*\n", res)
                    else:
                        os.remove(p)
                        res.files_removed.append(fn)
        self.state["files"] = list(files.keys())

        # 주간 스냅샷
        if self.cfg.get("weekly_snapshot"):
            self._weekly(cards, memos, res)

        # 목차 + 색인
        self._toc(cards, files, res)
        self._index(cards, files, res)
        self.state["last_run"] = datetime.now().isoformat(timespec="seconds")
        self._save_state()
        res.media_copied = self.r.copied
        return res

    def _weekly(self, cards, memos, res: Result):
        y, w, _ = date.today().isocalendar()
        key = f"{y}-W{w:02d}"
        wk = [c for c in cards
              if date.fromisoformat(self.state["cards"][str(c.cid)]["first_seen"]).isocalendar()[:2] == (y, w)]
        if not wk:
            return
        p = os.path.join(self.out, "_주간", key + ".md")
        self._write_if_changed(p, self._compose(wk, memos, f"{key} 새로 표시한 카드"), res)

    def _toc(self, cards, files, res: Result):
        """덱 트리 → 카드 제목 한 줄씩. 훅훅 넘겨보는 용도."""
        # 카드가 들어간 파일 이름 (제목 링크용)
        where: Dict[int, str] = {}
        for fn, cs in files.items():
            for c in cs:
                where.setdefault(c.cid, os.path.splitext(fn)[0])
        lines = [HEADER_NOTE, "# 목차", f"*총 {len(cards)}장 · 갱신 {datetime.now().strftime('%Y-%m-%d %H:%M')}*", ""]
        by_deck: "OrderedDict[str, List[CardInfo]]" = OrderedDict()
        for c in cards:
            by_deck.setdefault(c.deck, []).append(c)
        printed: List[str] = []
        for deck, cs in by_deck.items():
            parts = deck.split("::")
            for depth in range(len(parts)):
                prefix = parts[: depth + 1]
                if prefix != printed[: depth + 1]:
                    n = sum(len(v) for d, v in by_deck.items() if d.split("::")[: depth + 1] == prefix)
                    lines.append("    " * depth + f"- **{parts[depth]}** ({n}장)")
            printed = parts
            for c in cs:
                t = self.r.title_for(c)
                k = c.group_keys[0]
                mark = C.FLAG_EMOJI.get(int(k) if k.isdigit() else k, "")
                link = f"[[{where.get(c.cid, '')}#{t.replace('[', '').replace(']', '')}|{t}]]"
                extra = f" · 실패 {c.lapses}" if c.lapses else ""
                lines.append("    " * len(parts) + f"- {mark} {link}{extra}")
        self._write_if_changed(os.path.join(self.out, "_목차.md"), "\n".join(lines) + "\n", res)

    def _index(self, cards, files, res: Result):
        names = self.cfg["flag_names"]
        by_key = defaultdict(int)
        by_deck = defaultdict(int)
        for c in cards:
            for k in c.group_keys:
                by_key[k] += 1
            by_deck[c.deck.split("::")[0]] += 1
        lines = [HEADER_NOTE, "# Anki 복습 색인",
                 f"*총 {len(cards)}장 · 갱신 {datetime.now().strftime('%Y-%m-%d %H:%M')}*", "",
                 "## 파일"]
        for fn, cs in files.items():
            lines.append(f"- [[{os.path.splitext(fn)[0]}]] — {len(cs)}장")
        lines += ["", "## 표시별"]
        for k, n in sorted(by_key.items()):
            emoji = C.FLAG_EMOJI.get(int(k) if k.isdigit() else k, "")
            lines.append(f"- {emoji} {names.get(k, k)}: {n}장")
        lines += ["", "## 덱별"]
        for d, n in sorted(by_deck.items()):
            lines.append(f"- {d}: {n}장")
        self._write_if_changed(os.path.join(self.out, "_색인.md"), "\n".join(lines) + "\n", res)
