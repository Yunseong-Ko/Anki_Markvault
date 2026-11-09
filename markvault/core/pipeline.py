"""한 번의 실행: 서명 비교 → 수집 → 변환 → 쓰기. GUI 없이도 호출 가능."""
import os
from typing import Optional

from . import config as C
from .collector import collect, signature
from .renderer import Renderer
from .writer import Result, Writer

_last_sig: Optional[str] = None


def run(col, user_cfg: dict, state_dir: str, force: bool = False) -> Optional[Result]:
    """바뀐 게 없으면 None. force=True 면 무조건 다시 씀."""
    global _last_sig
    cfg = C.merged(user_cfg)
    q = C.effective_query(cfg)
    sig = signature(col, q)
    # 출력 폴더가 없으면(지웠거나 처음) 서명이 같아도 다시 만든다
    if not force and sig == _last_sig and os.path.isdir(cfg["output_dir"]):
        return None
    cards = collect(col, q, cfg.get("extra_fields"))
    r = Renderer(cfg, col.media.dir(), cfg["output_dir"])
    w = Writer(cfg, r, state_dir=state_dir)
    res = w.write(cards)
    _last_sig = sig
    return res
