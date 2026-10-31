"""Actual finite H=2 trees for offline fitting and diagnostic comparison.

Only the root and four immediate children expose public features. All 21 nodes
retain actual media and offline labels; those labels never enter generation.
"""

from collections import Counter
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import traceback

import torch

from ..v6.data import Observation, Target
from ..v6.neural import parameter_hash
from ..v6.observer import METRIC, METRIC_DIGEST, observe_tensors
from ..v7.data import VIEWS, make_batch
from ..v7.snapshot import Snapshot
from ..v7.sources import canonical, digest
from .base_recovery import AREA, ROOT, file_sha, ids_sha, write_json
from .emission import output_digests
from .media import RawMediaArchive, reopen_archive_records
from .runtime import (ACTIONS, FEATURE_DIM, initialize, public_digest,
                      public_features, public_frame, transition)


PLANS = ((),) + tuple((action,) for action in ACTIONS[1:]) + tuple(
    (first, second) for first in ACTIONS[1:] for second in ACTIONS[1:])
METRICS = ("utility", "joint_loss", "joint_fact_correct", "required_output_complete", *METRIC["weights"])


def stable_seed(*parts):
    """Shared canonical-JSON stream identity, excluding arm/checkpoint identity."""
    return int.from_bytes(hashlib.sha256(canonical(parts)).digest()[:8], "big") % (2**63)


@contextmanager
def _phase(totals, name):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        yield
    finally:
        item = totals.setdefault(name, {"calls": 0, "wall_ns": 0, "cpu_ns": 0})
        item["calls"] += 1
        item["wall_ns"] += time.perf_counter_ns() - wall
        item["cpu_ns"] += time.process_time_ns() - cpu


def _source_pins():
    paths = [AREA / folder / (name + ".py") for folder, names in (
        ("v6", ("data", "neural", "observer")),
        ("v7", ("data", "model", "snapshot", "sources")),
        ("abc_recovery", ("base_recovery", "emission", "media", "runtime", "trees", "trees_tests"))) for name in names]
    return {str(path.relative_to(ROOT)): file_sha(path) for path in paths}


def _source_identity(corpus, role, start, count):
    pool = corpus.splits[role]
    left, right = 2 * start, 2 * (start + count)
    selected = tuple(pool.ids[left:right])
    if len(selected) != 2 * count or len(set(selected)) != 2 * count:
        raise ValueError("Source pair range is incomplete or repeats source identities")
    images, labels = pool.images[left:right], pool.labels[left:right]
    return {"manifest_record_sha256": digest(corpus.manifest),
            "manifest_declared_sha256": corpus.manifest.get("manifest_sha256"),
            "source_ids_sha256": ids_sha(selected),
            "original_pixels_sha256": hashlib.sha256(images.contiguous().numpy().tobytes()).hexdigest(),
            "original_labels_sha256": hashlib.sha256(labels.contiguous().numpy().tobytes()).hexdigest()}


@torch.inference_mode()
def collect_tree(snapshot, corpus, observers, outdir, *, role, pair_start,
                 pair_count, scenarios, training_seed, interventions=None):
    """Collect every bounded plan from immutable parents and retain its evidence.

    Row order is view/case/scenario; PLANS indexes all metric columns. Features
    contain only the five current-public states at remaining horizons 2,1,1,1,1.
    A Q1 root counterfactual must copy features[:,0] and set its final column to
    .5; the stored root remains the factual H2 state with final column 1.0.
    """
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    phases, work, feature_work = {}, Counter(), Counter()
    try:
        with _phase(phases, "registration_and_integrity"):
            if (type(snapshot) is not Snapshot or set(observers) not in ({"primary"}, {"primary", "secondary"})
                    or role not in {"train", "development", "forecast_fit", "forecast_calibration"}
                    or any(type(value) is not int for value in (pair_start, pair_count, scenarios, training_seed))
                    or min(pair_count, scenarios) < 1 or pair_start < 0 or not 0 <= training_seed < 2**63):
                raise ValueError("Invalid bounded-tree inputs")
            interventions = dict(interventions or {})
            if interventions.get("content_mode", "full") != "full":
                raise ValueError("The complete 21-node tree requires content_mode=full; mask allocation policies separately")
            if set(interventions) - {"content_mode", "shared_mode", "context_mode"}:
                raise ValueError("Unknown tree intervention")
            snapshot.verify_integrity()
            model = snapshot._model
            if any(observer.training for observer in observers.values()):
                raise ValueError("Observers must be frozen in eval mode")
            pins = _source_pins()
            source_identity = _source_identity(corpus, role, pair_start, pair_count)
            observer_hashes = {name: parameter_hash(observer) for name, observer in observers.items()}
            observation_seed = stable_seed("observation", role, pair_start)
            registration = {"schema": "hepta.ndu-abc.actual-tree-registration.v1",
                            "role": role, "pair_start": pair_start, "pair_count": pair_count,
                            "scenarios_per_source": scenarios, "training_seed": training_seed,
                            "source_identity": source_identity, "source_sha256": pins,
                            "snapshot_sha256": snapshot.fingerprint, "model_parameter_sha256": snapshot.parameter_sha256,
                            "observer_parameter_sha256": observer_hashes, "metric_sha256": METRIC_DIGEST,
                            "plans": PLANS, "views": VIEWS, "interventions": interventions,
                            "observation_seed": observation_seed, "generation_stream": "stable_seed(generation,role,pair_start,training_seed,view,path)",
                            "arm_identity_in_rng": False, "features_expose_grandchildren": False,
                            "secondary_labels_for_evaluation_only": True,
                            "new_context_intervention_is_matched_architecture_training": False}
            write_json(outdir / "registration.json", registration)
        data = {"features": [], "root_pixels": [], "root_tokens": [], "root_emission_sha256": [],
                "metrics": {name: {metric: [] for metric in METRICS} for name in observers},
                "cases": [], "views": [], "scenarios": [], "source_ids": [], "plans": list(PLANS),
                "records_file": "raw-rows.jsonl.gz", "role": role, "pair_start": pair_start, "pair_count": pair_count,
                "scenarios_per_source": scenarios, "training_seed": training_seed,
                "source_manifest_sha256": corpus.manifest.get("manifest_sha256"),
                "snapshot_sha256": snapshot.fingerprint, "observer_parameter_sha256": observer_hashes}
        archive_hashes, ledger_hashes = {}, {}
        total_rows = pair_count * scenarios
        with (outdir / data["records_file"]).open("xb") as raw_stream, gzip.GzipFile(
                filename="", mode="wb", fileobj=raw_stream, mtime=0) as compressed, io.TextIOWrapper(
                    compressed, encoding="utf-8") as raw_rows:
            for view_index, view in enumerate(VIEWS):
                with _phase(phases, "observations"):
                    batch = make_batch(corpus, role, pair_count, observation_seed, view=view, offset=pair_start)
                    observation = Observation(*(value.repeat_interleave(scenarios, dim=0) for value in
                                                (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
                    target = Target(*(value.repeat_interleave(scenarios, dim=0) for value in
                                      (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                states, features, records, node_tokens, output_hashes = {}, [], [], [], []
                archive_name = f"media/{view}.zip"
                with RawMediaArchive(outdir / archive_name) as archive:
                    for plan_index, plan in enumerate(PLANS):
                        seed = stable_seed("generation", role, pair_start, training_seed, view, plan)
                        generator = torch.Generator().manual_seed(seed)
                        rng_before = hashlib.sha256(generator.get_state().numpy().tobytes()).hexdigest()
                        with _phase(phases, "generation"):
                            if not plan:
                                run = initialize(model, observation, generator=generator, **interventions)
                                incremental_start = 0
                            else:
                                parent = states[plan[:-1]]
                                parent_sha = public_digest(public_frame(parent))
                                incremental_start = len(parent.ledger)
                                run = transition(model, parent, plan[-1], generator=generator)
                                if public_digest(public_frame(parent)) != parent_sha:
                                    raise RuntimeError("Counterfactual transition mutated its parent")
                            if len(plan) < 2:
                                states[plan] = run
                            for entry in run.ledger[incremental_start:]:
                                work.update(entry.get("work", {}))
                        if len(plan) < 2:
                            with _phase(phases, "public_features"):
                                features.append(public_features(model, public_frame(run), work=feature_work))
                        with _phase(phases, "raw_media_write_decode"):
                            _, _, media_records = archive.append(run.pixels, run.tokens)
                            records.append(media_records)
                            node_tokens.append(run.tokens.detach().cpu().clone())
                            output_hashes.append(tuple(run.ledger[-1]["output_sha256"]))
                        if not plan:
                            data["root_pixels"].append(run.pixels.to(torch.uint8).cpu())
                            data["root_tokens"].append(run.tokens.detach().cpu().clone())
                            data["root_emission_sha256"].extend(output_hashes[-1])
                        with _phase(phases, "ledger_write"):
                            ledger_name = f"ledgers/{view}/{plan_index:02d}.jsonl"
                            path = outdir / ledger_name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            header = {"schema": "hepta.ndu-abc.tree-node-ledger.v1", "view": view,
                                      "plan_index": plan_index, "path": plan, "generation_seed": seed,
                                      "owner_rng_before_sha256": rng_before,
                                      "owner_rng_after_sha256": hashlib.sha256(generator.get_state().numpy().tobytes()).hexdigest(),
                                      "incremental_record_start": incremental_start,
                                      "cumulative_ledger_shared_ancestors_must_not_be_resummed": True,
                                      "new_emission_on_this_edge": not plan or plan[-1] != "refine_semantic"}
                            with path.open("x") as stream:
                                for entry in (header, *run.ledger):
                                    stream.write(json.dumps(entry, sort_keys=True, allow_nan=False) + "\n")
                            ledger_hashes[ledger_name] = file_sha(path)
                view_metrics = {name: {metric: torch.empty((total_rows, len(PLANS)), dtype=torch.float32)
                                      for metric in METRICS} for name in observers}
                scores = []
                for plan_index, plan in enumerate(PLANS):
                    with _phase(phases, "closed_archive_reopen"):
                        pixels, captions = reopen_archive_records(outdir / archive_name, records[plan_index])
                        if output_digests(pixels, node_tokens[plan_index]) != output_hashes[plan_index]:
                            raise ValueError("Reopened media no longer binds the actual token/pixel path")
                    per_observer = {}
                    for name, observer in observers.items():
                        with _phase(phases, "observer_" + name):
                            observed = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
                        for i, score in enumerate(observed):
                            score["joint_fact_correct"] = bool(score["caption_valid"] and all(score[key] == 0 for key in
                                ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
                            score["required_output_complete"] = records[plan_index][i]["required_output_complete"]
                            for metric in METRICS:
                                view_metrics[name][metric][i, plan_index] = score[metric]
                        per_observer[name] = observed
                    scores.append(per_observer)
                with _phase(phases, "raw_rows_write"):
                    for i in range(total_rows):
                        case_local, scenario = divmod(i, scenarios)
                        for plan_index, plan in enumerate(PLANS):
                            token_path = node_tokens[plan_index][i].tolist()
                            row = {"row_index": view_index * total_rows + i, "role": role,
                                   "case": pair_start + case_local, "view": view, "scenario": scenario,
                                   "source_ids": batch.source_ids[case_local], "plan_index": plan_index, "path": plan,
                                   "view_archive": archive_name, **records[plan_index][i],
                                   "token_path": token_path, "token_path_sha256": digest(token_path),
                                   "output_sha256": output_hashes[plan_index][i],
                                   "new_emission_on_this_edge": not plan or plan[-1] != "refine_semantic",
                                   "information_sufficient": batch.information_sufficient[case_local],
                                   "untrusted_hint_correct": batch.untrusted_hint_correct[case_local],
                                   "observer_scores": {name: scores[plan_index][name][i] for name in observers}}
                            raw_rows.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                data["features"].append(torch.stack(features, dim=1))
                for name in observers:
                    for metric in METRICS:
                        data["metrics"][name][metric].append(view_metrics[name][metric])
                for case_local in range(pair_count):
                    for scenario in range(scenarios):
                        data["cases"].append(pair_start + case_local)
                        data["views"].append(view)
                        data["scenarios"].append(scenario)
                        data["source_ids"].append(batch.source_ids[case_local])
                archive_hashes[archive_name] = file_sha(outdir / archive_name)
        with _phase(phases, "data_write_and_integrity"):
            for name in ("features", "root_pixels", "root_tokens"):
                data[name] = torch.cat(data[name], dim=0)
            for name in observers:
                for metric in METRICS:
                    data["metrics"][name][metric] = torch.cat(data["metrics"][name][metric], dim=0)
            expected_budget = torch.tensor([1., .5, .5, .5, .5]).expand(len(data["cases"]), -1)
            if data["features"].shape != (8 * total_rows, 5, FEATURE_DIM) or not torch.equal(data["features"][:, :, -1], expected_budget):
                raise ValueError("Only root H2 and immediate-child H1 public features may enter the dataset")
            if output_digests(data["root_pixels"].float(), data["root_tokens"]) != tuple(data["root_emission_sha256"]):
                raise ValueError("Stored root public draft identities differ")
            snapshot.verify_integrity()
            if (source_identity != _source_identity(corpus, role, pair_start, pair_count) or pins != _source_pins()
                    or observer_hashes != {name: parameter_hash(observer) for name, observer in observers.items()}):
                raise RuntimeError("Source, observer or code identities changed during tree collection")
            with (outdir / "data.pt").open("xb") as stream:
                torch.save(data, stream)
            data_sha = file_sha(outdir / "data.pt")
        summary = {"schema": "hepta.ndu-abc.actual-tree-summary.v1", "status": "completed",
                   "registration_sha256": file_sha(outdir / "registration.json"), "data_file_sha256": data_sha,
                   "records_file_sha256": file_sha(outdir / data["records_file"]),
                   "source_identity": source_identity, "source_sha256": pins, "snapshot_sha256": snapshot.fingerprint,
                   "model_parameter_sha256": snapshot.parameter_sha256, "observer_parameter_sha256": observer_hashes,
                   "identities_unchanged": True, "archive_sha256": archive_hashes, "ledger_sha256": ledger_hashes,
                   "rows": len(data["cases"]), "node_rows": len(data["cases"]) * len(PLANS),
                   "independent_source_pairs": pair_count, "scenarios_per_source": scenarios,
                   "phase_times": phases, "actual_incremental_generation_work": dict(work), "feature_work": dict(feature_work),
                   "features_expose_grandchildren": False, "root_Q1_counterfactual": "copy root features; replace final budget value with .5",
                   "metrics_include_action_penalty": False, "physical_completion_is_factual_correctness": False,
                   "secondary_labels_for_evaluation_only": True, "wall_ns": time.perf_counter_ns() - wall,
                   "cpu_ns": time.process_time_ns() - cpu,
                   "timer_scope": "collect_tree entry through data, raw media, ledgers, scoring and final integrity checks; outer runner measures process and final-report overhead"}
        write_json(outdir / "summary.json", summary)
        return data
    except BaseException as error:
        write_json(outdir / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                   "phase_times": phases, "actual_incremental_generation_work": dict(work),
                   "failed_transition_ledger": getattr(error, "ledger", None)})
        raise
