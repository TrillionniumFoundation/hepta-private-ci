"""Read-only aggregation audit of owner #3039's existing synthetic pilot."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
import tarfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ARCHIVE_SHA = "d85dbf45d5d64437651c4ba53b32a000c82ebe78d45ee6e1dd463785bfbafab4"
OWNER_SHA = "9da3c2b98bf427c5812cdc332d4adda1fc23bac6"
PHASE = "local-preflight-v1_1"


def tail_mean(values):
    ordered = sorted(values, reverse=True)
    mass = len(ordered) * 0.1
    whole = int(math.floor(mass))
    total = math.fsum(ordered[:whole])
    if whole < len(ordered):
        total += (mass - whole) * ordered[whole]
    return total / mass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    raw = args.archive.read_bytes()
    if len(raw) != 22415728 or hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA:
        raise ValueError("owner archive bytes differ from published manifest")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        if len(members) != len(archive.getmembers()):
            raise ValueError("duplicate archive member")

        def read(name):
            member = members[name]
            if not member.isfile() or member.size > 16 * 1024 * 1024:
                raise ValueError("bounded ordinary evidence member required")
            return archive.extractfile(member).read()

        def document(name):
            return json.loads(read(name))

        manifest = document(f"{PHASE}/evidence-manifest.json")
        verified = {}
        for name, expected in manifest.items():
            actual = hashlib.sha256(read(f"{PHASE}/{name}")).hexdigest()
            if actual != expected:
                raise ValueError(f"owner evidence member drift: {name}")
            verified[name] = actual
        summary = document(f"{PHASE}/summary.json")
        protocol = document(f"{PHASE}/protocol.json")
        completion = document(f"{PHASE}/completion.json")
        runtime = document(f"{PHASE}/runtime-start.json")
        groups = defaultdict(list)
        identities = set()
        worlds = set()
        primary = defaultdict(dict)
        count = 0
        with gzip.GzipFile(
            fileobj=io.BytesIO(read(f"{PHASE}/per_world.csv.gz"))
        ) as compressed:
            for row in csv.DictReader(io.TextIOWrapper(compressed)):
                key = (
                    int(row["seed"]),
                    row["scenario"],
                    int(row["budget"]),
                    row["arm"],
                )
                identity = (*key, row["world_id"])
                if identity in identities:
                    raise ValueError("duplicate policy/world observation")
                identities.add(identity)
                worlds.add(row["world_id"])
                columns = [
                    float(row[name])
                    for name in (
                        "loss",
                        "quality",
                        "linear_macs",
                        "resolved_correct",
                        "omission",
                    )
                ]
                if not all(math.isfinite(value) for value in columns):
                    raise ValueError("nonfinite pilot observation")
                groups[key].append(columns)
                if key[1:3] == ("test_iid", 4):
                    primary[(key[0], key[3])][row["world_id"]] = columns[0]
                count += 1
        stored = {
            (row["seed"], row["scenario"], row["budget"], row["arm"]): row
            for row in summary["rows"]
        }
        if set(groups) != set(stored) or len(stored) != len(summary["rows"]):
            raise ValueError("summary group census drift")
        maximum_error = 0.0
        recomputed = {}
        for key, values in groups.items():
            n = len(values)
            actual = {
                "n": n,
                "cvar90": tail_mean([row[0] for row in values]),
                "mean_loss": math.fsum(row[0] for row in values) / n,
                "mean_quality": math.fsum(row[1] for row in values) / n,
                "mean_linear_macs": math.fsum(row[2] for row in values) / n,
                "mean_resolved_correct_fraction": math.fsum(row[3] for row in values)
                / n,
                "mean_omission": math.fsum(row[4] for row in values) / n,
            }
            for name, value in actual.items():
                error = abs(value - stored[key][name])
                maximum_error = max(maximum_error, error)
                if error > 1e-9:
                    raise ValueError(f"summary mismatch: {key} {name} {error}")
            recomputed[key] = actual
        seeds = tuple(protocol["seeds"])
        candidate, baseline = "ndu_recursive_dp", "validation_selected_fixed_portfolio"
        paired = []
        for seed in seeds:
            left, right = primary[(seed, candidate)], primary[(seed, baseline)]
            if set(left) != set(right) or len(left) != 1536:
                raise ValueError("primary pairing census drift")
            ids = sorted(left)
            paired.append(
                (np.array([left[i] for i in ids]), np.array([right[i] for i in ids]))
            )
        differences = [tail_mean(left) - tail_mean(right) for left, right in paired]
        estimate = math.fsum(differences) / len(seeds)
        rng = np.random.default_rng(7891)
        replicates = []
        for _ in range(1000):
            chosen_seeds = rng.integers(len(seeds), size=len(seeds))
            chosen_worlds = rng.integers(1536, size=(len(seeds), 1536))
            contrasts = []
            for seed_index, world_indices in zip(
                chosen_seeds, chosen_worlds, strict=True
            ):
                left, right = paired[seed_index]
                contrasts.append(
                    tail_mean(left[world_indices]) - tail_mean(right[world_indices])
                )
            replicates.append(math.fsum(contrasts) / len(seeds))
        lower, upper = np.quantile(replicates, [0.025, 0.975])
        recorded = summary["primary_budget4_iid_contrasts"][baseline]["cvar90"]
        actual_primary = {
            "estimate": estimate,
            "ci_low": float(lower),
            "ci_high": float(upper),
        }
        for name, value in actual_primary.items():
            if abs(value - recorded[name]) > 1e-12:
                raise ValueError(f"bootstrap mismatch: {name}")
        prior_worlds = set()
        with gzip.GzipFile(
            fileobj=io.BytesIO(read("local-preflight-v1/per_world.csv.gz"))
        ) as compressed:
            for row in csv.DictReader(io.TextIOWrapper(compressed)):
                prior_worlds.add(row["world_id"])
        overlap = worlds & prior_worlds
        if overlap:
            raise ValueError("v1/v1.1 world IDs overlap")
        training = []
        for seed in seeds:
            name = f"seed-{seed}/training.json"
            before = document(f"local-preflight-v1/{name}")
            after = document(f"{PHASE}/{name}")
            fields = (
                "initial_weight_sha256",
                "final_weight_sha256",
                "data_generation",
                "parameter_counts",
            )
            if any(before[field] != after[field] for field in fields):
                raise ValueError("training identity differs across rounds")
            training.append({"seed": seed, **{field: after[field] for field in fields}})
        if "torch" in sys.modules:
            raise ValueError("aggregate audit unexpectedly imported Torch")
        result = {
            "schema": "hepta.owner3039.external-aggregate-audit.v1",
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "owner_pr": 3039,
            "owner_head": OWNER_SHA,
            "archive_path_read_only": str(args.archive),
            "archive_bytes": len(raw),
            "archive_sha256": ARCHIVE_SHA,
            "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "verified_evidence_members": verified,
            "policy_world_rows": count,
            "summary_groups": len(groups),
            "independently_recomputed_fields": list(next(iter(recomputed.values()))),
            "maximum_summary_absolute_error": maximum_error,
            "primary_cvar90": actual_primary,
            "primary_seed_differences": differences,
            "primary_bootstrap_replicates": 1000,
            "absolute_0_020_reduction_passed": bool(estimate <= -0.02),
            "interval_below_zero_passed": bool(upper < 0),
            "stored_primary_claim_passed": summary["primary_claim_passed"],
            "world_count_v1": len(prior_worlds),
            "world_count_v1_1": len(worlds),
            "world_id_overlap": len(overlap),
            "same_three_training_model_identities": training,
            "original_runtime": runtime,
            "original_completion": completion,
            "original_protocol_wall_seconds": summary["wall_seconds"],
            "model_checkpoint_or_forward_replay_performed_by_this_audit": False,
            "new_model_calls": 0,
            "torch_imported": False,
            "scope": (
                "Aggregation and pairing review of the existing synthetic "
                "660488-parameter pilot. Does not close licensed teacher, native "
                "150M/300M Student, Memory112, independent natural-semantic "
                "holdout, physical GPU/energy, or dedicated host qualification."
            ),
            "qualification": "NO_GO",
        }
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    print(
        json.dumps(
            {
                "rows": count,
                "groups": len(groups),
                "primary": actual_primary,
                "report_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "new_model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
