"""One frozen full EG2 owner exports image/audio globals and missing-modality controls."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from budgeted_media_encoder import BudgetedMediaEncoder
from cell_media_inputs import media_rows, save_features
from prepare_cell_media import canonical, sha
from real_cell_features import sha_file
from real_encoder import CANDIDATES, FrozenRealEncoder
from shared_feature_contract import SourceEvent


def export_all(datasets, snapshot, acquisition, output, *, batch_size=4, threads=4):
    if not 1 <= len(datasets) <= 2 or not 1 <= batch_size <= 8 or not 1 <= threads <= 8:
        raise ValueError("bounded multimodal export plan required")
    planned = [(Path(path), *media_rows(path)) for path in datasets]
    if len({item[2] for item in planned}) != len(planned):
        raise ValueError("one fixed cohort per modality")
    acquired = json.loads(Path(acquisition).read_bytes())
    spec = CANDIDATES["embeddinggemma2_740m"]
    if acquired["revision"] != spec["revision"] or acquired["repository"] != spec["repository"]:
        raise ValueError("pinned full EG2 acquisition required")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(threads)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate="embeddinggemma2_740m", snapshot=snapshot,
        revision=spec["revision"], expected_inventory_sha256=acquired["inventory_sha256"],
        operator_accepted_terms=True, profile="full", device="cpu", max_tokens=1024,
        task="classification", generation=1, scope_id="real-media-20261024")
    shared = BudgetedMediaEncoder(owner, vision_soft_tokens=70)
    load = {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "loaded_model": owner.accounting, "encoder_instances": 1}
    counts = {"image": 0, "audio": 0}
    handles = []
    for name, attribute in (("image", "vision_tower"), ("audio", "audio_tower")):
        def entered(_module, _args, name=name):
            counts[name] += 1
        handles.append(getattr(owner._model, attribute).register_forward_pre_hook(entered))
    reports = {}
    try:
        for dataset, rows, modality, digest in planned:
            target = root / modality
            target.mkdir()
            observation = time.time_ns()
            plan = {"schema": "hepta.real-media-features.v1", "dataset_sha256": digest,
                "source_ids": [row["source_id"] for row in rows], "input_modality": modality,
                "predictor_sha256": sha(canonical(rows)), "predictor_fields": ["neutral_text", "actual_media_bytes"],
                "gold_fields_enter_encoder": False, "vision_soft_token_budget": 70,
                "max_tokens": 1024, "batch_size": batch_size, "threads": threads,
                "extractor_source_sha256": sha(Path(__file__).read_bytes()),
                "observation_ns": observation, "scope": "recognition transfer; unknown pretraining overlap"}
            (target / "plan.json").write_bytes(canonical(plan) + b"\n")
            started, cpu = time.perf_counter_ns(), time.process_time_ns()
            matrices, receipts, sources, identity = [], [], [], None
            before, forward_before = dict(counts), owner._calls
            with (target / "batch-receipts.jsonl").open("x") as log:
                for begin in range(0, len(rows), batch_size):
                    batch_rows = rows[begin:begin + batch_size]
                    batch = shared.extract_records([row["record"] for row in batch_rows], media_root=dataset.parent,
                        events=[SourceEvent(row["source_id"], row["source_version"], observation) for row in batch_rows],
                        expected_identity=owner.identity, retention="global")
                    if identity is not None and batch.feature_identity_digest != identity:
                        raise ValueError("feature identity changed between batches")
                    identity = batch.feature_identity_digest
                    matrices.append(batch.read_global().numpy())
                    sources.extend(batch.source_record_digests)
                    receipt = {**shared.last_receipt, "first_row": begin}
                    receipts.append(receipt)
                    log.write(canonical(receipt).decode() + "\n")
                    log.flush()
                    if len(receipts) % 10 == 0:
                        print(json.dumps({"modality": modality, "encoded": begin + len(batch_rows),
                                          "total": len(rows), "forward_calls": owner._calls}), flush=True)
            encoding = {"wall_ns": time.perf_counter_ns() - started,
                        "cpu_ns": time.process_time_ns() - cpu,
                        "physical_forward_calls": owner._calls - forward_before,
                        "tower_forward_calls": {name: counts[name] - before[name] for name in counts}}
            if encoding["tower_forward_calls"][modality] != len(receipts):
                raise ValueError("actual modality tower did not run once per model forward")
            if encoding["tower_forward_calls"]["audio" if modality == "image" else "image"]:
                raise ValueError("unrequested modality tower ran")
            neutral = shared.extract_text([rows[0]["record"]["text"]],
                events=[SourceEvent("modality-off:" + modality, "control:v1", observation)],
                expected_identity=owner.identity, retention="global")
            if neutral.feature_identity_digest != identity:
                raise ValueError("missing-modality control must retain the exact shared feature identity")
            control = np.repeat(neutral.read_global().numpy(), len(rows), axis=0).astype(np.float32)
            with (target / "text_only_features.npy").open("xb") as stream:
                np.save(stream, control, allow_pickle=False)
            control_report = {"schema": "hepta.media-removed-control.v1", "dataset_sha256": digest,
                "source_ids": plan["source_ids"], "parent_feature_identity": identity,
                "feature_identity": neutral.feature_identity_digest, "feature_shape": list(control.shape),
                "feature_archive_sha256": sha_file(target / "text_only_features.npy"),
                "feature_tensor_sha256": sha(control.tobytes()), "input_fields": ["text"],
                "media_inputs_present": False, "neutral_text": rows[0]["record"]["text"],
                "encoder_identity": asdict(owner.identity), "checkpoint_inventory_sha256": acquired["inventory_sha256"],
                "counterfactual_source_record_digest": neutral.source_record_digests[0],
                "receipt": shared.last_receipt, "calibration_refitted": False,
                "semantics": "same neutral-text-only global substituted for each heldout media input"}
            (target / "text_only_report.json").write_bytes(canonical(control_report) + b"\n")
            # A second label-free verification detects media mutation during extraction.
            after_rows, after_modality, after_digest = media_rows(dataset)
            if rows != after_rows or digest != after_digest or modality != after_modality:
                raise ValueError("source cohort changed during extraction")
            reports[modality] = save_features(target, np.concatenate(matrices), plan, identity,
                {"load": load, "encoding": encoding, "encoder_identity": asdict(owner.identity),
                 "feature_extractor_sha256": shared.extractor_sha256,
                 "effective_processor": shared.processor_configuration(), "receipts": receipts,
                 "source_record_digests": sources,
                 "source_media_bytes": sum(row["media_bytes"] for row in rows),
                 "text_only_control": {"path": "text_only_features.npy", "sha256": sha_file(target / "text_only_features.npy"),
                     "feature_tensor_sha256": sha(control.tobytes()), "receipt": shared.last_receipt,
                     "semantics": "frozen heads and calibration receive only the identical neutral text, media removed"},
                 "quality_qualified": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"})
    finally:
        for handle in handles:
            handle.remove()
    summary = {"schema": "hepta.real-media-owner-run.v1", "load": load,
               "encoder_instances": 1, "forward_calls": owner._calls, "tower_forward_calls": counts,
               "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
               "reports": {key: sha_file(root / key / "report.json") for key in reports}}
    (root / "owner-run.json").write_bytes(canonical(summary) + b"\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", required=True, nargs="+")
    for name in ("snapshot", "acquisition", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    print(json.dumps(export_all(**vars(parser.parse_args()))))
