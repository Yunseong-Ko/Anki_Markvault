"""설정창과 PDF/docx 내보내기 창 (Qt)."""
import os
from datetime import datetime

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                    QLabel, QLineEdit, QPushButton, QSpinBox, QUrl, QVBoxLayout, QWebEngineView, QTimer,
                    QPageLayout, QPageSize, QMarginsF, Qt)
from aqt.utils import showInfo, tooltip

from .core import config as C
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


class ExportDialog(QDialog):
    def __init__(self, parent, user_cfg: dict, state_dir: str):
        super().__init__(parent)
        self.setWindowTitle("PDF / docx 로 내보내기")
        self.cfg = C.merged(user_cfg)
        self.state_dir = state_dir
        self._view = None
        form = QFormLayout()

        self.scope = QComboBox()
        self.scope.addItems(["전체", "특정 덱", "이번 주 새로 표시한 카드", "실패 N회 이상"])
        form.addRow("범위", self.scope)
        self.deck = QComboBox()
        decks = sorted(d.name for d in mw.col.decks.all_names_and_ids())
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        self.status = QLabel("")
        lay.addWidget(self.status)
        lay.addWidget(buttons)
        self.scope.currentIndexChanged.connect(self._toggle)
        self._toggle()

    def _toggle(self):
        i = self.scope.currentIndex()
        self.deck.setEnabled(i == 1)
        self.min_lapses.setEnabled(i == 3)

    def _export(self):
        scope = ["all", "deck", "week", "lapses"][self.scope.currentIndex()]
        mode = ["read", "check"][self.mode.currentIndex()]
        is_pdf = self.fmt.currentIndex() == 0
        stamp = datetime.now().strftime("%Y%m%d")
        default = os.path.join(self.cfg["output_dir"], f"Anki 복습 {stamp}.{'pdf' if is_pdf else 'docx'}")
        path, _ = QFileDialog.getSaveFileName(self, "저장", default, "PDF (*.pdf)" if is_pdf else "Word (*.docx)")
        if not path:
            return
        self.status.setText("만드는 중…")
        cfg, state_dir = self.cfg, self.state_dir
        deck, min_l = self.deck.currentText(), self.min_lapses.value()

        def op(col):
            cards = collect(col, C.effective_query(cfg), cfg.get("extra_fields"))
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
            if is_pdf:
                base = mw.serverURL()
                head = (f"<script src='{base}_anki/js/mathjax.js'></script>"
                        f"<script src='{base}_anki/js/vendor/mathjax/tex-chtml.js'></script>")
                html = exporter.build_html(cards, cfg, r, mode, memos, media_dir=col.media.dir(), extra_head=head)
                return ("pdf", html, col.media.dir(), len(cards))
            # docx: 외부 프로그램 없이 직접 만든다
            from .core.docx_writer import build_docx
            err = None
            if cards:
                try:
                    build_docx(cards, cfg, r, path, col.media.dir(), memos,
                               title=os.path.splitext(os.path.basename(path))[0])
                except Exception as e:  # noqa: BLE001
                    err = f"docx 만들기 실패: {e}"
            return ("docx", err, None, len(cards))

        def done(result):
            kind, payload, media_dir, n = result
            if n == 0:
                self.status.setText("범위에 맞는 카드가 없어요.")
                return
            if kind == "docx":
                if payload:
                    showInfo(payload)
                    self.status.setText("")
                else:
                    tooltip(f"docx 저장: {n}장")
                    self.accept()
                return
            self._print_pdf(payload, media_dir, path, n)

        QueryOp(parent=self, op=op, success=done).run_in_background()

    def _print_pdf(self, html: str, media_dir: str, path: str, n: int):
        """Anki 에 내장된 브라우저 엔진으로 '인쇄'.
        setHtml() 은 2MB 가 넘으면 조용히 빈 페이지가 되므로, 임시 HTML 파일을 만들어 load() 한다."""
        self._html_path = os.path.splitext(path)[0] + ".html"
        with open(self._html_path, "w", encoding="utf-8") as f:
            f.write(html)
        self.status.setText(f"PDF 만드는 중… ({n}장, 카드가 많으면 1분 정도 걸려요)")
        self._view = QWebEngineView()
        self._view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._view.resize(800, 1100)
        self._view.show()
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                             QMarginsF(16, 18, 16, 18), QPageLayout.Unit.Millimeter)

        def finished(p, ok):
            self._view.deleteLater()
            self._view = None
            size = os.path.getsize(p) if ok and os.path.exists(p) else 0
            if ok and size > 2000:
                try:
                    os.remove(self._html_path)
                except OSError:
                    pass
                tooltip(f"PDF 저장: {n}장")
                self.accept()
            else:
                self.status.setText("PDF 가 비어 있어요. 같은 이름의 .html 파일을 브라우저로 열어 인쇄(⌘P)해 주세요.")

        def loaded(ok):
            if not ok:
                self._view.deleteLater()
                self._view = None
                self.status.setText("페이지를 못 열었어요. 같은 이름의 .html 파일을 브라우저로 열어 인쇄(⌘P)해 주세요.")
                return
            # 이미지·수식이 다 그려질 시간을 준다 (카드 수에 비례, 최대 10초)
            delay = min(10000, 1500 + n * 20)
            QTimer.singleShot(delay, lambda: self._view.page().printToPdf(path, layout))

        self._view.page().pdfPrintingFinished.connect(finished)
        self._view.loadFinished.connect(loaded)
        self._view.load(QUrl.fromLocalFile(self._html_path))
