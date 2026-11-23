"""Independently audit only the explicitly fictional archive using the standard library."""

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return sha(canonical(value))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(archive):
    z = zipfile.ZipFile(archive)
    with z, sqlite3.connect(":memory:") as db:
        def read(name):
            return json.loads(z.read(name))
        names = z.namelist()
        require(len(names) == len(set(names)), "duplicate archive member")
        db.deserialize(z.read("original/intake/intake.sqlite"))
        rows = db.execute("SELECT id,request_sha,request_json,binding,state FROM admissions").fetchall()
        require(len(rows) == 1, "expected exactly one simulated released intake")
        admission, pair, paired_raw, binding_raw, state = rows[0]
        binding = json.loads(binding_raw)
        req = json.loads(paired_raw)
        prefix = "original/intake/" + admission + "/"
        cfg = json.loads(db.execute("SELECT value FROM settings").fetchone()[0])
        require(binding["release"]["scope"] == cfg["scope"] == "engineering_fixture"
                and state == "released" and digest(binding) == admission and digest(req) == pair
                and read(prefix + "paired.json") == req
                and read(prefix + "release.json") == dict(binding["release"], admission_sha256=admission),
                "engineering journal, scope or release differs")
        principal = binding["native"]["study_principal_sha256"]
        root = prefix + "consumer/"
        selection = read(root + "selection/RESULT.json")
        require(selection["request_sha256"] == pair and read(root + "selection/REQUEST.json") == req,
                "selected pair differs")
        model_count = 0
        panel_scores = {}
        for arm, end in zip(("parent", "candidate"), selection["cold_receipts"], strict=True):
            model = req[arm]
            for f in model["files"]:
                blob = z.read("original/materials/" + f["path"])
                require(len(blob) == f["bytes"] and sha(blob) == f["sha256"], "model artifact differs")
                model_count += 1
            require(end == read(root + f"selection/{arm}/END.json") and end["model_digest"] == digest(model),
                    "original cold arm differs")
            for index, panel in enumerate(("future", "retention")):
                row = read(root + f"selection/{arm}/{index:04d}.json")
                require(len(req[panel]) == 1 and row["task_sha256"] == digest(req[panel][0])
                        and digest(row) == end["row_hashes"][index] and row["prediction"]["pid"] == end["pid"],
                        "original cold row differs")
                expected = req[panel][0]["task"]["verifier"]["parameters"]["expected"]
                actual = json.loads(row["prediction"]["answer"])
                passed = type(actual) is type(expected) and actual == expected
                require(row["outcome"]["success"] is passed, "original cold score differs")
                panel_scores[arm, panel] = passed
        require(not panel_scores["parent", "future"] and panel_scores["candidate", "future"]
                and panel_scores["parent", "retention"] and panel_scores["candidate", "retention"],
                "candidate did not pass the fixture selection")
        child = req["candidate"]
        require(child["parent"] == digest(req["parent"])
                and child["runtime"]["base_directory"] != req["parent"]["runtime"]["base_directory"],
                "wrong model lineage")
        vocab = read("original/materials/" + child["runtime"]["base_directory"] + "/tokenizer.json")["model"]["vocab"]
        summary = read("SUMMARY.json")
        decisions, nonces = [], set()
        for expected, row in zip(("accepted", "rejected"), summary["decisions"], strict=True):
            op = row["run"]["operation"]
            path = root + op + "/"
            start, run, payload, raw, report = [read(path + name + ".json") for name in (
                "STARTED", "RUN", "worker-input", "worker-output", "OUTCOME")]
            pred = raw["prediction"]
            task = payload["task"]
            task_hash = digest(task)
            require(read("original/site/consumer-task-" + task_hash + ".json") == task, "source task differs")
            base = dict(pair=pair, candidate=digest(child), task=task_hash)
            operation = digest(["hepta.paired-learning.subsequent-operation.v1", admission, digest(selection), base])
            scope = dict(use="request_consumer_run", operation=operation, **base)
            require(operation == op and start["request"] == run["request"] == scope
                    and payload["model"] == child and pred["loaded_model_digest"] == digest(child),
                    "bound operation or candidate differs")
            nonce = start["nonce"]
            require(len(bytes.fromhex(nonce)) == 32 and nonce not in nonces
                    and nonce == payload["nonce"] == raw["nonce"] == run["nonce"],
                    "nonce differs or was reused")
            nonces.add(nonce)
            answer = z.read(path + "answer.utf8")
            require(pred["input_ids"] == [vocab[t] for t in task["input"].split()]
                    and answer.decode() in vocab and pred["output_ids"] == [vocab[answer.decode()]] and answer == pred["answer"].encode() == b"1"
                    and run["local_child_pid"] == pred["pid"] and run["prediction_sha256"] == digest(raw)
                    and run["selection_sha256"] == start["local_selection_sha256"] == digest(selection)
                    and run["grant_sha256"] == digest(start["grant"])
                    and row["run"]["run_receipt"] == row["checked_request"]["run_receipt"] == digest(run)
                    and row["run"]["output"] == run["output_sha256"] == sha(answer),
                    "worker tokens, output, or local receipt differs")
            report_scope = report["scope"]
            effect = sha(z.read(path + "effect.bin"))
            require(effect == report_scope["effect"]
                    and z.read("original/site/consumer-effect-" + effect + ".bin") == z.read(path + "effect.bin")
                    and report_scope == dict(scope, use="report_consumer_outcome", run_receipt=digest(run),
                                             output=sha(answer), effect=effect, outcome=expected)
                    and report["payment_authorized"] is False and report["independently_verified_business_effect"] is False
                    and report["evidence_scope"] == "engineering_fixture"
                    and row["checked_outcome"]["receipt_sha256"] == digest(report),
                    "outcome bytes or decision differs")
            for kind, want, grant in (("request", scope, start["grant"]), ("report", report_scope, report["grant"])):
                event = read(f"{expected}-{kind}-fixture-event.json")
                statement = {"study_sha256": cfg["study"], "scope": want}
                require(grant == event["receipt"] and grant["study_principal_sha256"] == principal
                        and event["request"] == dict(statement, delivery_id=grant["delivery_id"])
                        and grant["statement_sha256"] == sha(b"Fixture statement " + canonical(statement)),
                        "fictional delivery or statement differs")
            decisions.append(dict(outcome=expected, operation=op, run_receipt_sha256=digest(run),
                                  outcome_receipt_sha256=digest(report), output_sha256=sha(answer)))
        require(all(summary[k] == 0 for k in ("real_participants", "enrolled_real_pairs", "remote_execution_proofs",
                                              "external_effects_verified", "payments")), "incorrect evidence level")
        return dict(archive_sha256=sha(Path(archive).read_bytes()), archive_bytes=Path(archive).stat().st_size,
                    files=len(names), rehashed_model_files=model_count, cold_arms=2, cold_rows=4,
                    study_scope="engineering_fixture", real_participants=0, payments=0, decisions=decisions)


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1])), indent=2))
