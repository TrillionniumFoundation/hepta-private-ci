"""Fit rule-anchored document corrections using only old fit/validation merchants."""
import argparse
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.document_engine import ocr, deliver
from ...continuation_20261027.natural.document_study import score
from .common import freeze, read, save, sha, verify_frozen
from .document_model import fit, options, select


def run(assets, output):
    source = Path(__file__).parent
    manifest = read(assets / "MANIFEST.json")
    output.mkdir(parents=True, exist_ok=False)
    spec = {"training": "Existing fit role24 merchants", "validation": "Existing validation role12 merchants; never oldtest",
        "regularization": [.1, 1., 10., 100.], "thresholds": [0., .05, .1, .2, 1000.],
        "selection": "Max validation entropic certainty-equivalent of document quality, gamma2; tie fewer changed fields, stronger ridge, larger threshold",
        "heldout_not_received": True}
    registration = freeze(source, assets / "MANIFEST.json", output, spec)
    documents = []
    for item in manifest["documents"]:
        if item["role"] not in {"fit", "validation"}:
            continue
        observed = ocr(item["path"], output / "OCR" / item["id"])
        documents.append({**item, "options": options(observed)})
    training = [r for r in documents if r["role"] == "fit"]
    validation = [r for r in documents if r["role"] == "validation"]
    models = {str(penalty): fit(training, penalty) for penalty in spec["regularization"]}
    rows, candidates = [], []
    for penalty, model in models.items():
        for threshold in spec["thresholds"]:
            group = []
            changes = 0
            for document in validation:
                selected, decisions = select(document["options"], model, threshold)
                destination = output / "validation" / document["id"] / f"ridge-{penalty}-threshold-{threshold}"
                destination.mkdir(parents=True, exist_ok=False)
                public = deliver(document["path"], selected, destination)
                row = {"id": document["id"], "regularization": float(penalty), "threshold": threshold,
                    **public, **score(document["reference"], public["answers"]), "decisions": decisions}
                rows.append(row)
                group.append(row["quality"])
                changes += sum(not r["rule_preserved"] for r in decisions)
            candidates.append({"regularization": float(penalty), "threshold": threshold,
                "CE": float(-np.log(np.mean(np.exp(-2 * np.asarray(group)))) / 2),
                "mean_quality": float(np.mean(group)), "changed_fields": changes})
    chosen = min(candidates, key=lambda r: (-r["CE"], r["changed_fields"], -r["regularization"], -r["threshold"]))
    frozen = {"choice": chosen, "model": models[str(chosen["regularization"])], "candidates": candidates,
        "frozen_ns": time.time_ns(), "heldout_generation_not_started": True,
        "development_source_manifest_sha256": sha(assets / "MANIFEST.json")}
    save(output / "TRAINING_MODELS.json", models)
    save(output / "DEVELOPMENT_OPTIONS.json", documents)
    save(output / "VALIDATION_ROWS.json", rows)
    save(output / "FROZEN_MODEL.json", frozen)
    verify_frozen(registration)
    print(chosen, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.output)
