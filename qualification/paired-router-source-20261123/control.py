"""Exercise both previously authorized synthetic training cases under the archived graph."""
import json
from pathlib import Path
import shutil
import sys
import zipfile
from cell_experiments import data, paired_source, paired_source_gate as gate, paired_source_dispatch
from cell_experiments import paired_router_source as router
from cell_experiments.test_paired_source import draft
from cell_experiments.online_v4.test_circuit_bundle import training_task


def run(case, number, pair, receipt, primary, directory):
    root = directory / case / "materials"
    root.mkdir(mode=0o700,parents=True)
    for name in ("base","reader","source"):
        shutil.copytree(primary / "materials" / name, root / name)
    task = training_task(number,receipt["input"])
    assert task["authorization"]["training_allowed"] is True and receipt["scope"] == "authored_development"
    assert receipt["initial_verification"]["success"] is False and receipt["corrected_verification"]["success"] is True
    assert receipt["child"] == data.digest(pair["candidate"]["models"][case])
    records = []
    for i,(label,policy,answer) in enumerate((("failure",receipt["parent"],receipt["initial_answer"]),
                                               ("correction",receipt["child"],receipt["corrected_prediction"]["answer"]))):
        source = dict(original_training_receipt=receipt, phase=label)
        rec = draft(root,label,answer,policy,source,i+1)
        rec["task"] = task["task"]
        rec["authorization"] = task["authorization"]
        records.append(paired_source.capture_attempt(rec,root/(label+".artifact"),root/"originals",root/(label+".json")))
    router.keep(root/"parent.json",pair["candidate"])
    router.keep(root/"retention.json",pair["retention"])
    plan = dict(schema=router.POLICY,study=data.digest(["known authorized training",case]),delivery=data.digest("fixture"),
                failure=data.digest(records[0]),correction=data.digest(records[1]),parent=data.digest(pair["candidate"]),
                retention=data.digest(pair["retention"]),trainer_source_sha256=router.source_hash(),timeout_seconds=180)
    result, op = router._fit(root,plan,dict(schema="engineering_fixture"),engineering=True)
    freeze = result.get("freeze_sha256")
    comparisons = []
    if freeze:
        report = gate.gate(root,op)
        snapshot = router.read(op/"FROZEN.json")
        router.verify_originals(op,snapshot,result)
        assert snapshot["parent"]["models"] == snapshot["candidate"]["models"]
        assert data.digest(snapshot["candidate"]) == result["candidate_sha256"]
        try:
            paired_source_dispatch.authorize(snapshot,dict(source_retention_sha256=data.digest(report)),op/"RETENTION.json")
        except ValueError:
            pass
        else:
            raise AssertionError("engineering source entered owner dispatch")
        comparisons = report["comparisons"]
        decision = report["decision"]
    else:
        decision = result["decision"]
    return dict(case=case,source=receipt["input"],original_training_receipt_sha256=data.digest(receipt),
                scores=router.read(op/"ROUTER-FIT.json")["scores"],freeze_sha256=freeze,decision=decision,
                cold_comparisons=comparisons,prospective_dispatch=False)


def exercise(archive, primary, out):
    import hashlib
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == "08640f268030dbb74b97cc63f1631e510848c99b8522231314b1f2a9b5c83099"
    with zipfile.ZipFile(archive) as z:
        pair = json.loads(z.read(next(n for n in z.namelist() if n.endswith("/paired.json"))))
        results = [run(key,i,pair,json.loads(z.read("original/materials/"+key+"/TRAINING.json")),primary,out)
                   for key,i in (("source",3),("reader",4))]
    result = dict(scope="engineering_fixture_already_exposed",primary_measurement=False,cases=results,
                  trained_cells=0,enrolled_people=0,prospective_admissions=0,payments=0)
    router.keep(out/"CONTROL.json",result)
    print(json.dumps(result))
    with zipfile.ZipFile(out.parent/"ROUTER_CONTROL.zip","x",compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p,p.relative_to(out))


if __name__ == "__main__":
    exercise(*(Path(v) for v in sys.argv[1:]))
