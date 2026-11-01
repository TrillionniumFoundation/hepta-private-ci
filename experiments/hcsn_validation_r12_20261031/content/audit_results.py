"""Recompute scores and model/data/selection invariants from original records."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import logsumexp
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def equal_group(left, right, prefix):
    keys = [key for key in left if key.startswith(prefix)]
    return bool(keys) and all(key in right and torch.equal(left[key], right[key]) for key in keys)


def audit(root, source_root):
    root, source_root = Path(root), Path(source_root)
    protocol = json.loads((root/"PROTOCOL.json").read_text())
    freeze = json.loads((root/"SOURCE_FREEZE.json").read_text())
    candidates = json.loads((root/"CANDIDATE_FREEZE.json").read_text())
    assert sha(root/"PROTOCOL.json") == freeze["protocol_sha256"] == candidates["protocol_sha256"]
    for path, expected in freeze["files"].items():
        assert sha(source_root/path) == expected, path
    checks, scores, initial_states, batches, summaries = [], [], {}, {}, {}
    for job in protocol["jobs"]:
        entry = candidates["candidates"][job["id"]]
        folder = root/entry["path"]
        summary = json.loads((folder/"summary.json").read_text())
        assert summary["completed"] and not summary["heldout_opened"]
        assert sha(folder/"selected.pt") == entry["sha256"] == summary["selected_checkpoint_sha256"]
        assert sha(folder/"initial.pt") == summary["initial_sha256"]
        assert sha(folder/"final.pt") == summary["final_checkpoint_sha256"]
        initial = torch.load(folder/"initial.pt", weights_only=False, map_location="cpu")["state"]
        selected = torch.load(folder/"selected.pt", weights_only=False, map_location="cpu")
        final = torch.load(folder/"final.pt", weights_only=False, map_location="cpu")
        expected_step = min(summary["validations"], key=lambda x: x["loss"])["step"]
        assert expected_step == summary["selected_step"] == selected["step"] == entry["step"]
        trace = [json.loads(line) for line in (folder/"trace.jsonl").read_text().splitlines()]
        updates = protocol["donor_updates"] if job["kind"] == "donor" else protocol["fit_updates"]
        assert [row["step"] for row in trace] == list(range(1, updates+1))
        assert all(np.isfinite(row["loss"]) and np.isfinite(row["gradient_norm"]) for row in trace)
        assert all(torch.isfinite(value).all() for value in selected["model_state"].values())
        if job["kind"] == "fit":
            group = (job["task"], job["seed"])
            indices = [row["batch_indices"] for row in trace]
            if group in batches:
                assert batches[group] == indices
            batches[group] = indices
            donor = candidates["candidates"][job["donor"]]
            assert selected["donor_sha256"] == donor["sha256"]
            donor_payload = torch.load(root/donor["path"]/"selected.pt", map_location="cpu", weights_only=False)
            assert all(torch.equal(initial["encoder."+key], value) for key,value in donor_payload["encoder_state"].items())
            if job["mode"] == "frozen_frontend":
                assert equal_group(initial, selected["model_state"], "encoder.")
                assert equal_group(initial, final["model_state"], "encoder.")
            if job["family"] in ("ordinary_dual", "probit", "analytic"):
                key = (job["task"], job["seed"], job["mode"])
                if key in initial_states:
                    assert equal_group(initial_states[key], initial, "core.")
                    assert equal_group(initial_states[key], initial, "readout.")
                initial_states[key] = initial
            with np.load(folder/"validation_predictions.npz", allow_pickle=False) as p:
                ce = float(np.mean(logsumexp(p["logits"].astype(float), axis=1)-p["logits"][np.arange(len(p["labels"])), p["labels"]]))
                assert abs(ce-summary["selected_validation"]["ce"]) < 2e-6
            heldout = root/"heldout"/job["id"]
            published = json.loads((heldout/"summary.json").read_text())
            assert published["checkpoint"] == entry
            assert published["candidate_freeze_sha256"] == sha(root/"CANDIDATE_FREEZE.json")
            for domain in protocol["domains"][job["task"]]:
                path = heldout/(domain+".npz")
                with np.load(path, allow_pickle=False) as values:
                    logits, labels = values["logits"].astype(float), values["labels"]
                    assert len(labels) == protocol["splits"]["test"][0]
                    assert np.isfinite(logits).all()
                    normalizer = logsumexp(logits, axis=1)
                    probability = np.exp(logits-normalizer[:,None])
                    actual = dict(accuracy=float((logits.argmax(-1)==labels).mean()),
                        ce=float(np.mean(normalizer-logits[np.arange(len(labels)), labels])),
                        brier=float(np.mean(np.sum((probability-np.eye(logits.shape[1])[labels])**2, axis=1))))
                    for metric, value in actual.items():
                        assert abs(value-published["results"][domain][metric]) < 3e-6, (job["id"],domain,metric)
                    assert str(values["input_sha256"]) == published["results"][domain]["input_sha256"]
                    scores.append(dict(job=job["id"], task=job["task"], seed=job["seed"], mode=job["mode"],
                        family=job["family"], domain=domain, n=len(labels), **actual, raw_sha256=sha(path),
                        selected_step=summary["selected_step"], parameters=summary["parameters"],
                        body_cpu_seconds=summary["body_cpu_seconds"]))
        summaries[job["id"]] = summary
        checks.append(dict(job=job["id"], selected_step=summary["selected_step"], checks_passed=True))
    return dict(passed=True, source_files=len(freeze["files"]), jobs=len(checks), checks=checks,
                prediction_tables=len(scores), prediction_rows=sum(row["n"] for row in scores), scores=scores,
                parameter_pair_groups=len(initial_states), exact_batch_stream_groups=len(batches),
                step_zero_selected=sum(row["selected_step"]==0 for row in checks),
                limitations="Recomputed raw scores and recorded identities/selection; not independent natural-world validation or proof of absence of undisclosed external accesses. No test-based candidate modification.")


def report(result, output):
    rows = result["scores"]
    domains = []
    for row in rows:
        key = (row["task"], row["mode"], row["family"], row["domain"])
        if key not in domains:
            domains.append(key)
    lines = ["# R12 content results", "", "All scores below are independent reconstructions of the retained predictions. Three fitting seeds share the same fixed data; the intervals of a new natural population and foundation-model qualification are not established.", "", "## Every task, mode, family and stress domain", "", "| Task | Mode | Family | Domain | Mean accuracy | Mean CE | Seed accuracies |", "|---|---|---|---|---:|---:|---|"]
    for key in domains:
        selected = sorted([row for row in rows if (row["task"],row["mode"],row["family"],row["domain"])==key], key=lambda r:r["seed"])
        lines.append("| " + " | ".join(key) + f" | {np.mean([r['accuracy'] for r in selected]):.6f} | {np.mean([r['ce'] for r in selected]):.6f} | " + ", ".join(f"{r['accuracy']:.6f}" for r in selected) + " |")
    lines += ["", "## Primary paired analytic increments", "", "Each entry is analytic minus ordinary_dual. Positive means alone are not superiority findings; full retained stress domains and separately metered costs determine interpretation.", "", "| Task | Mode | Domain | Three fit differences | Mean |", "|---|---|---|---|---:|"]
    contrast_keys = []
    for row in rows:
        key = (row["task"],row["mode"],row["domain"])
        if key not in contrast_keys:
            contrast_keys.append(key)
    for key in contrast_keys:
        indexed = {(r["family"],r["seed"]):r for r in rows if (r["task"],r["mode"],r["domain"])==key}
        seeds = sorted({r["seed"] for r in rows})
        delta = [indexed[("analytic",s)]["accuracy"]-indexed[("ordinary_dual",s)]["accuracy"] for s in seeds]
        lines.append("| " + " | ".join(key) + " | " + ", ".join(f"{v:+.6f}" for v in delta) + f" | {np.mean(delta):+.6f} |")
    Path(output).write_text("\n".join(lines)+"\n")


if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args();result=audit(args.root,Path(__file__).resolve().parent)
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/"AUDIT.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    report(result,args.output/"REPORT.md")
    print(json.dumps({key:result[key] for key in ("passed","jobs","prediction_tables","prediction_rows","step_zero_selected")}))
