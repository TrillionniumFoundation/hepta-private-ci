"""Independent scripted-action fee/history/recovery and source-binding review."""

import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import time

os.sched_setaffinity(0, {1})
started = time.process_time()
here = Path(__file__).resolve().parent
root = here.parents[2]
folder = here / "scripted_confirmation_01"


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signed(value):
    result = dict(value)
    digest = result.pop("sha256")
    assert hashlib.sha256(canon(result)).hexdigest() == digest
    return result


protocol = json.loads((here / "SCRIPTED_PROTOCOL.json").read_text())
manifest = json.loads((here / "SCRIPTED_SOURCE_MANIFEST.json").read_text())
assert hashlib.sha256((here / "SCRIPTED_SOURCE_MANIFEST.json").read_bytes()).hexdigest() == "12b92be88363ae7461064fe19877b720e03d67c02963189b467dbe0dcd254823"
for name, digest in manifest["files"].items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
remote = json.loads((here / "INDEPENDENT_SCRIPTED_REMOTE_BINDINGS.json").read_text())
for entry in remote["files"]:
    raw = (here / entry["path"]).read_bytes()
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry["git_blob_sha1"]
summary = json.loads((folder / "SUMMARY.json").read_text())
training = here.parent / f"addressed_decision_r15_20261101/run_01/training/{protocol['fit']}.json.gz"
law = json.loads(gzip.decompress(training.read_bytes()))["calibration"]["models"]["hx"]["payload"]
checks, states, cases = 0, 0, []
for pattern, representation in itertools.product(protocol["patterns"], protocol["representations"]):
    group = folder / (pattern + "_" + representation)
    reference = json.loads((group / "reference/OUTPUT.json").read_text())
    row = reference["result"]
    assert reference["fsync_calls"] == ["file", "directory"] * 6
    assert len(row["queries"]) == 6
    expected_actions = ["WAIT", "READ"] if pattern == "wait_read" else ["REFRESH"]
    for q in row["queries"]:
        assert [a["action"] for a in q["actions"]] == expected_actions
        fee = .006 * q["dt"] + (.025 if pattern == "wait_read" else .07) * q["price_scale"]
        assert abs(q["fee"] - fee) < 1e-14 and q["fee"] > 0
        assert q["submitted_after"] == 2 * q["dt"]
        assert q["reward"] == int(q["answer"] == q["target"])
        checks += 4
    for process_input in group.glob("*/INPUT.json"):
        inp = json.loads(process_input.read_text())
        assert inp["law"] == law and inp["seed"] == protocol["seed"] and inp["domain"] == "ood"
        assert inp["variant"] == "r20" and inp["representation"] == representation and inp["pattern"] == pattern
        checks += 6
    for completed in range(6):
        lost = group / ("lost_query_" + str(completed))
        resumed = group / ("resume_query_" + str(completed))
        assert json.loads((lost / "PROCESS.json").read_text())["exit_code"] == -9 and not (lost / "OUTPUT.json").exists()
        assert json.loads((resumed / "PROCESS.json").read_text())["exit_code"] == 0
        result = json.loads((resumed / "OUTPUT.json").read_text())
        clean = lambda value: {k: v for k, v in value.items() if k not in
            ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}
        assert clean(result["result"]) == clean(row)
        assert result["fsync_calls"] == ["file", "directory"] * (5 - completed)
        expected_history = [{k: v for k, v in q.items() if k not in ("target", "reward", "utility")}
                            for q in row["queries"][:completed + 1]]
        body = signed(json.loads((lost / "state.json").read_text()))
        assert body["completed_query"] == completed and body["history"] == expected_history
        assert body["model"] == law["identity"] and body["world"] == row["world"]
        assert body["memory"]["sha256"] == row["queries"][completed]["checkpoint_sha256"]
        signed(body["memory"])
        recorded = next(q for q in summary["cases"] if q["pattern"] == pattern and
                        q["representation"] == representation and q["query"] == completed)
        assert abs(recorded["prefix_fee"] - sum(q["fee"] for q in expected_history)) < 1e-14
        assert abs(recorded["full_fee"] - sum(q["fee"] for q in row["queries"])) < 1e-14
        assert recorded["public_history_exact"] and recorded["cold_continuation_exact"] and recorded["lost_reply_sigkill"]
        cases.append(dict(pattern=pattern, representation=representation, completed_query=completed,
                          prefix_fee=recorded["prefix_fee"], full_fee=recorded["full_fee"]))
        checks += 12
    for path in group.glob("*/state.json"):
        body = signed(json.loads(path.read_text()))
        memory = signed(body["memory"])
        completed = body["completed_query"]
        assert body["model"] == memory["model"] == law["identity"]
        assert body["representation"] == representation and body["world"] == row["world"]
        assert len(body["history"]) == completed + 1 and len(body["receipts"]) == completed + 1
        assert body["memory"]["sha256"] == row["queries"][completed]["checkpoint_sha256"]
        states += 1
        checks += 6
assert len(list(folder.rglob("PROCESS.json"))) == summary["process_count"] == 52
assert states == 48 and len(cases) == summary["cold_lost_reply_cases"] == 24
assert summary["passed"] and summary["base_source_commit"] == protocol["base_source_commit"]
receipt = json.loads((folder / "PROCESS_RECEIPT.json").read_text())
assert receipt["exit_code"] == 0
result = dict(passed=True, checks=checks, cases=cases, processes=52, states=48, lost_reply_cuts=24,
              source_commit=remote["source_commit"], source_files=len(manifest["files"]),
              complete_child_family_cpu_seconds=receipt["complete_child_family_cpu_seconds"],
              raw_sha256={str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in folder.rglob("*") if p.is_file()},
              measured_body_cpu_seconds=time.process_time() - started,
              reviewer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              scope="Independent standard-library reconstruction of separately frozen scripted WAIT-READ and REFRESH-STOP controls with actual paid prefixes and cold continuations. The child replaces choose only; filtering, answers, fees and persistence remain original. No value-policy quality, optimality, resource, population, mid-query external-effect or power-loss inference.")
with (here / "INDEPENDENT_SCRIPTED_REVIEW.json").open("x") as stream:
    json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
