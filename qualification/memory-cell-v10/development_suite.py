"""Full control-flow smoke check on wholly separate synthetic development data."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np

from export_native import canonical, sha
from processes import Ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    data = args.output / "data" / "capacity-64"
    data.mkdir(parents=True)
    rng = np.random.default_rng(90401)
    feature = {}
    population = {"development_fixture": True, "records": [], "events": rng.integers(-10, 20, 64).tolist(), "holds": [3, 27]}
    for kind, width in (("semantic", 3), ("procedure", 4)):
        feature[kind] = rng.normal(size=(64, 384)).astype(np.float32)
        feature[kind] /= np.linalg.norm(feature[kind], axis=1, keepdims=True)
        for index in range(64):
            key = f"development-{kind}-{index:03d}"
            value = rng.integers(0, 16, 3).tolist() if kind == "semantic" else [*rng.integers(0, 6, 3).tolist(), 6]
            population["records"].append({"kind": kind, "index": index, "key": key, "value": value,
                                           "canonical_text": key, "source_id": sha(key.encode()), "version": 0, "active": True})
    (data / "sources.json").write_bytes(canonical(population))
    (data.parent / "TRAIN_ENCODER.json").write_bytes(canonical({"base_encoder_sha": sha(b"development-synthetic-features-not-MiniLM")}))
    np.savez_compressed(data / "canonical.npz", **feature)
    for phase, offsets in (("train", (0, 1)), ("calibration", (5, 7)), ("held", (11, 13))):
        queries, vectors = [], []
        for index in range(64):
            for role in ("semantic", "skill", "unknown"):
                kind = "procedure" if role == "skill" else "semantic"
                queries.append({"id": f"development:{phase}:{role}:{index}", "text": f"{phase} development {role} request {index}",
                                "role": role, "entity": index if role == "semantic" else None,
                                "workflow": index if role == "skill" else None, "wording_group": f"development:{phase}:{role}"})
                vectors.append(feature[kind][index] if role != "unknown" else -feature[kind][index])
            for offset in offsets:
                workflow = (index + offset) % 64
                queries.append({"id": f"development:{phase}:compose:{index}:{workflow}",
                                "text": f"{phase} development composition {index} with {workflow}", "role": "compose",
                                "entity": index, "workflow": workflow, "wording_group": f"development:{phase}:compose"})
                vector = feature["semantic"][index] + feature["procedure"][workflow]
                vectors.append(vector / np.linalg.norm(vector))
        (data / f"{phase}-queries.json").write_bytes(canonical(queries))
        np.savez_compressed(data / f"{phase}-features.npz", features=np.asarray(vectors))
    connection = sqlite3.connect(data / "exact.sqlite")
    connection.executescript("CREATE TABLE memory(kind TEXT,idx INTEGER,key TEXT,value TEXT,source_id TEXT,PRIMARY KEY(kind,idx)); CREATE TABLE episode(idx INTEGER,at INTEGER,value INTEGER,source_id TEXT,PRIMARY KEY(idx,at)); CREATE TABLE exception(idx INTEGER PRIMARY KEY,held INTEGER,source_id TEXT);")
    connection.executemany("INSERT INTO memory VALUES(?,?,?,?,?)", [(row["kind"], row["index"], row["key"], json.dumps(row["value"]), row["source_id"]) for row in population["records"]])
    connection.executemany("INSERT INTO episode VALUES(?,?,?,?)", [(i, 20, value, sha(f"development-event-{i}".encode())) for i, value in enumerate(population["events"])])
    connection.executemany("INSERT INTO exception VALUES(?,?,?)", [(i, i in population["holds"], sha(f"development-hold-{i}".encode())) for i in range(64)])
    connection.commit()
    connection.close()
    here, ledger = Path(__file__).resolve().parent, Ledger(args.output)
    ledger.run("fit", [sys.executable, str(here / "research_fit.py"), "--data", str(data), "--output", str(args.output / "models"),
                       "--capacity", "64", "--seed", "90401", "--development"])
    ledger.run("read", [sys.executable, str(here / "research_evaluate.py"), "--data", str(data), "--models", str(args.output / "models"),
                        "--output", str(args.output / "evaluation")])
    result = json.loads((args.output / "evaluation" / "RESULTS.json").read_text())
    strong = result["pipeline"]["oracle/exact_sql"]
    if strong["correct"] != strong["count"]:
        raise AssertionError("same-information SQL interpreter did not reproduce the independent targets")
    maintenance = json.loads((args.output / "models" / "maintenance" / "MAINTENANCE.json").read_text())
    for cycle in maintenance["cycles"]:
        if cycle["event"] == "delete_clean_rebuild":
            for arm in cycle["arms"].values():
                if not arm["clean_rebuild_identity_equal"] or arm["lineage_contains_deleted_source"]:
                    raise AssertionError("clean rebuilding retained a deleted source or old initialization")
    print(json.dumps({"full_development_control_flow_passed": True, "formal_inputs_read": False,
                      "sample_distribution": "independent seed90401 synthetic random vectors; not a research result",
                      "processes": ledger.rows}))


if __name__ == "__main__":
    main()
