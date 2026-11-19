"""Physical/readout qualification using counterfactual raw-output probes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import torch

EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT))
from codec import semantic_metrics
from data import make_worlds, render


def predictions(facts, style, logit_strength=20):
    raw = render(facts, style)
    raw["text"] = raw["text"] * logit_strength
    raw["style_logits"] = torch.nn.functional.one_hot(raw["style_index"], 2).float() * 20
    return raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    worlds = make_worlds(128, 731)
    facts, style = worlds["facts"], worlds["style"]
    canonical = semantic_metrics(predictions(facts, style), facts)
    uncertain = semantic_metrics(predictions(facts, style, logit_strength=1), facts)
    missing_raw = predictions(facts, style)
    missing_raw["audio"].zero_()
    missing = semantic_metrics(missing_raw, facts)
    centered_facts = torch.zeros_like(facts)
    wrong = semantic_metrics(predictions(centered_facts + 0.45, style), centered_facts)
    midpoint = semantic_metrics(predictions(facts, torch.zeros_like(style)), facts)
    nonfinite = {}
    for modality in ("text", "audio", "image", "video", "style_logits"):
        malformed = predictions(facts, style)
        malformed[modality].reshape(len(facts), -1)[:, 0] = float("nan")
        result = semantic_metrics(malformed, facts)
        nonfinite[modality] = {"factual_loss": float(result["factual_loss"].mean()),
                               "invalid_nonfinite": float(result["invalid_nonfinite"].mean()),
                               "resolved": float(result["resolved"].mean()),
                               "all_metrics_finite": all(bool(torch.isfinite(x).all()) for x in result.values())}
    keys = ("factual_loss", "correct", "resolved", "correct_resolved", "disagreement",
            "style_lawful", "style_consistent", "lawful_consistent")
    probes = {name: {key: float(result[key].mean()) for key in keys}
              for name, result in (("canonical", canonical), ("uncertain_text", uncertain),
                                   ("missing_audio", missing), ("coherent_wrong", wrong),
                                   ("style_midpoint", midpoint))}
    gates = {
        "canonical_raw_readback": probes["canonical"]["correct_resolved"] == 1
                                  and probes["canonical"]["lawful_consistent"] == 1
                                  and probes["canonical"]["factual_loss"] < 0.001,
        "uncertain_text_not_resolved": probes["uncertain_text"]["correct"] == 1
                                       and probes["uncertain_text"]["correct_resolved"] == 0,
        "missing_audio_not_resolved": probes["missing_audio"]["resolved"] == 0,
        "coherent_wrong_is_wrong": probes["coherent_wrong"]["correct_resolved"] == 0
                                   and probes["coherent_wrong"]["factual_loss"] > 0.05
                                   and probes["coherent_wrong"]["disagreement"] < 0.001,
        "averaged_style_not_lawful": probes["style_midpoint"]["style_lawful"] == 0,
        "nonfinite_outputs_fail_closed": all(row["factual_loss"] == 1
                                             and row["invalid_nonfinite"] == 1
                                             and row["resolved"] == 0
                                             and row["all_metrics_finite"]
                                             for row in nonfinite.values()),
    }
    result = {"schema": "ndu-latent-codec-metric-audit-v1",
              "finished_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Known physical raw-output probes, not heldout learned-model efficacy",
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (EXPERIMENT / "data.py", EXPERIMENT / "codec.py", Path(__file__))},
              "probes": probes, "nonfinite_probes": nonfinite,
              "gates": gates, "all_passed": all(gates.values())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
