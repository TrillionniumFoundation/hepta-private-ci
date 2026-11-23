"""Replay the preregistered archived weights and unmodified amber training task."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from cell_experiments import data, paired_freeze, paired_source_gate as gate
from cell_experiments import paired_router_source as router
from cell_experiments.test_paired_source import capture

ZIP = "08640f268030dbb74b97cc63f1631e510848c99b8522231314b1f2a9b5c83099"


def main(archive, out):
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ZIP
    root = out / "materials"
    root.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.startswith(("original/materials/base/", "original/materials/reader/", "original/materials/source/")) and not name.endswith("/"):
                relative = Path(name).relative_to("original/materials")
                assert ".." not in relative.parts
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(z.read(name))
        req = json.loads(z.read(next(n for n in z.namelist() if n.endswith("/paired.json"))))
        select = next(n for n in z.namelist() if n.endswith("/consumer/selection/RESULT.json")).removesuffix("RESULT.json")
        # Separately exercise the existing positive edge fixture's graph-aware cold rows.
        snapshot = {k: req[k] for k in ("parent", "candidate", "retention", "timeout_seconds")}
        original = []
        for arm in ("parent", "candidate"):
            rows = []
            for i, panel in enumerate(("future", "retention")):
                row = json.loads(z.read(select + arm + f"/{i:04d}.json"))
                rows.append(dict(panel=panel, record_sha256=row["task_sha256"], prediction=row["prediction"], outcome=row["outcome"]))
            target = out / (arm + "-cold-control.json")
            model = data.digest(req[arm])
            raw = dict(arm=arm, model=model, pid=rows[0]["prediction"]["pid"], rows=rows)
            paired_freeze.publish(raw, target)
            records = [(panel, req[panel][0]) for panel in ("future", "retention")]
            gate.read_arm(target, arm, snapshot, records, root)
            original.append([r["outcome"]["success"] for r in rows])
            wrong = copy.deepcopy(raw)
            wrong["rows"][0]["prediction"]["circuit_trace"]["nodes"][1]["output"]["input_ids"] = [-1]
            damaged = out / (arm + "-damage-control.json")
            paired_freeze.publish(wrong, damaged)
            try:
                gate.read_arm(damaged, arm, snapshot, records, root)
            except ValueError:
                damaged.unlink()
            else:
                raise AssertionError("substituted relay input survived")
    router.keep(root / "parent.json", req["candidate"])
    router.keep(root / "retention.json", req["retention"])
    a = capture(root, "failure", "0", "a" * 64, {"action": "0"}, 1)
    b = capture(root, "correction", "1", "b" * 64, {"action": "1"}, 2)
    spec = dict(schema=router.POLICY, study=data.digest("fictional amber router study"),
                delivery=data.digest("fixture only"), failure=data.digest(a), correction=data.digest(b),
                parent=data.digest(req["candidate"]), retention=data.digest(req["retention"]),
                trainer_source_sha256=router.source_hash(), timeout_seconds=180)
    owner = dict(schema="engineering_fixture", participants=0)
    result, op = router._fit(root, spec, owner, engineering=True)
    repeat, _ = router._fit(root, spec, owner, engineering=True)
    assert result == repeat and result["scope"] == "engineering_fixture"
    if "freeze_sha256" in result:
        result = gate.gate(root, op)
        router.verify_originals(op, router.read(op / "FROZEN.json"), router.read(op / "COMPLETED.json"))
    else:
        assert not (op / "FROZEN.json").exists()
    original_fit = router.read(op / "ROUTER-FIT.json")
    # The normal producer must refuse a fictional owner through the ordinary owner path.
    try:
        router._fit(root, spec, owner)
    except ValueError:
        pass
    else:
        raise AssertionError("engineering fixture promoted")
    summary = dict(scope="engineering_fixture", original_archive_sha256=ZIP, study=data.digest(spec),
                   training_input=a["task"]["input"], original_failure=a["final_answer"],
                   original_correction=b["final_answer"], router_only=original_fit,
                   result=result, old_graph_control_parent_candidate=original,
                   tampered_cold_hops_refused=2, unregistered_owner_refused=True, repeat_same_original=True,
                   registered_users=0, prospective_b=0, payments=0)
    router.keep(out / "READOUT.json", summary)
    print(json.dumps({"case": "unchanged archived amber", "decision": result["decision"],
                      "scores": original_fit["scores"], "old_cold_rows": original}))
    archive_out = out.parent / "ROUTER_SOURCE_ORIGINALS.zip"
    with zipfile.ZipFile(archive_out, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
