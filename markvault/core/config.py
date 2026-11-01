"""기본 설정값과 병합 로직."""
import copy
import os

DEFAULTS = {
    # 출력 폴더. 비어 있으면 ~/Documents/Anki 복습
    "output_dir": "",
    # Anki 검색식
    "query": "flag:1 OR tag:marked",
    # none | flag | deck  — 파일을 어떻게 나눌지
    "split_by": "none",
    "single_file_name": "복습 카드",
    # 플래그 번호 → 표시 이름. "marked" 는 Mark(태그 marked)
    "flag_names": {
        "1": "빨강", "2": "주황", "3": "초록", "4": "파랑",
        "5": "분홍", "6": "청록", "7": "보라", "marked": "Mark", "0": "자동 포함",
    },
    # highlight: 정답 한 줄, 빈칸을 ==…== 로 / qa: 문제·정답 분리
    "cloze_mode": "highlight",
    # markdown: ![](_media/x.png) / wikilink: ![[_media/x.png]]
    "image_link_style": "markdown",
    # 사용자 결정: 공부 중엔 건드리지 않게 플래그 직후 실행은 기본 꺼짐, 동기화 직후가 기준
    "triggers": {"on_change": False, "on_sync": True, "on_profile_open": True},
    # 실패 N회 이상 카드 자동 포함 (0 = 끔) → 검색식에 OR prop:lapses>=N
    "auto_include_lapses": 0,
    "debounce_sec": 3,
    # 플래그가 풀린 카드를 _해제됨.md 에 남길지
    "archive_removed": False,
    # _주간/YYYY-Www.md — 그 주에 새로 추가된 카드 모음
    "weekly_snapshot": False,
    # 카드 아래 메타 줄(복습 횟수, 마지막 복습 등)
    "show_meta": True,
    "show_tooltip": True,
}

FLAG_EMOJI = {1: "🔴", 2: "🟠", 3: "🟢", 4: "🔵", 5: "🩷", 6: "🩵", 7: "🟣", "marked": "⭐", 0: "⚠", "0": "⚠"}


def effective_query(cfg) -> str:
    """검색식 + (옵션) 실패 N회 이상 자동 포함."""
    q = cfg["query"]
    n = int(cfg.get("auto_include_lapses") or 0)
    if n > 0:
        q = f"({q}) OR prop:lapses>={n}"
    return q


def merged(user_cfg):
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in (user_cfg or {}).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if not cfg["output_dir"]:
        cfg["output_dir"] = os.path.join(os.path.expanduser("~"), "Documents", "Anki 복습")
    cfg["output_dir"] = os.path.expanduser(cfg["output_dir"])
    return cfg
