# MarkVault 설정
설정창(도구 → MarkVault → 설정…)에서 바꾸는 걸 권장합니다.

- `output_dir`: 출력 폴더. 비어 있으면 `~/Documents/Anki 복습`
- `query`: Anki 검색식. 기본 `flag:1 OR tag:marked`
- `auto_include_lapses`: 실패 N회 이상 카드 자동 포함 (0 = 끔)
- `split_by`: `none`(파일 하나) / `flag`(색별) / `deck`(최상위 덱별)
- `cloze_mode`: `highlight`(==빈칸== 한 줄) / `qa`(문제·정답 분리)
- `image_link_style`: `markdown` / `wikilink`
- `triggers`: `on_sync`(동기화 직후) / `on_profile_open`(Anki 열 때) / `on_change`(플래그 단 직후, 기본 꺼짐)
- `archive_removed`, `weekly_snapshot`, `show_meta`, `show_tooltip`
