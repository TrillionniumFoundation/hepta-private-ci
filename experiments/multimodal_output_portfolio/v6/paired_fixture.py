"""Export a complete, already observed v6 paired census for owner replay.

Fixed selection: NDU-trained risk-aware controller versus dev-tuned static,
every future source pair and seed, at the largest registered budget. This is
posthoc engineering, with no new model execution, scientific sample or authority.
"""

import argparse
import gzip
import itertools
import json
import math
from pathlib import Path
import random
import struct
import subprocess

from .terminal_fixture import canonical, checked_read, sha


SCHEMA = "hepta.ndu-v6.paired-owner-fixture.v1"
BASELINE = "fixed_dev_tuned"
CANDIDATE = "risk_aware_recursive"
TRAINING = "terminal_entropic_ndu"
SCOPE = "Previously observed completed outputs; posthoc engineering only; no new scientific samples or external observer authentication"


def loss_q32(value):
    """Preserve original JSON binary64 and round ties to even, as the owner does."""
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid bounded loss")
    return round(float(value) * (1 << 32))


def test_source_ids(cache_bytes, manifest):
    """Rebuild the historical test identity order without Torch or model inference."""
    pools, observed, conflicts = {}, {}, set()
    for partition, prefix in (("train", "train"), ("test", "t10k")):
        images = gzip.decompress(cache_bytes[f"{prefix}-images-idx3-ubyte.gz"])
        labels = gzip.decompress(cache_bytes[f"{prefix}-labels-idx1-ubyte.gz"])
        magic, count, height, width = struct.unpack(">IIII", images[:16])
        if ((magic, height, width) != (2051, 28, 28) or len(images) != 16 + 784 * count
                or struct.unpack(">II", labels[:8]) != (2049, count) or len(labels) != 8 + count):
            raise ValueError("Invalid original IDX archives")
        hashes = [sha(images[16 + 784 * i:16 + 784 * (i + 1)]) for i in range(count)]
        for digest, label in zip(hashes, labels[8:]):
            if observed.setdefault(digest, label) != label:
                conflicts.add(digest)
        pools[partition] = hashes
    seen, eligible = set(), []
    for index, digest in enumerate(pools["test"]):
        if digest not in conflicts and digest not in seen:
            seen.add(digest)
            eligible.append(index)
    random.Random(manifest["split_seed"] + 1).shuffle(eligible)
    result = [f"mnist:test:{index}:{pools['test'][index]}"
              for index in eligible[:manifest["splits"]["test"]["count"]]]
    if sha("\n".join(result).encode()) != manifest["splits"]["test"]["identity_sha256"]:
        raise ValueError("Historical test split order cannot be reproduced")
    return result


def export_fixture(source, destination, *, cache, expected_rows_sha256, expected_summary=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Export must not modify the original evidence tree")
    raw_status = checked_read(source, "status.json")
    status = json.loads(raw_status)
    if status.get("state") != "completed":
        raise ValueError("Source run is not completed")
    originals = {"status.json": raw_status}
    for name in ("protocol.json", "summary.json", "rows.jsonl"):
        originals[name] = checked_read(source, name)
    if sha(originals["rows.jsonl"]) != expected_rows_sha256:
        raise ValueError("Rows differ from the independently supplied completed-run pin")
    protocol = json.loads(originals["protocol.json"])
    summary = json.loads(originals["summary.json"])
    protocol_json, summary_json = canonical(protocol), canonical(summary)
    protocol_sha, summary_sha = sha(protocol_json.encode()), sha(summary_json.encode())
    if (status["summary_sha256"] != summary_sha
            or expected_summary is not None and expected_summary != summary_sha
            or summary["protocol_sha256"] != protocol_sha):
        raise ValueError("Completed status/summary/protocol identity mismatch")
    if protocol["hard_output_modalities"] != ["text", "image"]:
        raise ValueError("Required real output profile changed")
    # Bind a reproducible public-input recipe, not either policy's learned latent.
    # Archive exact historical generator source and verify the original archives.
    cache = Path(cache).resolve()
    source_files = protocol["dataset_manifest"]["source_files"]
    cache_pins = {entry["name"]: entry["sha256"] for entry in source_files}
    cache_bytes = {name: checked_read(cache, name, expected) for name, expected in cache_pins.items()}
    recipe_sources = []
    for name in ("data.py", "run.py"):
        relative = f"experiments/multimodal_output_portfolio/v6/{name}"
        raw = subprocess.check_output(["git", "show", f"{protocol['source']['git_commit']}:{relative}"],
                                      cwd=Path(__file__).parents[3])
        if sha(raw) != protocol["source"]["files"][relative]:
            raise ValueError("Historical public-input generator source differs")
        recipe_sources.append({"path": relative, "sha256": sha(raw), "text": raw.decode("utf-8")})
    input_recipe_json = canonical({
        "schema": "hepta.ndu-v6.reproducible-public-input.v1",
        "source_commit": protocol["source"]["git_commit"],
        "source_bundle_sha256": protocol["source"]["bundle_sha256"],
        "generator_sources": {entry["path"]: entry["sha256"] for entry in recipe_sources},
        "dataset_manifest": protocol["dataset_manifest"],
        "runtime_environment": summary["environment"],
        "entrypoint": "run.case_batch(corpus, 'future', case.index, case.corruption).observation",
        "source_split": "test", "batch_size": 1, "pair_offset": "case.index",
        "observation_rng_seed": "424242 + case.index",
        "generation_noise_seed": "training_seed * 10000 + case.index",
        "semantics": "Observation only: pixels, mask, public command/hint tokens; Target is excluded",
    })
    if TRAINING not in protocol["trainings"] or not {BASELINE, CANDIDATE} <= set(protocol["policies"]):
        raise ValueError("The fixed comparison is absent from the protocol")
    seeds, cases, budget = sorted(protocol["seeds"]), protocol["cases"]["future"], max(protocol["budgets"])
    cases = sorted(cases, key=lambda case: case["case_id"])
    original_ids = test_source_ids(cache_bytes, protocol["dataset_manifest"])
    for case in cases:
        offset = 2 * case["index"]
        if case["source_ids"] != original_ids[offset:offset + 2]:
            raise ValueError("Source-to-case mapping does not match the historical pair offset")
    if not 1 <= len(seeds) <= 32 or not 1 <= len(cases) <= 4096:
        raise ValueError("Paired census exceeds the registered import bounds")
    expected_keys = set(itertools.product(seeds, protocol["trainings"], protocol["budgets"],
                                         protocol["policies"],
                                         ((split, case["case_id"]) for split, entries in protocol["cases"].items()
                                          for case in entries)))
    if len(expected_keys) != status["rows"] or summary["rows"] != status["rows"]:
        raise ValueError("Registered full census does not match completed status")
    selected, seen = [], set()
    for line in originals["rows.jsonl"].splitlines():
        row = json.loads(line)
        key = (row["seed"], row["training"], row["budget"], row["policy"], (row["split"], row["case_id"]))
        if key not in expected_keys or key in seen:
            raise ValueError("Missing, duplicated or foreign original execution")
        seen.add(key)
        receipt = row.pop("receipt_sha256")
        payload = canonical(row)
        if sha(payload.encode()) != receipt:
            raise ValueError("Original execution/observation row receipt changed")
        if (row["training"] == TRAINING and row["split"] == "future" and row["budget"] == budget
                and row["policy"] in (BASELINE, CANDIDATE)):
            selected.append((row, payload, receipt, sha(line)))
    if seen != expected_keys or len(selected) != 2 * len(cases) * len(seeds):
        raise ValueError("Incomplete actual execution census")
    selected.sort(key=lambda item: (item[0]["case_id"], item[0]["seed"], item[0]["policy"] == CANDIDATE))
    source_pins = {name: sha(raw) for name, raw in originals.items()}
    for name in ("audit-observer.pt", "reward-observer.pt"):
        source_pins[name] = sha(checked_read(source, name))
    audit, reward = source_pins["audit-observer.pt"], source_pins["reward-observer.pt"]
    if (audit == reward or summary["observer_binding"]["audit_artifact_sha256"] != audit
            or summary["observer_binding"]["reward_artifact_sha256"] != reward):
        raise ValueError("Audit observer identity or declared separation mismatch")
    versions = []
    for seed in seeds:
        label = f"seed-{seed}-{TRAINING}"
        snapshot, forecast = f"{label}.pt", f"{label}-forecast.pt"
        for name in (snapshot, forecast):
            source_pins[name] = sha(checked_read(source, name))
        expected = {"snapshot_file_sha256": source_pins[snapshot], "forecast_file_sha256": source_pins[forecast]}
        if summary["checkpoint_files"][label] != expected:
            raise ValueError("Whole model/forecast files differ from completed identities")
        versions.append({"seed": seed, **expected})
    by_case, by_seed = {c["case_id"]: c for c in cases}, {v["seed"]: v for v in versions}
    weights, records = protocol["metric"]["weights"], []
    for row, payload, receipt, line_digest in selected:
        case, version, metrics = by_case[row["case_id"]], by_seed[row["seed"]], row["metrics"]
        if (row["source_ids"] != case["source_ids"] or row["corruption"] != case["corruption"]
                or row["observer_sha256"] != audit or row["reward_observer_sha256"] != reward
                or any(row[key] != version[key] for key in ("snapshot_file_sha256", "forecast_file_sha256"))):
            raise ValueError("A paired row mixes context/model/observer identities")
        loss = sum(weights[key] * metrics[key] for key in weights)
        if (any(not math.isfinite(metrics[key]) or not 0 <= metrics[key] <= 1 for key in weights)
                or abs(loss - metrics["joint_loss"]) > 1e-12
                or abs(1 - 2 * loss - metrics["utility"]) > 1e-12):
            raise ValueError("The frozen observation metric arithmetic changed")
        for modality in ("text", "image"):
            relative = row["output_paths"][modality]
            source_pins[relative] = sha(checked_read(source, relative, row["output_hashes"][modality]))
        if row["joint_output_contract"]["required_mask"] != 3:
            raise ValueError("Original joint-output requirement changed")
        records.append({"row_payload_json": payload, "row_receipt_sha256": receipt,
                        "source_row_sha256": line_digest, "loss_q32": loss_q32(metrics["joint_loss"])})
    # Both arms start from the same immutable model/public input/noise realization.
    # Their subsequent actions and outputs can differ and are never equated.
    for left, right in zip(selected[::2], selected[1::2]):
        for key in ("case_id", "seed", "source_ids", "corruption", "snapshot_sha256",
                    "forecast_sha256", "initial_content_plan"):
            if left[0][key] != right[0][key]:
                raise ValueError("Pair does not share its initial input/configuration")
    result = {
        "schema": SCHEMA, "authority": "deny_all", "source_usage": SCOPE,
        "source_root": str(source), "source_pins": source_pins,
        "expected_rows_sha256": expected_rows_sha256,
        "protocol_json": protocol_json, "summary_json": summary_json,
        "metric_json": canonical(protocol["metric"]),
        "cache_root": str(cache), "cache_pins": cache_pins,
        "recipe_sources": recipe_sources, "input_recipe_json": input_recipe_json,
        "selection": {"training": TRAINING, "split": "future", "budget": budget,
                      "baseline": BASELINE, "candidate": CANDIDATE},
        "cases": cases, "versions": versions, "records": records,
        "exporter_sha256": sha(Path(__file__).read_bytes()),
        "helper_sha256": sha(Path(__file__).with_name("terminal_fixture.py").read_bytes()),
        "observation_witness": "Posthoc digest of the original combined row receipt and Audit-B artifact; not a separately signed original observation or re-scoring",
        "estimand": "candidate-minus-baseline; seeds averaged within each original source pair; conditional frozen-model scope; no training-seed or tail coverage",
        "family_alpha_ppm": 50000, "simultaneous_comparisons": 64,
    }
    for name, expected in source_pins.items():
        checked_read(source, name, expected)
    for name, expected in cache_pins.items():
        checked_read(cache, name, expected)
    raw = (canonical(result) + "\n").encode()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Paired fixture exceeds the bounded 8 MiB profile")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(raw)
    return {"path": str(destination), "sha256": sha(raw), "rows": len(records),
            "source_cases": len(cases), "fixed_seeds": len(seeds), "source_files_verified": len(source_pins),
            "source_summary_sha256": summary_sha, "authority": "deny_all"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--expected-summary")
    parser.add_argument("--expected-rows-sha256", required=True)
    args = parser.parse_args()
    print(canonical(export_fixture(args.source, args.destination, cache=args.cache,
                                   expected_rows_sha256=args.expected_rows_sha256,
                                   expected_summary=args.expected_summary)))
