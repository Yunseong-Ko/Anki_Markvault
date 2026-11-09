# 개발용: 내보내기 창을 Anki 없이 화면 밖(offscreen)에서 띄워 끝까지 돌려 본다.
# 사용: python3 dev_guitest.py <collection.anki2> <0=PDF|1=docx> <저장 경로> <스크린샷 접두어>
import os, sys, types, importlib.util, time
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]="--no-sandbox"
import aqt.qt  # noqa (QtWebEngine 먼저)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv)
# markvault/__init__.py(Anki 메뉴 등록)를 건너뛰고 gui 만 불러오기
pkg = types.ModuleType("markvault"); pkg.__path__ = [os.path.abspath("markvault")]; sys.modules["markvault"] = pkg
spec = importlib.util.spec_from_file_location("markvault.gui", "markvault/gui.py"); gui = importlib.util.module_from_spec(spec)
sys.modules["markvault.gui"] = gui; spec.loader.exec_module(gui)
gui.tooltip = lambda msg, **k: print("TOOLTIP:", msg)
from anki.collection import Collection
col = Collection(sys.argv[1]); fmt = int(sys.argv[2]); out = sys.argv[3]; shots = sys.argv[4]
def runner(op, success, failure):
    def go():
        try: res = op(col)
        except Exception as e:
            import traceback; traceback.print_exc(); failure(e); return
        success(res)
    QTimer.singleShot(50, go)
gui.mw = types.SimpleNamespace(col=col)
dlg = gui.ExportDialog(None, {"output_dir": os.path.abspath("outbig")}, os.path.abspath("outbig_state"),
                       runner=runner, on_main=lambda fn: fn(), server_url=lambda: "http://127.0.0.1:9/")
dlg.fmt.setCurrentIndex(fmt); dlg.resize(560, 420); dlg.show()
t0 = time.time()
for i, ms in enumerate([300, 3000, 6000, 9000]):
    QTimer.singleShot(ms, lambda i=i: (dlg.grab().save(f"{shots}_{i}.png"), print("shot", i, dlg.stage.text(), dlg.elapsed.text())))
dlg.finished.connect(lambda r: (print("dialog finished", r, round(time.time()-t0,1), "s", "status:", dlg.status.text()), app.quit()))
QTimer.singleShot(100, lambda: dlg._export(out))
QTimer.singleShot(240000, lambda: (print("TIMEOUT", dlg.stage.text(), dlg.status.text()), app.quit()))
app.exec()
print("file:", out, os.path.getsize(out) if os.path.exists(out) else "없음")
col.close()
