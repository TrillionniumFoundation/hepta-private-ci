"""Post-publication evaluation of every frozen content model and channel cell."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import torch
from ..campaign import configure, load_candidate, read_plan, sha, write
from ..data import dataset
from .publication_gate import require_publication


METRICS = ("all_prefix_accuracy", "final_prefix_accuracy", "all_prefix_nll", "final_prefix_nll")


def values(logits, y):
    logp = torch.log_softmax(logits, -1)
    correct = logits.argmax(-1) == y
    nll = -logp.gather(-1, y[..., None]).squeeze(-1)
    return logp.exp().numpy(), correct.numpy(), nll.numpy()


def difference(a, b):
    return {key: a[key]-b[key] for key in METRICS}


def evaluate(run, out, source_head, candidate_head, publication):
    if any(not re.fullmatch(r"[0-9a-f]{40}", head) for head in (source_head, candidate_head)):
        raise ValueError("Published source and candidate identities are required")
    gate = require_publication(run, publication, source_head, candidate_head)
    out.mkdir(parents=True, exist_ok=False)
    plan = read_plan(run)
    candidates = json.loads((run/"CANDIDATES.json").read_text())
    if candidates["plan_sha256"] != sha(run/"PLAN.json") or len(candidates["models"]) != 36:
        raise RuntimeError("Candidate manifest differs from training plan")
    protocol_path = Path(__file__).with_name("EVALUATION_PROTOCOL.json")
    protocol = json.loads(protocol_path.read_text())
    write(out/"START.json", {"source_remote_head": source_head, "candidate_remote_head": candidate_head,
          "candidate_manifest_sha256": sha(run/"CANDIDATES.json"), "protocol": protocol,
          "evaluation_source_sha256": sha(Path(__file__)), "evaluation_protocol_sha256": sha(protocol_path),
          "publication_gate": gate})
    rows, identities = [], {}
    for split in protocol["splits"]:
        for task in protocol["tasks"]:
            raw_x, y, groups, orders, identity = dataset(task, split)
            identities[task+"/"+split] = identity
            ids = identity["ids"]
            actors = [sorted(set(re.findall(r"(?<!\d)(\d{4})_", identifier))) for identifier in ids]
            write(out/f"{task}-{split}-OBJECTS.json", {"objects": [
                {"index": i, "source_id": identifier, "actor_ids": actors[i]} for i, identifier in enumerate(ids)],
                "dependent_orders_per_object": 10, "source_pairs_can_share_recordings": task == "av_binding"})
            for entry in candidates["models"]:
                if entry["task"] != task:
                    continue
                directory = run/entry["directory"]
                if sha(directory/"weights.pt") != entry["weights_sha256"] or sha(directory/"TRAIN.json") != entry["train_metadata_sha256"]:
                    raise RuntimeError("Published candidate file identity differs")
                model, norm = load_candidate(directory)
                x = norm.apply(raw_x)
                modes = ("hx_full", "hx_margin") if entry["family"] in ("hx_full", "hx_margin") else (entry["family"],)
                for mode in modes:
                    with torch.inference_mode():
                        logits, events = model(x, mode=mode, return_events=True)
                        probabilities, correct, nll = values(logits, y)
                    if not np.isfinite(probabilities).all() or not np.allclose(probabilities.sum(-1), 1, rtol=0, atol=1e-12):
                        raise ArithmeticError("Invalid actual class probabilities")
                    reset = torch.stack([e["reset"] for e in events], 1).numpy()
                    restored = torch.stack([e["restored"] for e in events], 1).numpy()
                    label = f"{task}-{split}-{entry['family']}-{entry['seed']}-execute-{mode}"
                    raw_path = out/(label+".npz")
                    np.savez_compressed(raw_path, probabilities=probabilities, labels=y.numpy(),
                        logits=logits.numpy(),
                        predictions=logits.argmax(-1).numpy(), object_index=groups,
                        accepted_order=np.asarray(orders), reset=reset, restored=restored)
                    metrics = {"all_prefix_accuracy": float(correct.mean()), "final_prefix_accuracy": float(correct[:, -1].mean()),
                               "all_prefix_nll": float(nll.mean()), "final_prefix_nll": float(nll[:, -1].mean())}
                    by_object = [{"object_index": i, "all_prefix_accuracy": float(correct[groups == i].mean()),
                                  "final_prefix_accuracy": float(correct[groups == i, -1].mean()),
                                  "all_prefix_nll": float(nll[groups == i].mean()),
                                  "final_prefix_nll": float(nll[groups == i, -1].mean())} for i in range(len(ids))]
                    write(out/(label+"-OBJECT_METRICS.json"), by_object)
                    rows.append({"task": task, "split": split, "training_family": entry["family"], "seed": entry["seed"],
                                 "execution_mode": mode, **metrics, "prefix_accuracy": correct.mean(0).tolist(),
                                 "prefix_nll": nll.mean(0).tolist(), "recording_or_pair_objects": len(ids),
                                 "dependent_sequences": len(x), "reset_cell_events": int(reset.sum()),
                                 "restoration_cell_events": int(restored.sum()), "raw_file": raw_path.name,
                                 "raw_sha256": sha(raw_path), "weights_sha256": entry["weights_sha256"]})
    contrasts = []
    for split in protocol["splits"]:
        for task in protocol["tasks"]:
            for seed in plan["protocol"]["seeds"]:
                cells = {(r["training_family"], r["execution_mode"]): r for r in rows
                         if (r["split"], r["task"], r["seed"]) == (split, task, seed)}
                A, B, C, D = (cells[key] for key in (("hx_full", "hx_full"), ("hx_full", "hx_margin"),
                                                     ("hx_margin", "hx_full"), ("hx_margin", "hx_margin")))
                d = {"A-B": difference(A, B), "C-D": difference(C, D), "A-C": difference(A, C), "B-D": difference(B, D)}
                d["(A-B)-(C-D)"] = {key: d["A-B"][key]-d["C-D"][key] for key in METRICS}
                for family in ("hx_margin", "ordinary_gate", "gru", "ssm", "history"):
                    d["A-versus-"+family] = difference(A, cells[family, family])
                contrasts.append({"task": task, "split": split, "seed": seed, "descriptive_only": d})
    if len(rows) != protocol["condition_records"]:
        raise RuntimeError("Incomplete frozen evaluation roster")
    write(out/"RESULT.json", {"schema": "hcsn-v13-content-evaluation.v1", "condition_records": len(rows),
          "input_identities": identities, "rows": rows, "contrasts": contrasts,
          "all_declared_conditions_executed": True, "quality_admission_passed": False,
          "all_blockers_closed": False, "production_activation": False,
          "scope": "Historical fixed-candidate descriptive replay. No best-family selection or independent confirmation claim."})
    print(json.dumps({"conditions": len(rows), "all_declared_conditions_executed": True, "quality_admission_passed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-remote-head", required=True); parser.add_argument("--candidate-remote-head", required=True)
    parser.add_argument("--publication", type=Path, required=True)
    args = parser.parse_args(); configure()
    evaluate(args.run, args.out, args.source_remote_head, args.candidate_remote_head, args.publication)
