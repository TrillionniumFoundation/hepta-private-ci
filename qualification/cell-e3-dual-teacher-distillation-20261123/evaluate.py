"""Request blind predictions, score the frozen panel, and audit conditional teacher inheritance."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from panel import DOMAINS, panel

ARMS = ("parent", "t5", "smol", "best_single", "mix", "fixed", "sparse")


def groups(rows):
    return {d: [r for r in rows if r["domain"] == d] for d in DOMAINS}


def outcomes(rows, ta, tb):
    c = Counter((ta[r["id"]] == r["label"], tb[r["id"]] == r["label"]) for r in rows)
    return {
        "n": len(rows),
        "both": c[True, True],
        "t5_only": c[True, False],
        "smol_only": c[False, True],
        "neither": c[False, False],
        "t5_correct": c[True, True] + c[True, False],
        "smol_correct": c[True, True] + c[False, True],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("evidence", type=Path)
    a = p.parse_args()
    e = a.evidence.resolve()
    bundle = e / "owned-students.zip"
    freeze = json.loads((e / "freeze.json").read_bytes())
    sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if sha != freeze["bundle_sha256"]:
        raise ValueError("Frozen bundle mismatch")
    items = panel()
    evaluation = [
        r for r in items if r["split"] in ("holdout", "composition", "old-test")
    ]
    blind = json.dumps(
        [{k: r[k] for k in ("id", "domain", "prompt")} for r in evaluation]
    )
    run = {}
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for f in ("student.py", "cold.py"):
            shutil.copy(Path(__file__).parent / f, d / f)
        shutil.copy(bundle, d / "owned.zip")
        for arm in ARMS:
            proc = subprocess.run(
                [
                    "unshare",
                    "-Urn",
                    sys.executable,
                    "-I",
                    "-S",
                    str(d / "cold.py"),
                    str(d / "owned.zip"),
                    arm,
                ],
                input=blind,
                text=True,
                capture_output=True,
                check=False,
                cwd=d,
            )
            if proc.returncode:
                raise RuntimeError(proc.stderr)
            result = json.loads(proc.stdout)
            if result["bundle_sha256"] != sha or len(result["rows"]) != len(evaluation):
                raise ValueError("Incomplete cold return")
            (e / ("cold-" + arm + ".json")).write_text(proc.stdout)
            run[arm] = {r["id"]: r["answer"] for r in result["rows"]}
    held = [r for r in items if r["split"] == "holdout"]
    disc = [r for r in items if r["split"] == "discovery"]
    old = [r for r in items if r["split"] == "old-test"]
    comp = [r for r in items if r["split"] == "composition"]
    by = groups(comp)
    pairs = [
        (ra, rb)
        for i in range(0, len(DOMAINS), 2)
        for ra, rb in zip(by[DOMAINS[i]], by[DOMAINS[i + 1]], strict=True)
    ]

    def score(rows, ans):
        return sum(ans[r["id"]] == r["label"] for r in rows)

    def pair_score(ans):
        return sum(all(ans[r["id"]] == r["label"] for r in pair) for pair in pairs)

    teachers = {}
    for name in ("t5", "smol"):
        merged = {}
        for phase in ("fit", "confirmation"):
            rec = json.loads((e / f"teacher-{phase}-{name}.json").read_bytes())
            merged.update({r["id"]: r["label"] for r in rec["rows"]})
        teachers[name] = merged
    sta, stb = teachers["t5"], teachers["smol"]
    domains = {
        k: {d: outcomes(rr, sta, stb) for d, rr in groups(group).items()}
        for k, group in (("discovery", disc), ("holdout", held))
    }
    selected = {
        m: [
            d
            for d, c in domains["discovery"].items()
            if c[m + "_correct"] >= 7
            and c[m + "_only"] >= 2
            and c[m + "_correct"] > c[other + "_correct"]
        ]
        for m, other in (("t5", "smol"), ("smol", "t5"))
    }
    result = {
        "bundle_sha256": sha,
        "human_users": 0,
        "domains": domains,
        "discovery_advantages": selected,
        "confirmed_direction": {
            m: [
                d
                for d in dd
                if domains["holdout"][d][m + "_correct"]
                > domains["holdout"][d][("smol" if m == "t5" else "t5") + "_correct"]
            ]
            for m, dd in selected.items()
        },
        "student": {},
        "teacher_composition_correct": {m: pair_score(v) for m, v in teachers.items()},
        "denominators": {
            "holdout": len(held),
            "per_domain": 20,
            "composition_pairs": len(pairs),
            "old": len(old),
        },
        "pairs": [[x["id"] for x in pair] for pair in pairs],
    }
    for name, ans in run.items():
        bydomain = {d: score(rr, ans) for d, rr in groups(held).items()}
        result["student"][name] = {
            "correct": score(held, ans),
            "per_domain": bydomain,
            "worst_domain_count": min(bydomain.values()),
            "correct_pairs": pair_score(ans),
            "old": score(old, ans),
            "teacher_exclusive_inherited": {},
        }
        for m, other in (("t5", "smol"), ("smol", "t5")):
            rows = [
                r
                for r in held
                if teachers[m][r["id"]] == r["label"]
                and teachers[other][r["id"]] != r["label"]
            ]
            result["student"][name]["teacher_exclusive_inherited"][m] = [
                score(rows, ans),
                len(rows),
            ]
    (e / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["student"]), flush=True)


if __name__ == "__main__":
    main()
