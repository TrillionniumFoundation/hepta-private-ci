"""Enumerate a finite real neural continuation family on offline source roles."""

from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path
import time

import torch

from ..v6.data import Observation, Target
from .data import VIEWS, make_batch
from .forecast import CONTINUATIONS, public_summary, state_features
from .sources import canonical, digest


@dataclass
class EndpointData:
    features: torch.Tensor
    targets: torch.Tensor
    groups: torch.Tensor
    rows: list[dict]
    evidence: dict


def collect_endpoints(snapshot, corpus, role, labeler, pairs, directory, *, offset=0,
                      public_seed=424242, noise_seed=73421):
    """Twenty-one endpoints, with all legal suffix labels attached to each state.

    Every source pair stays together across views, initialization and branches.
    Hidden hint correctness is diagnostic metadata, never a feature column.
    """
    if role not in {"forecast_fit", "forecast_calibration", "development"}:
        raise ValueError("Forecast development cannot open a formal or Neuron role")
    if snapshot.initial_plan_cost != 2 or pairs < 2:
        raise ValueError("Registered forecast requires controlled two-step initialization")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    snapshot.verify_integrity()
    labeler.verify_integrity()
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    feature_parts, target_parts, groups, rows = [], [], [], []
    label_digest = hashlib.sha256()
    source_pairs = None
    event_path = directory / "actual-endpoints.jsonl.gz"
    with gzip.open(event_path, "wt", encoding="utf-8", newline="\n") as stream:
        for view in VIEWS:
            batch = make_batch(corpus, role, pairs, public_seed, view=view, offset=offset)
            if source_pairs is None:
                source_pairs = batch.source_ids
            elif source_pairs != batch.source_ids:
                raise ValueError("View source groups changed")
            for content_control in (True, False):
                initialization = "full" if content_control else "allocation"
                plans = tuple(plan for plan in CONTINUATIONS
                              if content_control or all(action in {"refine_image", "refine_text"} for action in plan))
                for start in range(0, pairs, 64):
                    stop = min(start + 64, pairs)
                    observation = Observation(*(value[start:stop] for value in
                                                (batch.observation.pixels, batch.observation.mask,
                                                 batch.observation.text_tokens)))
                    target = Target(*(value[start:stop] for value in
                                      (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                    summary = public_summary(observation)
                    initial = snapshot.encode(observation, noise_seed + start, content_control=content_control)
                    states, utilities, observations = {(): initial}, {}, {}
                    for plan in plans:
                        if plan:
                            states[plan] = snapshot.step(states[plan[:-1]], plan[-1])
                        labels = labeler.label(snapshot, states[plan], target)
                        observations[plan] = labels
                        utilities[plan] = torch.tensor([item["utility"] for item in labels], dtype=torch.float64)
                        for i, observed in enumerate(labels, start):
                            event = {"pair": offset + i, "view": view, "initialization": initialization,
                                     "continuation": plan, "utility": observed["utility"],
                                     "raw_sha256": observed["raw_sha256"], "observed": observed}
                            raw = canonical(event) + b"\n"
                            stream.write(raw.decode())
                            label_digest.update(raw)
                    for prefix in plans:
                        targets = torch.full((stop - start, len(CONTINUATIONS)), float("nan"), dtype=torch.float64)
                        for index, suffix in enumerate(CONTINUATIONS):
                            endpoint = prefix + suffix
                            if endpoint in utilities:
                                targets[:, index] = utilities[endpoint]
                        feature_parts.append(state_features(states[prefix], summary).detach().clone())
                        target_parts.append(targets)
                        groups.append(torch.arange(start, stop, dtype=torch.long))
                        rows.extend({"pair": offset + i, "view": view, "initialization": initialization,
                                     "prefix": prefix, "step_count": 2 + len(prefix),
                                     "information_sufficient": batch.information_sufficient[i],
                                     "untrusted_hint_correct": batch.untrusted_hint_correct[i],
                                     "initial_plan_index": initial.plan_indices[i - start],
                                     "actual_observation": observations[prefix][i - start]}
                                    for i in range(start, stop))
    features, targets, group_ids = torch.cat(feature_parts), torch.cat(target_parts), torch.cat(groups)
    evidence = {
        "schema": "hepta.ndu-v7.forecast-endpoint-corpus.v1", "role": role,
        "source_manifest_sha256": corpus.manifest["manifest_sha256"], "source_pairs": source_pairs,
        "source_pair_sha256": digest(source_pairs), "pairs": pairs, "offset": offset,
        "public_seed": public_seed, "noise_seed": noise_seed, "views": VIEWS,
        "snapshot_sha256": snapshot.fingerprint, "metric_contract_sha256": labeler.contract_sha256,
        "endpoint_rows": len(rows), "labeled_state_suffixes": int(torch.isfinite(targets).sum()),
        "actual_endpoints_sha256": label_digest.hexdigest(),
        "actual_endpoints_file": event_path.name,
        "actual_endpoints_file_sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
        "features_sha256": hashlib.sha256(features.numpy().tobytes()).hexdigest(),
        "targets_sha256": hashlib.sha256(targets.numpy().tobytes()).hexdigest(),
        "groups_sha256": hashlib.sha256(group_ids.numpy().tobytes()).hexdigest(),
        "costs": {"encoder_examples": pairs * len(VIEWS) * 2,
                  "initial_action_examples": pairs * len(VIEWS) * 2 * 2,
                  "continuation_action_examples": pairs * len(VIEWS) * (20 + 6),
                  "decode_score_examples": len(rows),
                  "public_summary_example_calls": pairs * len(VIEWS) * 2,
                  "wall_ns": time.perf_counter_ns() - start_wall,
                  "cpu_ns": time.process_time_ns() - start_cpu},
        "candidate_family": "full all prefixes depth<=2; allocation legal modality prefixes only",
        "formal_holdout_access": False,
    }
    snapshot.verify_integrity()
    labeler.verify_integrity()
    (directory / "manifest.json").write_bytes(canonical(evidence) + b"\n")
    return EndpointData(features, targets, group_ids, rows, evidence)


def collect_scenarios(snapshot, corpus, role, labeler, pairs, directory, *, scenarios=1):
    """Keep common latent-noise scenarios within each independent source group."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if scenarios not in {1, 4}:
        raise ValueError("Only the preregistered single/four-noise profiles are supported")
    parts = []
    for slot in range(scenarios):
        part = collect_endpoints(snapshot, corpus, role, labeler, pairs, directory / f"scenario-{slot}",
                                  noise_seed=73421 + slot * 1000003)
        for row in part.rows:
            row["noise_slot"] = slot
        parts.append(part)
    features = torch.cat([part.features for part in parts])
    targets = torch.cat([part.targets for part in parts])
    groups = torch.cat([part.groups for part in parts])
    rows = [row for part in parts for row in part.rows]
    evidence = dict(parts[0].evidence)
    evidence.update({"scenarios": scenarios, "endpoint_rows": len(rows),
                     "labeled_state_suffixes": int(torch.isfinite(targets).sum()),
                     "scenario_evidence": [part.evidence for part in parts],
                     "features_sha256": hashlib.sha256(features.numpy().tobytes()).hexdigest(),
                     "targets_sha256": hashlib.sha256(targets.numpy().tobytes()).hexdigest(),
                     "groups_sha256": hashlib.sha256(groups.numpy().tobytes()).hexdigest(),
                     "actual_endpoints_sha256": digest([part.evidence["actual_endpoints_sha256"] for part in parts]),
                     "costs": {key: sum(part.evidence["costs"][key] for part in parts)
                               for key in parts[0].evidence["costs"]}})
    (directory / "manifest.json").write_bytes(canonical(evidence) + b"\n")
    return EndpointData(features, targets, groups, rows, evidence)
