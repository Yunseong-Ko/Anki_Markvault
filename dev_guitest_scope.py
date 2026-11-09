# 개발용: 설정창·내보내기 창의 덱 트리/조건/장수 표시를 offscreen 으로 점검 (testbig 필요: python3 make_bigcol.py)
import os, sys, types, importlib.util, time
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]="--no-sandbox"
import aqt.qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
app = QApplication(sys.argv)
pkg = types.ModuleType("markvault"); pkg.__path__ = [os.path.abspath("markvault")]; sys.modules["markvault"] = pkg
spec = importlib.util.spec_from_file_location("markvault.gui", "markvault/gui.py"); gui = importlib.util.module_from_spec(spec)
sys.modules["markvault.gui"] = gui; spec.loader.exec_module(gui)
gui.tooltip = lambda msg, **k: print("TOOLTIP:", msg)
from anki.collection import Collection
col = Collection("testbig/collection.anki2")
gui.mw = types.SimpleNamespace(col=col)
def runner(op, success, failure):
    def go():
        try: res = op(col)
        except Exception as e:
            import traceback; traceback.print_exc(); failure(e); return
        success(res)
    QTimer.singleShot(50, go)
# 설정창
sd = gui.SettingsDialog(None, {"deck_filter": "AnKing Step Deck::Bootcamp"}); sd.resize(620, 760); sd.show()
app.processEvents(); sd.grab().save("/tmp/settings.png"); print("settings selected:", sd.decks.selected())
# 내보내기 창
dlg = gui.ExportDialog(None, {"output_dir": os.path.abspath("outbig"), "deck_filter": ["AnKing Step Deck::Bootcamp"]},
                       os.path.abspath("outbig_state"), runner=runner, on_main=lambda fn: fn(), server_url=lambda: "http://x/")
dlg.resize(620, 720); dlg.show(); app.processEvents()
print("initial:", dlg.count.text(), dlg.decks.selected())
dlg.grab().save("/tmp/export0.png")
dlg.decks.set_all(False); app.processEvents(); print("none:", dlg.count.text())
it = dlg.decks._items
it["AnKing Step Deck::Bootcamp::Cardiology::03_Vascular_System"].setCheckState(0, Qt.CheckState.Checked)
it["AnKing Step Deck::B&B"].setCheckState(0, Qt.CheckState.Checked)
app.processEvents(); print("two decks:", dlg.count.text(), dlg.decks.selected())
dlg.use_lapses.setChecked(True); app.processEvents(); print("+lapses:", dlg.count.text())
dlg.use_lapses.setChecked(False); app.processEvents()
dlg.grab().save("/tmp/export1.png")
dlg.fmt.setCurrentIndex(0)
dlg.finished.connect(lambda r: (print("finished", r), app.quit()))
QTimer.singleShot(100, lambda: dlg._export("/tmp/sel.pdf"))
QTimer.singleShot(120000, app.quit); app.exec()
print("pdf:", os.path.getsize("/tmp/sel.pdf") if os.path.exists("/tmp/sel.pdf") else "없음")
col.close()
