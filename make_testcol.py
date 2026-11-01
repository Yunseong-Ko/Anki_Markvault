import os, shutil, sys
from anki.collection import Collection
from anki.consts import *
path = os.path.abspath("testcol/collection.anki2")
if os.path.exists(path):
    for f in os.listdir("testcol"): 
        p=os.path.join("testcol",f); shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
col = Collection(path)
# media: tiny png
import base64
png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
mp = os.path.join(col.media.dir(), "hf_01.png")
open(mp,"wb").write(png)
did = col.decks.id("국시::순환기::심부전")
did2 = col.decks.id("국시::내분비")
basic = col.models.by_name("Basic"); cloze = col.models.by_name("Cloze")
def add(model, did, fields, tags=()):
    n = col.new_note(model)
    for i,f in enumerate(fields): n.fields[i]=f
    n.tags=list(tags); col.add_note(n, did); return n
n1 = add(basic, did, ["심부전에서 가장 먼저 오르는 <b>바이오마커</b>는?", "BNP<br><img src=\"hf_01.png\"><div>벽 신장 자극 \\(\\uparrow\\) 분비</div>"], ["marked"])
n2 = add(cloze, did, ["{{c1::BNP}}는 {{c2::심실 벽 신장}} 자극으로 분비되며, 심부전 진단 cutoff 는 {{c1::100 pg/mL}}", "Extra: NT-proBNP 도 사용"])
n3 = add(basic, did2, ["Graves 병 1차 약제", "Methimazole<ul><li>PTU 는 임신 1기</li><li>부작용: agranulocytosis</li></ul>"])
n4 = add(basic, did2, ["플래그 없는 카드", "표시 안 됨"])
# flags: red on n2 c1, blue on n3
c = n2.cards()
col.set_user_flag_for_cards(1, [c[0].id])
col.set_user_flag_for_cards(4, [n3.cards()[0].id])
# some review history for n2 c1
from anki.scheduler.v3 import Scheduler
col.save() if hasattr(col,'save') else None
print("cards:", col.card_count(), "flagged/marked:", len(col.find_cards("flag:1 OR tag:marked")))
col.close()
