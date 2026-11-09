import sys, time, re; sys.path.insert(0,"markvault")
import core
from anki.collection import Collection
from core import config as C, collector, exporter, pipeline
from core.renderer import Renderer
from core.writer import parse_blocks, extract_memo
from core.docx_writer import build_docx
colpath, out = sys.argv[1], sys.argv[2]
col = Collection(colpath)
ucfg = {"output_dir": out}
cfg = C.merged(ucfg)
t=time.time(); res = pipeline.run(col, ucfg, out+"_state", force=True); print("md:", res.summary(), round(time.time()-t,1),"s")
md = open(f"{out}/복습 카드.md").read()
# 메모 넣고 다시 → 보존 확인
first = re.search(r"^> 🔴.*$|^> ⭐.*$", md, re.M).group(0)
md = md.replace(first, first + "\n\n> [!note] 내 메모\n> 메모 보존 테스트", 1)
open(f"{out}/복습 카드.md","w").write(md)
pipeline._last_sig = None
print("md 2nd:", pipeline.run(col, ucfg, out+"_state", force=True).summary(), "| memo kept:", "메모 보존 테스트" in open(f"{out}/복습 카드.md").read())
print("titles empty:", md.count("(내용 없음)"), "| junk:", any(x in md for x in ["<script","function toggle","Boards and Beyond","Sketchy"]))
cards = collector.collect(col, C.effective_query(cfg), cfg["extra_fields"])
memos = {}
for cid, blk in parse_blocks(open(f"{out}/복습 카드.md").read()).items():
    m = extract_memo(blk)
    if m: memos.setdefault(cid, m)
r = Renderer(cfg, col.media.dir(), out)
open(f"{out}/print.html","w").write(exporter.build_html(cards, cfg, r, "read", memos, media_dir=col.media.dir()))
open(f"{out}/check.html","w").write(exporter.build_html(cards, cfg, r, "check", memos, media_dir=col.media.dir()))
build_docx(cards, cfg, r, f"{out}/test.docx", col.media.dir(), memos)
print("blocks:", len(cards), "| memo in docx/pdf:", "메모 보존 테스트" in open(f"{out}/print.html").read())
col.close()
