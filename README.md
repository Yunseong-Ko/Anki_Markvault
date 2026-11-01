# MarkVault

Anki 에서 플래그·Mark 를 단 카드를 **동기화 직후** Markdown 폴더로 자동으로 모아 주고, 원할 때 PDF 로 뽑아 주는 Anki 애드온. 어떤 덱·노트 유형이든 동작하며, AI 나 외부 서버를 쓰지 않는다.

## 설치
1. [Releases](../../releases) 에서 `markvault.ankiaddon` 내려받기 (또는 `./build_addon.sh` 로 직접 만들기)
2. Anki → 도구 → 추가 기능 → **파일에서 설치…** → 그 파일 선택 → Anki 재시작
3. 도구 → MarkVault → **지금 내보내기** → `~/Documents/Anki 복습/` 확인

## 사용
- 공부하며 빨간 플래그(Ctrl+1) 또는 Mark(Ctrl+K)
- 동기화 버튼을 누르면 끝난 직후 `복습 카드.md`·`_목차.md`·`_색인.md` 가 갱신된다 (Anki 를 열 때도 한 번)
- 카드 블록 아래에 `> [!note] 내 메모` 콜아웃을 적어 두면 다음 갱신에도 남는다
- 도구 → MarkVault → PDF / docx 로 내보내기… (범위: 전체·덱·이번 주·실패 N회 이상 / 모양: 읽기용·확인용·Anki 그대로)
- 설정: 검색식, 출력 폴더, 파일 나눔(하나·플래그 색별·덱별), Cloze 표시, 실행 시점

자세한 것은 [markvault/README.md](markvault/README.md), 설정 항목은 [markvault/config.md](markvault/config.md).

## 구조
- `markvault/__init__.py` — Anki 훅·메뉴 (Anki 와 연결되는 유일한 파일)
- `markvault/gui.py` — 설정창, PDF/docx 내보내기 창
- `markvault/core/` — 수집(collector) → 변환(renderer) → 쓰기(writer), PDF HTML(exporter). Anki 화면 없이 테스트 가능
- `markvault/vendor/` — markdownify 등 동봉 라이브러리
- `make_testcol.py`, `run_core.py` — 가짜 컬렉션으로 core 를 돌려 보는 개발용 스크립트 (`pip install anki`)

## 한계
- Image Occlusion 카드는 원본 이미지만 (가림막은 Anki 에서)
- docx 는 pandoc 필요. PDF 는 추가 설치 없음
- 아이패드에서 단 플래그는 데스크톱 Anki 가 동기화할 때 들어온다
