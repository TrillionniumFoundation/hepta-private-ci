"""Read-only family diagnostics through the existing trained tensor consumer.

Reuses verified receipts, the frozen-feature loader and HeadTensorBundleV2.
No encoder call, training, external effect, selection or trust owner is added.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

import numpy as np
import torch

from binomial_support import family_support_report
from decision_cell_metrics import HEADS, selection_statistics


def decision_counts(*, predictions: dict, labels: dict, supported: list[bool],
                    ood_rejected: list[bool], in_domain: list[bool]) -> dict:
    """Count complete decisions directly; never reverse-engineer rounded rates."""
    selection_statistics(predictions, labels, supported, ood_rejected, in_domain)
    if any(accepted and rejected for accepted, rejected in zip(supported, ood_rejected)):
        raise ValueError("support contradicts the OOD predicate")
    correct = [inside and all(
        predictions[name][index] == labels[name][index] or
        (name == "target" and labels[name][index] == -1) for name in HEADS)
        for index, inside in enumerate(in_domain)]
    return {
        "ood_errors": sum(not inside and not rejected for inside, rejected in zip(in_domain, ood_rejected)),
        "ood_trials": sum(not inside for inside in in_domain),
        "decision_errors": sum(accepted and not matched for accepted, matched in zip(supported, correct)),
        "decision_trials": sum(supported),
    }


def replay_family(output_dir: Path, expected_summary_sha256: str) -> dict:
    """Recompute the complete fixed bakeoff family, binding old and new sources.

    The existing summary/receipt verifier must accept every configured backend.
    This is retrospective synthetic-panel reanalysis, not preregistration or a
    fresh encoder run. The exact original summary digest is caller-supplied.
    """
    import decision_cell_bakeoff as bakeoff
    from head_retraining import load_frozen_features

    if type(expected_summary_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_summary_sha256):
        raise ValueError("invalid frozen summary digest")
    source = bakeoff.repository_source()
    models = sorted(bakeoff.MODEL_SPECS)
    verified = bakeoff.verify_outputs(output_dir, models)
    if verified["summary_sha256"] != expected_summary_sha256:
        raise ValueError("frozen summary identity mismatch")
    identities, observations, replays = {}, {}, []
    for row in verified["models"]:
        receipt_path = Path(row["receipt_path"])
        receipt, digest = bakeoff.verified_receipt(receipt_path)
        if digest != row["receipt_sha256"] or receipt["model_name"] != row["model_name"]:
            raise ValueError("receipt changed during family replay")
        if receipt.get("synthetic_panel_only") is not True:
            raise ValueError("this replay only admits the retained synthetic panel")
        examples, states, targets = load_frozen_features(receipt, receipt_path.parent.parent)
        selected = [index for index, example in enumerate(examples) if example.split in ("test", "ood_test")]
        if {examples[index].split for index in selected} != {"test", "ood_test"}:
            raise ValueError("both held-out populations are required")
        head = receipt["head_artifact"]
        manifest = bakeoff._tensor_module.strict_json(bakeoff._tensor_module.checked_bytes(
            Path(head["manifest_path"]), head["manifest_sha256"], 1024 * 1024))
        bundle = bakeoff._tensor_module.HeadTensorBundleV2(
            manifest_path=Path(head["manifest_path"]), manifest_sha256=head["manifest_sha256"],
            weights_path=Path(head["weights_path"]), weights_sha256=head["weights_sha256"],
            expected_base_snapshot=receipt["base_model"]["snapshot_digest"],
            expected_runtime_profile=manifest["runtime_profile"])
        predictions = {name: [] for name in HEADS}
        labels = {name: [int(getattr(examples[index], name)) for index in selected] for name in HEADS}
        inside = [examples[index].ood == 0 for index in selected]
        supported, rejected, trace = [], [], []
        for offset in range(0, len(selected), 32):
            indices = selected[offset:offset + 32]
            probabilities = bundle.probabilities(torch.from_numpy(states[indices]),
                                               torch.from_numpy(targets[indices]))
            current = {name: probabilities[name].argmax(dim=-1).tolist() for name in HEADS}
            accepts = probabilities["supported"].tolist()
            rejects = (probabilities["ood"][:, 1] >= manifest["calibration"]["maximum_ood_probability"]).tolist()
            for name in HEADS:
                predictions[name].extend(current[name])
            supported.extend(accepts)
            rejected.extend(rejects)
            for local, index in enumerate(indices):
                trace.append({"example_id": examples[index].example_id,
                              "prediction": [current[name][local] for name in HEADS],
                              "supported": accepts[local], "ood_rejected": rejects[local]})
        counts = decision_counts(predictions=predictions, labels=labels, supported=supported,
                                 ood_rejected=rejected, in_domain=inside)
        name = receipt["model_name"]
        identities[name], observations[name] = digest, counts
        replays.append({
            "model_name": name, "training_source": receipt["source"], "training_receipt_sha256": digest,
            "dataset_sha256": receipt["dataset_sha256"],
            "embedding_sha256": receipt["embedding_artifact"]["sha256"],
            "head_manifest_sha256": head["manifest_sha256"], "weights_sha256": head["weights_sha256"],
            "parameter_group_sha256": manifest["parameter_group_sha256"],
            "counts": counts, "held_out_rows": len(selected), "in_domain_rows": sum(inside),
            "supported_in_domain_rows": sum(a and b for a, b in zip(supported, inside)),
            "trace_head_order": list(HEADS), "prediction_trace": trace,
            "prediction_trace_sha256": bakeoff.sha256_bytes(bakeoff.canonical_json(trace)),
        })
    # Resolve the complete frozen family again, including all bound artifact bytes.
    if bakeoff.verify_outputs(output_dir, models) != verified or bakeoff.repository_source() != source:
        raise ValueError("source or frozen family changed during replay")
    return {
        "schema": "hepta.decision-cell-family-artifact-replay.v1",
        "consumer_source": source, "input_summary_sha256": expected_summary_sha256,
        "implementation_sha256": {name: bakeoff.sha256_file(Path(__file__).with_name(name))
            for name in ("family_replay.py", "binomial_support.py", "head_retraining.py", "decision_cell_bakeoff.py")},
        "tensor_consumer_sha256": bakeoff.sha256_file(bakeoff._TENSOR_PATH),
        "process": {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__,
                    "platform": platform.platform(), "device": "cpu", "threads": torch.get_num_threads()},
        "replays": replays, "family_support": family_support_report(candidate_receipts=identities,
                                                                    observations=observations),
        "scope": "retrospective_synthetic_panel_reanalysis", "weights_reloaded": True,
        "base_reencoded_this_run": False, "training_executed_this_run": False,
        "independence_established": False, "calibration_trust_granted": False,
        "runtime_selection_eligible": False, "prospective_future_window_evidence": False,
        "production_activation": False, "operator_acceptance": False,
    }


def command_family_support(args) -> int:
    """Existing bakeoff CLI entry; privately publish one immutable diagnostic."""
    result = replay_family(args.output_dir, args.summary_sha256)
    data = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    descriptor = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "REPLAYED_FROZEN_FAMILY_DIAGNOSTIC", "report": str(args.report),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "all_count_bounds_met": result["family_support"]["all_count_bounds_met"],
                      "calibration_trust_granted": False}, sort_keys=True))
    return 0
