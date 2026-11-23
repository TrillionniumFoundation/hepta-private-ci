"""Read the hosted ZIP directly and recheck the signed-source fixture against its router outputs."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile

p = Path(sys.argv[1])
raw = p.read_bytes()
assert len(raw) == 50546 and hashlib.sha256(raw).hexdigest() == "3128dafa11321b515c0d7a2846280ef665d2e325b26603e6cfaffbdd39634a37"
def digest(obj):
    body=json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    return hashlib.sha256(body).hexdigest()

with zipfile.ZipFile(p) as z:
    assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
    read=lambda n:json.loads(z.read(n))
    res=read("RESULT.json")
    ref=json.loads((Path(__file__).parent/"RESULT.json").read_bytes())
    assert res == ref and res["native_A_grants"] == res["enrolled_people"] == res["new_B_arrivals"] == res["payments"] == 0
    assert res["result"]["decision"] == "no_update_no_distinct_graph_success"
    assert read("operation/NO_UPDATE.json") == res["result"]
    assert read("materials/proposed-scope.json")["scope"] == {"use":"train","failure":res["failure"],"correction":res["correction"]}
    for call in res["original_calls"]:
        slot=call["slot"]
        outcome=read(f"materials/attempts/{slot}.json")
        assert digest(outcome)==call["effect_sha256"]
        body=z.read(f"materials/attempts/{slot}.artifact")
        assert hashlib.sha256(body).hexdigest()==call["text_sha256"]
        assert digest(read(f"materials/{slot}.json"))==res[slot]
        assert (json.loads(body.decode()) == {"count":2}) == call["semantic_success"] == (slot=="correction")
    assert not any(n.endswith("/FROZEN.json") for n in z.namelist())
    values={digest(read(n)):n for n in z.namelist() if n.startswith("operation/router-search/") and n.endswith(".json")}
    for item in res["result"]["scores"]:
        assert item["success"] is False
        row=read(values[item["raw_result_sha256"]])
        assert row["outcome"]["success"] is False and len(row["nodes"])==2
    print("ORIGINAL_AUDIT",json.dumps({"members":len(z.namelist()),"flows":2,"model_forwards":4,"native_human_grants":0,
        "sha256":hashlib.sha256(raw).hexdigest(),"git_blob":hashlib.sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()}))
encoded=base64.b64encode(raw).decode("ascii")
for start in range(0,len(encoded),1800):
    print("ORIGINAL_BYTES",start,encoded[start:start+1800])
