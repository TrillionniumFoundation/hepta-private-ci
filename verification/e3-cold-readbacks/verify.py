"""Independently rescore cold predictions against both registered generators (stdlib only)."""

import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
base = root / "qualification"
cases = (
    ("letter","cell-e3-dual-teacher-distillation-20261123","ba9a8f4482d81126eda860a7401f23ccea718ac85313502b44707bc14f135b7d"),
    ("native","cell-e3-dual-teacher-distillation-20261123","0a0b8446718e36aa03b9ef7617d80574f52fbd58ba200bcf86a4af5ce925dfb7"),
    ("completion","cell-e3-native-answer-transfer-20261123","4e9dc2f83b79db9a1076f107d1c610c9b4ad4e61d24d0ed1aaaa53dea870b508"),
)

def compare(a,b):
    assert len(a)==len(b)
    return {"both":sum(x and y for x,y in zip(a,b)),
            "fixed_only":sum(x and not y for x,y in zip(a,b)),
            "sparse_only":sum(y and not x for x,y in zip(a,b)),
            "neither":sum(not x and not y for x,y in zip(a,b))}

def exact_p(count_a,count_b):
    n=count_a+count_b
    return min(1,2*sum(math.comb(n,k) for k in range(min(count_a,count_b)+1))/2**n)

def run(mode,folder,expected):
    directory=base/folder
    spec=importlib.util.spec_from_file_location("generator",directory/"panel.py")
    generator=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    rows=generator.panel()
    truth={r["id"]:r["label"] for r in rows}
    assert len(rows)==len(truth)==460
    loc=directory/"evidence"/(mode+"-run.zip")
    assert hashlib.sha256(loc.read_bytes()).hexdigest()==expected
    with zipfile.ZipFile(loc) as z:
        def read(name):
            return json.loads(z.read(name+".json"))
        main=read("results")
        freeze=read("freeze")
        assert hashlib.sha256(z.read("owned-students.zip")).hexdigest()==main["bundle_sha256"]==freeze["bundle_sha256"]
        assert freeze["panel_sha256"]==generator.digest(rows)
        groups={"holdout":[[r["id"]] for r in rows if r["split"]=="holdout"],"pairs":main["pairs"],
                "old":[[r["id"]] for r in rows if r["split"]=="old-test"]}
        expected_ids=set(id for g in groups.values() for pair in g for id in pair)
        correctness={}
        for arm,summary in main["student"].items():
            obs=read("cold-"+arm)
            pred={r["id"]:r["answer"] for r in obs["rows"]}
            assert len(pred)==len(obs["rows"])==len(expected_ids) and set(pred)==expected_ids
            assert obs["interfaces"]==["lo"] and obs["loopback_bytes"]==0 and obs["bundle_sha256"]==freeze["bundle_sha256"]
            per={kind:[all(pred[id]==truth[id] for id in pair) for pair in members] for kind,members in groups.items()}
            assert [sum(per[k]) for k in groups]==[summary["correct"],summary["correct_pairs"],summary["old"]]
            correctness[arm]=per
        p={}
        for domain in generator.DOMAINS:
            c=main["domains"]["holdout"][domain]
            p[domain]=exact_p(c["t5_only"],c["smol_only"])
        return {"fixed_vs_sparse":{g:compare(correctness["fixed"][g],correctness["sparse"][g]) for g in groups},
                "teacher_discordance_two_sided_p":p,"panel_sha256":freeze["panel_sha256"]}

if __name__=="__main__":
    print("E3_PAIRED",json.dumps({mode:run(mode,d,sha) for mode,d,sha in cases},separators=(",",":")))
