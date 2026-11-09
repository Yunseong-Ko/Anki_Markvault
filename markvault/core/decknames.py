"""덱 이름을 읽기 좋게: 공통 접두 덱 빼기, '03_' 번호·밑줄 정리, 단계별 제목 만들기."""
import re
from typing import Iterable, List

_RE_NUM = re.compile(r"^\d+[_.\-\s]+")


def pretty(seg: str) -> str:
    """'03_Non-Pacemaker_Action_Potential' → 'Non-Pacemaker Action Potential'"""
    s = _RE_NUM.sub("", seg.strip())
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or seg


def common_prefix(decks: Iterable[str], base: str = "") -> List[str]:
    """빼도 되는 앞부분. '이 덱만' 설정(base)이 있으면 그 덱까지, 없으면 모든 덱이 공유하는 앞부분
    (마지막 단계는 남긴다). 예: AnKing Step Deck::Bootcamp"""
    parts = [d.split("::") for d in decks]
    b = [x for x in (base or "").split("::") if x]
    if b and parts and all(p[: len(b)] == b and len(p) > len(b) for p in parts):
        return b
    if not parts:
        return []
    pre: List[str] = []
    for segs in zip(*parts):
        if all(s == segs[0] for s in segs):
            pre.append(segs[0])
        else:
            break
    shortest = min(len(p) for p in parts)
    return pre[: max(0, shortest - 1)]


def rel_parts(deck: str, prefix: List[str]) -> List[str]:
    segs = deck.split("::")
    return [pretty(s) for s in segs[len(prefix):]] or [pretty(segs[-1])]


def heading_levels(deck: str, prefix: List[str], max_levels: int = 3) -> List[str]:
    """제목 단계로 쓸 이름들. max_levels 를 넘는 깊은 단계는 마지막 단계에 ' › ' 로 합친다."""
    p = rel_parts(deck, prefix)
    if len(p) <= max_levels:
        return p
    return p[: max_levels - 1] + [" › ".join(p[max_levels - 1:])]
