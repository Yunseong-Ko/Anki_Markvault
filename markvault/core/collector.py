"""검색식에 맞는 카드와 메타데이터 수집. 빠른 변경 감지용 서명도 만든다."""
import hashlib
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import content as CT


@dataclass
class CardInfo:
    cid: int
    nid: int
    deck: str            # 전체 덱 경로 "국시::순환기::심부전"
    flag: int            # 0~7
    marked: bool
    notetype: str
    is_cloze: bool
    ord: int
    reps: int
    lapses: int
    ivl: int
    last_review: Optional[float]   # epoch seconds
    tags: List[str] = field(default_factory=list)
    question_html: str = ""      # 템플릿으로 그린 것 (필드에서 못 뽑을 때만 채움)
    answer_html: str = ""
    css: str = ""
    content: Optional[CT.Content] = None   # 필드에서 뽑은 본문
    ords: List[int] = field(default_factory=list)   # 합쳐진 카드들의 번호 (cloze 강조용)
    cids: List[int] = field(default_factory=list)   # 합쳐진 카드들

    @property
    def group_keys(self):
        """이 카드가 속하는 분류(플래그 번호 또는 'marked'). 둘 다일 수 있음."""
        keys = []
        if self.flag:
            keys.append(str(self.flag))
        if self.marked:
            keys.append("marked")
        return keys or ["0"]


def signature(col, query: str) -> str:
    """플래그/Mark 대상 집합과 그 노트들의 수정 시각으로 만든 서명.
    복습 중 매 답변마다 호출되므로 가볍게: SQL 두 번."""
    ids = sorted(col.find_cards(query))
    if not ids:
        return "empty"
    max_mod = 0
    # 노트 본문이 바뀐 것도 잡기 위해 notes.mod, 카드 상태(플래그 등)는 cards.mod
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        ph = ",".join("?" * len(chunk))
        m = col.db.scalar(
            f"select max(max(c.mod), max(n.mod)) from cards c join notes n on n.id=c.nid where c.id in ({ph})",
            *chunk,
        ) or 0
        max_mod = max(max_mod, m)
    h = hashlib.sha1()
    h.update(",".join(map(str, ids)).encode())
    h.update(str(max_mod).encode())
    return h.hexdigest()


def collect(col, query: str, extra_fields: Optional[List[str]] = None) -> List[CardInfo]:
    out = []
    for cid in col.find_cards(query):
        card = col.get_card(cid)
        note = card.note()
        nt = card.note_type()
        try:
            ct = CT.build(note, nt, card.ord, extra_fields)
        except Exception:  # 이상한 노트 유형이어도 멈추지 않음
            ct = CT.Content(kind="template")
        q = a = css = ""
        if CT.is_empty(ct.question_html):
            # 필드에서 못 뽑았으면 템플릿 결과를 쓴다
            ct.kind = "template"
            try:
                r = card.render_output()
                q, a, css = CT.clean(r.question_text), CT.clean(r.answer_text), r.css
            except Exception as e:
                q, a = "", f"(렌더 실패: {e})"
            ct.title = CT.first_line(q) or ct.title
        last = col.db.scalar("select max(id) from revlog where cid=?", cid)
        out.append(CardInfo(
            cid=cid, nid=note.id,
            deck=col.decks.name(card.odid or card.did),
            flag=card.user_flag(), marked=note.has_tag("marked"),
            notetype=nt["name"], is_cloze=(nt.get("type") == 1),
            ord=card.ord, reps=card.reps, lapses=card.lapses, ivl=card.ivl,
            last_review=(last / 1000) if last else None,
            tags=list(note.tags),
            question_html=q, answer_html=a, css=css, content=ct,
        ))
    # 덱 경로 → 노트 생성순 → 카드 순서
    out.sort(key=lambda c: (c.deck.lower(), c.nid, c.ord))
    return merge_siblings(out)


def merge_siblings(cards: List[CardInfo]) -> List[CardInfo]:
    """같은 노트의 카드(c1, c2 …)는 한 블록으로. 대표 cid 는 가장 작은 것."""
    merged: "dict[int, CardInfo]" = {}
    order = []
    for c in cards:
        c.ords = c.ords or [c.ord]
        c.cids = c.cids or [c.cid]
        g = merged.get(c.nid)
        if g is None:
            merged[c.nid] = c
            order.append(c.nid)
            continue
        g.ords.append(c.ord)
        g.cids.append(c.cid)
        g.flag = g.flag or c.flag
        g.reps = max(g.reps, c.reps)
        g.lapses = max(g.lapses, c.lapses)
        if c.last_review and (not g.last_review or c.last_review > g.last_review):
            g.last_review = c.last_review
    out = [merged[n] for n in order]
    for g in out:
        g.cid = min(g.cids)
    return out
