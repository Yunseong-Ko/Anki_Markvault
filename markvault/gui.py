"""설정창과 PDF/docx 내보내기 창 (Qt)."""
import os
import random
import time
from datetime import datetime

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                    QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSpinBox, QUrl, QVBoxLayout,
                    QWebEngineView, QTimer, QPageLayout, QPageSize, QMarginsF, QWidget, Qt)
from aqt.utils import showInfo, tooltip

from .core import config as C
from .core import content as CT
from .core import exporter
from .core.collector import collect
from .core.renderer import Renderer
from .core.writer import Writer, extract_memo, parse_blocks


class SettingsDialog(QDialog):
    def __init__(self, parent, user_cfg: dict):
        super().__init__(parent)
        self.setWindowTitle("MarkVault 설정")
        self.setMinimumWidth(520)
        self.user_cfg = dict(user_cfg or {})
        cfg = C.merged(self.user_cfg)
        form = QFormLayout()

        self.out_dir = QLineEdit(cfg["output_dir"])
        btn = QPushButton("찾기…")
        btn.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.out_dir)
        row.addWidget(btn)
        form.addRow("출력 폴더", row)

        self.deck_filter = QComboBox()
        self.deck_filter.addItem("(전체 덱)")
        try:
            names = sorted(d.name for d in mw.col.decks.all_names_and_ids())
        except Exception:
            names = []
        self.deck_filter.addItems(names)
        cur = cfg.get("deck_filter") or ""
        if cur and cur in names:
            self.deck_filter.setCurrentText(cur)
        form.addRow("이 덱만 (하위 덱 포함)", self.deck_filter)

        self.query = QLineEdit(cfg["query"])
        form.addRow("검색식", self.query)
        form.addRow("", QLabel("<small>예: <code>flag:1 OR tag:marked</code> · 덱 한정: "
                               "<code>(flag:1 OR tag:marked) deck:국시*</code></small>"))

        self.lapses = QSpinBox()
        self.lapses.setRange(0, 50)
        self.lapses.setValue(int(cfg.get("auto_include_lapses") or 0))
        self.lapses.setSpecialValueText("끔")
        form.addRow("실패 N회 이상 자동 포함", self.lapses)

        self.extra = QLineEdit(", ".join(cfg.get("extra_fields") or []))
        form.addRow("본문에 덧붙일 필드", self.extra)
        form.addRow("", QLabel("<small>쉼표로 구분. 여기 없는 필드(예: AnKing 의 Sketchy, Boards and Beyond)는 빠져요.</small>"))

        self.split = QComboBox()
        self.split.addItems(["파일 하나", "플래그 색별 파일", "최상위 덱별 파일"])
        self.split.setCurrentIndex({"none": 0, "flag": 1, "deck": 2}.get(cfg["split_by"], 0))
        form.addRow("파일 나눔", self.split)

        self.cloze = QComboBox()
        self.cloze.addItems(["빈칸을 ==형광펜== 으로, 한 줄", "문제 / 정답 분리"])
        self.cloze.setCurrentIndex(0 if cfg["cloze_mode"] == "highlight" else 1)
        form.addRow("Cloze 표시", self.cloze)

        self.img = QComboBox()
        self.img.addItems(["일반 Markdown  ![](_media/x.png)", "옵시디언  ![[_media/x.png]]"])
        self.img.setCurrentIndex(0 if cfg["image_link_style"] == "markdown" else 1)
        form.addRow("이미지 링크", self.img)

        t = cfg["triggers"]
        self.on_sync = QCheckBox("동기화가 끝난 직후")
        self.on_sync.setChecked(t.get("on_sync", True))
        self.on_open = QCheckBox("Anki 를 열 때")
        self.on_open.setChecked(t.get("on_profile_open", True))
        self.on_change = QCheckBox("플래그·Mark 를 단 직후 (3초 모아서)")
        self.on_change.setChecked(t.get("on_change", False))
        box = QVBoxLayout()
        for w in (self.on_sync, self.on_open, self.on_change):
            box.addWidget(w)
        form.addRow("언제 실행", box)

        self.archive = QCheckBox("플래그가 풀린 카드를 _해제됨.md 에 보관")
        self.archive.setChecked(cfg.get("archive_removed", False))
        self.weekly = QCheckBox("주간 스냅샷 _주간/ 만들기")
        self.weekly.setChecked(cfg.get("weekly_snapshot", False))
        self.meta = QCheckBox("카드 아래 메타 줄(복습·실패 횟수) 표시")
        self.meta.setChecked(cfg.get("show_meta", True))
        self.tip = QCheckBox("실행 후 작은 알림 표시")
        self.tip.setChecked(cfg.get("show_tooltip", True))
        box = QVBoxLayout()
        for w in (self.archive, self.weekly, self.meta, self.tip):
            box.addWidget(w)
        form.addRow("기타", box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("<small>저장하면 바로 한 번 내보내요.</small>"))
        lay.addWidget(buttons)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "출력 폴더", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def result_cfg(self) -> dict:
        cfg = dict(self.user_cfg)
        cfg["output_dir"] = self.out_dir.text().strip()
        cfg["query"] = self.query.text().strip() or C.DEFAULTS["query"]
        cfg["deck_filter"] = "" if self.deck_filter.currentIndex() == 0 else self.deck_filter.currentText()
        cfg["auto_include_lapses"] = self.lapses.value()
        cfg["extra_fields"] = [x.strip() for x in self.extra.text().split(",") if x.strip()]
        cfg["split_by"] = ["none", "flag", "deck"][self.split.currentIndex()]
        cfg["cloze_mode"] = "highlight" if self.cloze.currentIndex() == 0 else "qa"
        cfg["image_link_style"] = "markdown" if self.img.currentIndex() == 0 else "wikilink"
        cfg["triggers"] = {"on_sync": self.on_sync.isChecked(), "on_profile_open": self.on_open.isChecked(),
                           "on_change": self.on_change.isChecked()}
        cfg["archive_removed"] = self.archive.isChecked()
        cfg["weekly_snapshot"] = self.weekly.isChecked()
        cfg["show_meta"] = self.meta.isChecked()
        cfg["show_tooltip"] = self.tip.isChecked()
        return cfg


PREVIEW_CSS = """
QFrame#mvPreview { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }
QLabel#mvDeck { color: gray; font-size: 11px; }
QLabel#mvQ { font-size: 14px; }
QLabel#mvA { font-size: 14px; color: #1a7f37; }
"""


class ExportDialog(QDialog):
    """범위·모양·형식을 고르고 저장. 만드는 동안 진행 상황과 카드 미리보기를 보여 준다."""

    def __init__(self, parent, user_cfg: dict, state_dir: str, runner=None, on_main=None, server_url=None):
        super().__init__(parent)
        self.setWindowTitle("PDF / docx 로 내보내기")
        self.setMinimumWidth(520)
        self.cfg = C.merged(user_cfg)
        self.state_dir = state_dir
        self._view = None
        self._cards = []
        self._t0 = 0.0
        # 테스트에서 바꿔 끼울 수 있게: 백그라운드 실행기, 메인 스레드 호출기, Anki 내장 서버 주소
        self._runner = runner or self._query_op
        self._on_main = on_main or (lambda fn: mw.taskman.run_on_main(fn))
        self._server_url = server_url or (lambda: mw.serverURL())
        self.setStyleSheet(PREVIEW_CSS)

        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItems(["전체", "특정 덱", "이번 주 새로 표시한 카드", "실패 N회 이상"])
        form.addRow("범위", self.scope)
        self.deck = QComboBox()
        try:
            decks = sorted(d.name for d in mw.col.decks.all_names_and_ids())
        except Exception:
            decks = []
        self.deck.addItems(decks)
        form.addRow("덱", self.deck)
        self.min_lapses = QSpinBox()
        self.min_lapses.setRange(1, 50)
        self.min_lapses.setValue(3)
        form.addRow("실패 N회", self.min_lapses)
        self.mode = QComboBox()
        self.mode.addItems(["읽기용 — 정답 바로 보임", "확인용 — 빈칸·문제만, 정답은 마지막 장"])
        form.addRow("모양", self.mode)
        self.fmt = QComboBox()
        self.fmt.addItems(["PDF — 쭉 읽기용", "Word (docx) — 노트정리용, 편집 가능"])
        form.addRow("형식", self.fmt)
        self.form_box = QWidget()
        self.form_box.setLayout(form)

        # ---- 진행 패널 (처음엔 숨김) ----
        self.progress_box = QWidget()
        pl = QVBoxLayout(self.progress_box)
        pl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.stage = QLabel("")
        self.elapsed = QLabel("")
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(self.stage)
        row.addWidget(self.elapsed)
        pl.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        pl.addWidget(self.bar)
        self.preview = QFrame()
        self.preview.setObjectName("mvPreview")
        vl = QVBoxLayout(self.preview)
        vl.setContentsMargins(14, 10, 14, 12)
        self.pv_head = QLabel("기다리는 동안 한 장 볼까요?")
        self.pv_head.setObjectName("mvDeck")
        self.pv_deck = QLabel("")
        self.pv_deck.setObjectName("mvDeck")
        self.pv_q = QLabel("")
        self.pv_q.setObjectName("mvQ")
        self.pv_a = QLabel("")
        self.pv_a.setObjectName("mvA")
        for w in (self.pv_deck, self.pv_q, self.pv_a):
            w.setWordWrap(True)
        for w in (self.pv_head, self.pv_deck, self.pv_q, self.pv_a):
            vl.addWidget(w)
        self.preview.setMinimumHeight(170)
        self.preview.hide()
        pl.addWidget(self.preview)
        self.progress_box.hide()

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._export)
        self.buttons.rejected.connect(self._cancel)
        lay = QVBoxLayout(self)
        lay.addWidget(self.form_box)
        lay.addWidget(self.progress_box)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)
        self.scope.currentIndexChanged.connect(self._toggle)
        self._toggle()

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_elapsed)
        self._pv_timer = QTimer(self)
        self._pv_timer.timeout.connect(self._preview_step)
        self._pv_phase = 0

    # ---- 기본 실행기: Anki 의 백그라운드 작업 ----
    def _query_op(self, op, success, failure):
        QueryOp(parent=self, op=op, success=success).failure(failure).run_in_background()

    def _toggle(self):
        i = self.scope.currentIndex()
        self.deck.setEnabled(i == 1)
        self.min_lapses.setEnabled(i == 3)

    def _cancel(self):
        self._stop_ui()
        self.reject()

    # ---- 진행 표시 ----
    def _start_ui(self):
        self.form_box.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.status.setText("")
        self.progress_box.show()
        self._t0 = time.time()
        self._tick.start(500)
        self._update_elapsed()

    def _stop_ui(self):
        self._tick.stop()
        self._pv_timer.stop()

    def _set_stage(self, text: str, value: int = -1, maximum: int = 0):
        self.stage.setText(text)
        if value < 0:
            self.bar.setRange(0, 0)          # 끝을 모를 때: 왔다갔다 하는 막대
        else:
            self.bar.setRange(0, max(maximum, 1))
            self.bar.setValue(value)

    def _update_elapsed(self):
        self.elapsed.setText(f"{int(time.time() - self._t0)}초")

    def _start_preview(self):
        if not self._cards:
            return
        self.preview.show()
        self._pv_phase = 0
        self._preview_step()

    def _preview_step(self):
        """새 카드(빈칸 가림) 4초 → 정답 공개 3초 → 새 카드 …"""
        if not self._cards:
            return
        self._pv_timer.start(4000 if self._pv_phase % 2 == 0 else 3000)
        if self._pv_phase % 2 == 0:
            c = random.choice(self._cards)
            q, a = CT.preview(c.content, c.ords or [c.ord])
            self._pv_cur = (c, q, a)
            self.pv_deck.setText(c.deck.replace("::", " › "))
            self.pv_q.setText(q or self._title(c))
            self.pv_a.setText("")
        else:
            c, q, a = self._pv_cur
            if a and a != q:
                self.pv_a.setText(a if c.is_cloze else f"→ {a}")
        self._pv_phase += 1

    @staticmethod
    def _title(c):
        return (c.content.title if c.content else "") or "(내용 없음)"

    def _fail(self, msg: str):
        self._stop_ui()
        self.form_box.setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        self.progress_box.hide()
        self.status.setText(msg)

    # ---- 내보내기 ----
    def _export(self, path: str = ""):
        scope = ["all", "deck", "week", "lapses"][self.scope.currentIndex()]
        mode = ["read", "check"][self.mode.currentIndex()]
        is_pdf = self.fmt.currentIndex() == 0
        if not path:
            stamp = datetime.now().strftime("%Y%m%d")
            default = os.path.join(self.cfg["output_dir"], f"Anki 복습 {stamp}.{'pdf' if is_pdf else 'docx'}")
            path, _ = QFileDialog.getSaveFileName(self, "저장", default, "PDF (*.pdf)" if is_pdf else "Word (*.docx)")
            if not path:
                return
        self._start_ui()
        self._set_stage("카드 모으는 중…", 0, 1)
        cfg, state_dir = self.cfg, self.state_dir
        deck, min_l = self.deck.currentText(), self.min_lapses.value()

        def progress(i, n):
            self._on_main(lambda: self._set_stage(f"카드 모으는 중… {i}/{n}", i, n))

        # 1단계: 카드 모으기 (빨리 끝남) → 미리보기 시작
        def op_collect(col):
            cards = collect(col, C.effective_query(cfg), cfg.get("extra_fields"), progress=progress)
            r = Renderer(cfg, col.media.dir(), cfg["output_dir"])
            w = Writer(cfg, r, state_dir=state_dir)
            cards = exporter.filter_cards(cards, scope, deck, min_l, w.state.get("cards"))
            memos = {}
            for fn in w.state.get("files", []):
                p = os.path.join(cfg["output_dir"], fn)
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as f:
                        for cid, blk in parse_blocks(f.read()).items():
                            m = extract_memo(blk)
                            if m:
                                memos.setdefault(cid, m)
            return cards, memos, r, col.media.dir()

        def collected(result):
            cards, memos, r, media_dir = result
            if not cards:
                self._fail("범위에 맞는 카드가 없어요.")
                return
            self._cards = cards
            self._start_preview()
            n_cards = sum(len(c.cids or [c.cid]) for c in cards)
            self._set_stage(f"{'PDF' if is_pdf else 'Word'} 문서 만드는 중… (카드 {n_cards}장)")
            base = self._server_url()
            head = (f"<script src='{base}_anki/js/mathjax.js'></script>"
                    f"<script src='{base}_anki/js/vendor/mathjax/tex-chtml.js'></script>")

            # 2단계: 문서 만들기 (백그라운드)
            def op_build(_col):
                if is_pdf:
                    return exporter.build_html(cards, cfg, r, mode, memos, media_dir=media_dir, extra_head=head)
                from .core.docx_writer import build_docx
                build_docx(cards, cfg, r, path, media_dir, memos,
                           title=os.path.splitext(os.path.basename(path))[0])
                return None

            def built(html):
                if is_pdf:
                    self._print_pdf(html, path, n_cards)
                else:
                    self._done(f"Word 저장: 카드 {n_cards}장", path)

            self._runner(op_build, built, lambda e: self._fail(f"문서 만들기 실패: {e}"))

        self._runner(op_collect, collected, lambda e: self._fail(f"카드 모으기 실패: {e}"))

    def _done(self, msg: str, path: str):
        self._stop_ui()
        self.done_path = path
        tooltip(msg, period=4000)
        self.accept()

    def _print_pdf(self, html: str, path: str, n: int):
        """Anki 에 내장된 브라우저 엔진으로 '인쇄'.
        setHtml() 은 2MB 가 넘으면 조용히 빈 페이지가 되므로, 임시 HTML 파일을 만들어 load() 한다."""
        self._html_path = os.path.splitext(path)[0] + ".html"
        with open(self._html_path, "w", encoding="utf-8") as f:
            f.write(html)
        self._set_stage("페이지 그리는 중…", 0, 100)
        self._view = QWebEngineView()
        self._view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._view.resize(800, 1100)
        self._view.show()
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                             QMarginsF(16, 18, 16, 18), QPageLayout.Unit.Millimeter)

        def finished(p, ok):
            if self._view is not None:
                self._view.deleteLater()
                self._view = None
            size = os.path.getsize(p) if ok and os.path.exists(p) else 0
            if ok and size > 2000:
                try:
                    os.remove(self._html_path)
                except OSError:
                    pass
                self._done(f"PDF 저장: 카드 {n}장", p)
            else:
                self._fail("PDF 가 비어 있어요. 같은 이름의 .html 파일을 브라우저로 열어 인쇄(⌘P)해 주세요.")

        def loaded(ok):
            if not ok:
                self._fail("페이지를 못 열었어요. 같은 이름의 .html 파일을 브라우저로 열어 인쇄(⌘P)해 주세요.")
                return
            self._set_stage(f"PDF 로 인쇄하는 중… (카드 {n}장, 1분 정도 걸릴 수 있어요)")
            # 이미지·수식이 다 그려질 시간을 준다 (카드 수에 비례, 최대 10초)
            delay = min(10000, 1500 + n * 5)
            QTimer.singleShot(delay, lambda: self._view and self._view.page().printToPdf(path, layout))

        self._view.loadProgress.connect(lambda v: self._set_stage("페이지 그리는 중…", v, 100))
        self._view.page().pdfPrintingFinished.connect(finished)
        self._view.loadFinished.connect(loaded)
        self._view.load(QUrl.fromLocalFile(self._html_path))
