import sys; sys.path.insert(0,"markvault")
from anki.collection import Collection
from core import config as C, collector, renderer, writer
def run(user_cfg):
    col = Collection("testcol/collection.anki2")
    cfg = C.merged(user_cfg)
    cards = collector.collect(col, cfg["query"])
    r = renderer.Renderer(cfg, col.media.dir(), cfg["output_dir"])
    w = writer.Writer(cfg, r, state_dir="out_state")
    res = w.write(cards); col.close(); return res
if __name__ == "__main__":
    print(run({"output_dir": "out", "weekly_snapshot": True}).summary())
