"""Fit the common parent, the three students and the sparse selector. No test scoring."""

import argparse
import hashlib
import json
import platform
import struct
import time
import zipfile
from pathlib import Path
import numpy as np
from panel import DOMAINS, digest, panel
from student import encode, terms

REG = 0.20


def teacher_values(path, ids):
    j = json.loads(path.read_bytes())
    if j["phase"] != "fit" or j["panel_sha256"] != digest(panel()):
        raise ValueError("Incompatible supervision")
    cols = {r["id"]: r["label"] for r in j["rows"]}
    if len(j["rows"]) != len(cols) or set(cols) != ids:
        raise ValueError("Supervision roster mismatch")
    return cols


def main():
    p = argparse.ArgumentParser()
    p.add_argument("evidence", type=Path)
    p.add_argument("bundle", type=Path)
    a = p.parse_args()
    now, cpu = time.perf_counter(), time.process_time()
    rows = panel()
    disc = [r for r in rows if r["split"] == "discovery"]
    train = [r for r in rows if r["split"] == "train"]
    old = [r for r in rows if r["split"] == "old-train"]
    vocab = sorted(set().union(*(terms(r["prompt"]).keys() for r in old + train)))
    vi = {s: i for i, s in enumerate(vocab)}

    def matrix(rows):
        x = np.zeros((len(rows), len(vocab)), dtype=float)
        for j, row in enumerate(rows):
            for k, v in encode(row["prompt"], vi).items():
                x[j, k] = v
        return x

    def fit(x, target, parent):
        return parent + x.T @ np.linalg.solve(
            x @ x.T + REG * np.eye(len(x)), target - x @ parent
        )

    ids = {r["id"] for r in disc + train}
    teachers = {
        m: teacher_values(a.evidence / ("teacher-fit-" + m + ".json"), ids)
        for m in ("t5", "smol")
    }
    # Only the old-skill examples supply authored labels to the expert fits.
    xo = matrix(old)
    target_old = np.array([2 * r["label"] - 1 for r in old])
    parent = fit(xo, target_old, np.zeros(len(vocab)))
    x = matrix(train + old)
    labels = {
        m: np.concatenate([[2 * teachers[m][r["id"]] - 1 for r in train], target_old])
        for m in teachers
    }
    weights = {m: fit(x, y, parent) for m, y in labels.items()}
    weights["mix"] = fit(x, (labels["t5"] + labels["smol"]) / 2, parent)
    weights["parent"] = parent

    def get_count(m, rr):
        return sum(teachers[m][r["id"]] == r["label"] for r in rr)

    counts = {
        d: {m: get_count(m, [r for r in disc if r["domain"] == d]) for m in teachers}
        for d in DOMAINS
    }
    fixed = {d: "smol" if c["smol"] > c["t5"] else "t5" for d, c in counts.items()}
    best = "smol" if get_count("smol", disc) > get_count("t5", disc) else "t5"
    gate_y = np.array(
        [
            int(teachers["smol"][r["id"]] == r["label"])
            - int(teachers["t5"][r["id"]] == r["label"])
            for r in disc
        ]
    )
    weights["gate"] = fit(matrix(disc), gate_y, np.zeros(len(vocab)))
    state = {
        "vocabulary": vocab,
        "fixed_route": fixed,
        "best_single": best,
        "format": "word-char-3gram-ridge-v1",
    }
    with zipfile.ZipFile(a.bundle, "x", compression=zipfile.ZIP_DEFLATED) as z:

        def member(name, buf):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 23, 0, 0, 0))
            z.writestr(info, buf, compress_type=zipfile.ZIP_DEFLATED)

        member(
            "state.json",
            json.dumps(state, separators=(",", ":"), sort_keys=True).encode(),
        )
        for m, w in sorted(weights.items()):
            member(m + ".f64", struct.pack("<" + "d" * len(w), *w))
    receipt = {
        "panel_sha256": digest(rows),
        "bundle_sha256": hashlib.sha256(a.bundle.read_bytes()).hexdigest(),
        "features": len(vocab),
        "regularization": REG,
        "old_rehearsal": len(old),
        "training_items": len(train),
        "discovery_items": len(disc),
        "fit_teacher_sha256": {
            m: hashlib.sha256(
                (a.evidence / f"teacher-fit-{m}.json").read_bytes()
            ).hexdigest()
            for m in teachers
        },
        "fixed_route": fixed,
        "best_single": best,
        "discovery_correct": counts,
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - now,
        "numpy": np.__version__,
        "python": platform.python_version(),
    }
    (a.evidence / "freeze.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
