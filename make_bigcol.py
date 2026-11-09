"""AnKing 비슷한 대형 테스트 컬렉션: 복잡한 템플릿, 자료 필드, 이미지, 2,000장 플래그."""
import os, random, shutil, sys
from anki.collection import Collection
random.seed(1)
d = "testbig"
shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
col = Collection(os.path.abspath(f"{d}/collection.anki2"))
mm = col.models
from anki.stdmodels import StockNotetypeKind
m = mm.new("AnKingOverhaul"); m["type"] = 1
m["tmpls"] = [mm.new_template("Cloze")]
for n in ["Text","Extra","Lecture Notes","Missed Questions","Pixorize","Sketchy","Boards and Beyond","One by one"]:
    mm.add_field(m, mm.new_field(n))
t = m["tmpls"][0]
t["qfmt"] = "<div class=front>{{cloze:Text}}</div><script>var x=1;</script><button onclick=toggle()>Extra</button>"
t["afmt"] = ("{{cloze:Text}}<hr id=answer><div class=hints>"
             "{{#Extra}}<button class=hint>Extra</button><div style='display:none'>{{Extra}}</div>{{/Extra}}"
             "{{#Sketchy}}<button class=hint>Sketchy</button><div style='display:none'>{{Sketchy}}</div>{{/Sketchy}}"
             "{{#Boards and Beyond}}<div style='display:none'>{{Boards and Beyond}}</div>{{/Boards and Beyond}}</div>"
             "<script>function toggle(){}</script>")
m["css"] += ".hint{color:red}" * 200
mm.add(m)
# 이미지 120장 (각 ~60KB PNG)
import zlib, struct
def png(w, h, seed):
    random.seed(seed)
    raw = b"".join(b"\x00" + bytes(random.getrandbits(8) for _ in range(w*3)) for _ in range(h))
    def ch(t, data): return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t+data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw, 1)) + ch(b"IEND", b"")
for i in range(120):
    open(os.path.join(col.media.dir(), f"img_{i}.png"), "wb").write(png(200, 100, i))
for i in range(20):  # 세로로 긴 그림
    open(os.path.join(col.media.dir(), f"tall_{i}.png"), "wb").write(png(120, 260, 500 + i))
topics = ["03_Vascular_System::01_Aorta","12_Cardiac_Conductive_Physiology::03_Non-Pacemaker_Action_Potential",
          "15_Ventricularl_Antiarrhythmias::03_Torsades_de_Pointes","26_Hypertension::03_Hypertension_Variants",
          "24_Myocardial_Infarction::06_Management","20_Valvular_Disease::02_Aortic_Stenosis"]
cids = []
for i in range(1100):
    deck = col.decks.id("AnKing Step Deck::Bootcamp::Cardiology::" + topics[i % len(topics)])
    n = col.new_note(m)
    n["Text"] = (f"<div><b>Torsades</b> de pointes #{i} is caused by {{{{c1::prolonged QT}}}} and treated with "
                 f"{{{{c2::IV magnesium sulfate::drug}}}}<br>&nbsp;</div>")
    # AnKing 처럼 그림에 크기가 박혀 있으면 찌그러지던 문제 재현용
    n["Extra"] = (f"<div>Mnemonic: <i>Some Risky Meds</i></div><img src='img_{i % 120}.png' style='width: 600px; height: 90px'>"
                  + (f"<img src='tall_{i % 20}.png' width='400' height='120'>" if i % 3 == 0 else "")
                  + "<div><br></div><i>Photo credit: OpenStax</i>")
    n["Lecture Notes"] = "QT &gt; 500 ms 위험" if i % 5 == 0 else ""
    n["Sketchy"] = f"<img src='img_{(i+7) % 120}.png'><img src='img_{(i+9) % 120}.png'>" * 2
    n["Boards and Beyond"] = "<a href='https://x'>B&amp;B video</a>" + "<div>long resource text</div>" * 30
    n["Pixorize"] = "\x0bcontrol char test"
    col.add_note(n, deck)
    cs = n.cards()
    for c in cs:
        cids.append(c.id)
col.set_user_flag_for_cards(1, cids[:2000])
# Bootcamp 밖 덱 (덱 한정 테스트)
bb = col.decks.id("AnKing Step Deck::B&B::Renal")
for i in range(30):
    n = col.new_note(m); n["Text"] = f"B&B card {{{{c1::{i}}}}}"; col.add_note(n, bb)
    col.set_user_flag_for_cards(1, [n.cards()[0].id])
# 기본 카드, IO 비슷한 카드, 마크
b = col.models.by_name("Basic")
n = col.new_note(b); n["Front"] = "<div><div>QT 연장 약물?</div></div>"; n["Back"] = "<ul><li>Class IA</li><li>Class III</li></ul>"
n.tags = ["marked"]; col.add_note(n, col.decks.id("AnKing Step Deck::Bootcamp::Pharm"))
print("flagged/marked:", len(col.find_cards("flag:1 OR tag:marked")))
col.close()
