"""Read-only diagnosis of the frozen FSDD Transformer CE audit failure.

This does not amend the registered absolute tolerance, replace its failed
audit, select a model, or train anything. It reproduces the original FP32
producer and separately compares independent higher-precision reductions.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp
import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1 import training
from .model import build_model


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
RUN_ID = "fsdd__transformer__9202"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "source.py").write_bytes(Path(__file__).read_bytes())
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    protocol_path = PACKAGE / "CONTENT002_PROTOCOL.json"
    protocol = read(protocol_path)
    for relative, expected in protocol["source_files_sha256"].items():
        assert sha(ROOT / relative) == expected, "Registered source changed"
    directory = PACKAGE / "results/content002/runs" / RUN_ID
    paths = {
        "protocol": protocol_path,
        "frozen_analysis": PACKAGE / "results/content_analysis002/ANALYSIS.json",
        "summary": directory / "summary.json",
        "selection": directory / "selection.json",
        "selected_weights": directory / "selected.npz",
        "predictions": directory / "test_predictions.npz",
        "data": ROOT / protocol["data"]["fsdd"]["path"],
    }
    inputs = {key: dict(path=str(path.relative_to(ROOT)), sha256=sha(path))
              for key, path in paths.items()}
    analysis, summary = read(paths["frozen_analysis"]), read(paths["summary"])
    bad = [row for row in analysis["audits"] if not row["valid"]]
    assert analysis["valid"] == 175 and analysis["invalid"] == 1
    assert bad == [dict(job=dict(task="fsdd", model="transformer", seed=9202), valid=False,
                        error="AssertionError: cross entropy summary")]
    assert sha(paths["data"]) == protocol["data"]["fsdd"]["sha256"]
    stated = summary["holdout"]["test"]
    with np.load(paths["predictions"], allow_pickle=False) as archive:
        saved = {key: np.array(archive[key], copy=True) for key in archive.files}
    split = training.load_split(paths["data"], "test")
    y = split["y"].numpy()
    mask = y != -100
    samples, steps = np.nonzero(mask)
    assert np.array_equal(saved["supervised"], mask)
    assert np.array_equal(saved["sample_indices"], samples)
    assert np.array_equal(saved["step_indices"], steps)
    assert np.array_equal(saved["labels"], y[mask])
    assert saved["logits"].dtype == np.float32 and np.isfinite(saved["logits"]).all()
    logits = saved["logits"].astype(np.float64)
    labels = saved["labels"]
    ce64 = float(np.mean(logsumexp(logits, axis=-1)-logits[np.arange(len(labels)), labels]))
    ce_torch64 = float(F.cross_entropy(torch.from_numpy(logits), torch.from_numpy(labels), reduction="mean"))
    independent_terms = []
    for row, label in zip(logits, labels):
        maximum = float(row.max())
        independent_terms.append(maximum + math.log(math.fsum(math.exp(float(v)-maximum) for v in row)) - float(row[label]))
    ce_fsum64 = math.fsum(independent_terms) / len(labels)
    full = torch.zeros((*y.shape, logits.shape[-1]), dtype=torch.float32)
    full[torch.from_numpy(mask)] = torch.from_numpy(saved["logits"])
    original_batches = []
    for start in range(0, len(y), 128):
        stop = min(len(y), start+128)
        batch_logits, batch_y = full[start:stop], split["y"][start:stop]
        loss32 = float(F.cross_entropy(batch_logits.flatten(0, 1), batch_y.flatten(), ignore_index=-100, reduction="sum"))
        loss64 = float(F.cross_entropy(batch_logits.double().flatten(0, 1), batch_y.flatten(), ignore_index=-100, reduction="sum"))
        original_batches.append(dict(start=start, stop=stop, sum_fp32=loss32, sum_fp64=loss64,
                                     difference_fp32_minus_fp64=loss32-loss64))
    producer_ce = sum(row["sum_fp32"] for row in original_batches) / len(labels)
    model = build_model("transformer", split["x"].shape[-1],
                        protocol["data"]["fsdd"]["output_dim"], width=32, depth=1, seed=9202)
    training.load_weights(paths["selected_weights"], model)
    model.eval()
    replay_parts, replay_batch_sums = [], []
    with torch.no_grad():
        for start in range(0, len(y), 128):
            x, dt, batch_y = (split[key][start:start+128] for key in ("x", "dt", "y"))
            replay, _ = model(x, dt, return_sequence=True)
            replay_parts.append(replay.numpy()[batch_y.numpy() != -100])
            replay_batch_sums.append(float(F.cross_entropy(replay.flatten(0, 1), batch_y.flatten(),
                                                          ignore_index=-100, reduction="sum")))
        small = model(split["x"][:4], split["dt"][:4], return_sequence=True, return_aux=False).numpy()
    replay_logits = np.concatenate(replay_parts)
    replay_ce = sum(replay_batch_sums) / len(labels)
    keep = samples < 4
    small_error = float(np.max(np.abs(small[samples[keep], steps[keep]] - saved["logits"][keep])))
    accuracy = float((saved["logits"].argmax(-1) == labels).mean())
    difference = ce64-stated["cross_entropy"]
    checks = {
        "saved_logits_producer_fp32_summary_exact": producer_ce == stated["cross_entropy"],
        "full_512_sample_original_batch_logits_bitwise_equal": np.array_equal(replay_logits, saved["logits"]),
        "full_selected_checkpoint_fp32_summary_exact": replay_ce == stated["cross_entropy"],
        "saved_argmax_exact": np.array_equal(saved["predictions"], saved["logits"].argmax(-1)),
        "accuracy_summary_exact": accuracy == stated["accuracy"],
        "three_fp64_reductions_agree_within_1e_12": max(abs(ce64-ce_torch64), abs(ce64-ce_fsum64)) <= 1e-12,
        "original_four_sample_replay_tolerance_unchanged": small_error <= 5e-5,
        "original_absolute_ce_gate_still_fails": abs(difference) >= 2e-6,
    }
    for key, path in paths.items():
        assert sha(path) == inputs[key]["sha256"], "Input changed during diagnosis"
    result = {
        "schema": "hcsn-frozen-ce-failure-diagnostic.v1",
        "status": "reproduced" if all(checks.values()) else "unexpected_difference",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID, "source_sha256": sha(__file__), "input_sha256": inputs,
        "torch_version": torch.__version__, "checks": checks,
        "original_frozen_audit": dict(valid=175, invalid=1, absolute_ce_tolerance=2e-6,
                                       record=bad[0], preserved_unchanged=True),
        "cross_entropy": dict(stated=stated["cross_entropy"], saved_logits_original_producer_fp32=producer_ce,
            full_checkpoint_original_producer_fp32=replay_ce, scipy_fp64=ce64, torch_fp64=ce_torch64,
            independent_fsum_fp64=ce_fsum64, fp64_minus_stated=difference,
            relative_absolute_difference=abs(difference)/abs(ce64),
            fp32_spacing_at_stated=float(np.spacing(np.float32(stated["cross_entropy"]))),
            difference_in_fp32_spacings=abs(difference)/float(np.spacing(np.float32(stated["cross_entropy"])))),
        "original_batches": original_batches, "accuracy": accuracy,
        "full_replay_max_abs_logit_error": float(np.max(np.abs(replay_logits-saved["logits"]))),
        "original_four_sample_replay_max_abs_logit_error": small_error,
        "scope": "Independent read-only diagnosis, not an amended acceptance gate or replacement analysis; no weights, predictions, selections, statistics, registered sources or frozen outcomes changed; no training.",
    }
    write(output / "RESULT.json", result)
    write(output / "EXECUTION.json", dict(source_sha256=sha(__file__), result_sha256=sha(output / "RESULT.json"),
        own_cpu_seconds_through_receipt=time.process_time(), scope="Inner process timer nested in enclosing measured_support wait4"))
    print(json.dumps({key: result[key] for key in ("status", "checks", "cross_entropy")}), flush=True)
    if result["status"] != "reproduced":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
