"""Recompute recovery integrity and resource totals without importing runtime."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_state(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    sequence, body, digest = db.execute("SELECT sequence,body,sha FROM state").fetchone()
    value = json.loads(body)
    assert sha(value) == digest
    history = db.execute("SELECT sequence,sha FROM history ORDER BY sequence").fetchall()
    assert [row[0] for row in history] == list(range(sequence + 1))
    assert history[-1][1] == digest
    db.close()
    return value


def audit(directory):
    summary = json.loads((directory / "SUMMARY.json").read_text())
    comparisons, checked_queries, checked_effects = 0, 0, 0
    for case in summary["cases"]:
        folder = directory / case["case"]
        config = json.loads((folder / "config.json").read_text())
        expected = json.loads((folder / "expected.json").read_text())
        index = [row for row in summary["cases"] if row["case"] == case["case"]].index(case)
        actual = read_state(folder / f"fault_{index:02d}.sqlite")
        assert actual == expected and sha(actual) == case["actual_sha256"] == case["expected_sha256"]
        assert actual["config_sha256"] == sha(config)
        assert actual["query"] == 6 and actual["status"] == "done"
        assert actual["pending"] is None and actual["current"] is None
        body = dict(actual["memory"])
        memory_sha = body.pop("sha256")
        assert sha(body) == memory_sha and body["model"] == config["model"]["identity"]
        effects = []
        for query in actual["queries"]:
            fee, completed = 0., 0
            for i, action in enumerate(query["actions"]):
                slots = 2 if action["action"] == "REFRESH" else 1
                completed += slots
                assert action["step"] == completed
                fee += .003 * slots * query["dt"]
                if action["action"] in ("READ", "REFRESH"):
                    fee += (.025 if action["action"] == "READ" else .07) * query["price_scale"]
                else:
                    assert action["token"] is None
                effects.append(f"{config['owner_fingerprint']}:{query['query']}:{i}")
            assert abs(fee-query["fee"]) < 2e-15
            assert query["reward"] == int(query["answer"] == query["target"])
            assert query["utility"] == query["reward"] - query["fee"]
            checked_queries += 1
        assert actual["effects"] == effects and len(set(effects)) == len(effects)
        checked_effects += len(effects)
        suspended = json.loads((folder / f"fault_{index:02d}_suspended.json").read_text())
        pieces = case["stop"].split(":")
        if len(pieces) == 3:
            when, phase, action = pieces
            if when == "after" and phase == "applied":
                assert suspended["pending"] is None
            else:
                expected_phase = phase if when == "after" else {"received":"elapsed", "applied":"received"}[phase]
                assert suspended["pending"]["phase"] == expected_phase
                assert suspended["pending"]["action"] == action
        else:
            assert suspended["status"] == "query_boundary" and suspended["current"] is None
        kill = json.loads((folder / f"fault_{index:02d}_kill.process.json").read_text())
        resumed = json.loads((folder / f"fault_{index:02d}_resume.process.json").read_text())
        assert kill["exit_code"] == -9 and resumed["exit_code"] == 0 and kill["pid"] != resumed["pid"]
        comparisons += 1
    receipts = [json.loads(path.read_text()) for path in directory.rglob("*.process.json")]
    cold_starts = 0
    for path in directory.rglob("*.stdout"):
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        assert lines[0]["transition_cache_entries"] == lines[0]["event_cache_entries"] == 0
        cold_starts += 1
    assert len(receipts) == summary["process_count"] == cold_starts
    assert abs(sum(row["cpu_seconds"] for row in receipts)-summary["complete_child_cpu_seconds"]) < 1e-12
    assert abs(sum(row["cpu_seconds"] for row in receipts if row["exit_code"] == -9)-summary["killed_child_cpu_seconds"]) < 1e-12
    assert all(summary["negative_rejections"].values())
    return dict(scope="Independent saved-record integrity, action-fee/effect accounting and process-cost audit; no runtime/planner imports or production claim.",
        recovery_comparisons=comparisons, checked_queries=checked_queries, checked_effects=checked_effects,
        cold_starts=cold_starts, all_passed=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.directory)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(canonical(result))
