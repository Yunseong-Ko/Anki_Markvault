"""MarkVault — 플래그·Mark 카드를 Markdown 폴더로 자동 내보내기.

Anki 화면과 연결되는 유일한 파일. 신호(훅) 받기, 디바운스, 메뉴, 설정창 호출.
실제 일은 core/ 가 한다.
"""
import os

from aqt import gui_hooks, mw
from aqt.operations import QueryOp
from aqt.qt import QAction, QMenu, QTimer, QDesktopServices, QUrl
from aqt.utils import showInfo, tooltip

from .core import config as C
from .core import pipeline

ADDON_DIR = os.path.dirname(__file__)
STATE_DIR = os.path.join(ADDON_DIR, "user_files")
_timer: QTimer = None
_running = False


# ---- 설정 ---------------------------------------------------------------
def get_cfg() -> dict:
    return mw.addonManager.getConfig(__name__) or {}


def save_cfg(cfg: dict):
    mw.addonManager.writeConfig(__name__, cfg)


# ---- 실행 ---------------------------------------------------------------
def run_export(force: bool = False, quiet: bool = False):
    """백그라운드에서 한 번 실행. 복습 화면은 멈추지 않는다."""
    global _running
    if _running or mw.col is None:
        return
    _running = True
    cfg = get_cfg()

    def op(col):
        return pipeline.run(col, cfg, STATE_DIR, force=force)

    def on_done(res):
        global _running
        _running = False
        if res is None:
            if not quiet:
                tooltip("MarkVault: 바뀐 게 없어요")
            return
        if C.merged(cfg).get("show_tooltip", True) or not quiet:
            tooltip(f"MarkVault: {res.summary()}", period=3000)

    def on_fail(exc):
        global _running
        _running = False
        showInfo(f"MarkVault 내보내기 실패:\n{exc}")

    QueryOp(parent=mw, op=op, success=on_done).failure(on_fail).run_in_background()


def schedule(delay_sec: float):
    """연달아 오는 신호를 모아 마지막 것만 처리 (디바운스)."""
    global _timer
    if _timer is None:
        _timer = QTimer(mw)
        _timer.setSingleShot(True)
        _timer.timeout.connect(lambda: run_export(quiet=True))
    _timer.start(int(delay_sec * 1000))


# ---- 훅 -----------------------------------------------------------------
def on_sync_finished():
    if C.merged(get_cfg())["triggers"].get("on_sync", True):
        schedule(1)


def on_profile_open():
    if C.merged(get_cfg())["triggers"].get("on_profile_open", True):
        schedule(5)


def on_operation(changes, handler):
    """플래그(changes.card) / Mark(changes.note, changes.tag) 변경. 기본은 꺼져 있음."""
    cfg = C.merged(get_cfg())
    if not cfg["triggers"].get("on_change", False):
        return
    if changes.card or changes.note or changes.tag:
        schedule(cfg.get("debounce_sec", 3))


# ---- 메뉴 ---------------------------------------------------------------
def open_folder():
    out = C.merged(get_cfg())["output_dir"]
    os.makedirs(out, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(out))


def open_settings():
    from .gui import SettingsDialog
    dlg = SettingsDialog(mw, get_cfg())
    if dlg.exec():
        save_cfg(dlg.result_cfg())
        run_export(force=True)


def open_export():
    from .gui import ExportDialog
    ExportDialog(mw, get_cfg(), STATE_DIR).exec()


def setup_menu():
    menu = QMenu("MarkVault", mw)
    a = QAction("지금 내보내기", mw)
    a.triggered.connect(lambda: run_export(force=True))
    menu.addAction(a)
    a = QAction("출력 폴더 열기", mw)
    a.triggered.connect(open_folder)
    menu.addAction(a)
    a = QAction("PDF / docx 로 내보내기…", mw)
    a.triggered.connect(open_export)
    menu.addAction(a)
    menu.addSeparator()
    a = QAction("설정…", mw)
    a.triggered.connect(open_settings)
    menu.addAction(a)
    mw.form.menuTools.addMenu(menu)


setup_menu()
gui_hooks.sync_did_finish.append(on_sync_finished)
gui_hooks.profile_did_open.append(on_profile_open)
gui_hooks.operation_did_execute.append(on_operation)
mw.addonManager.setConfigAction(__name__, open_settings)
