"""Read-only audits of sealed actual media; failures remain explicit reports.

An audit checks saved bytes, task reconstruction and frozen-observer scores. It
does not regenerate outputs, train/select a model, certify neural optimality or
turn repeated source/scenario/policy rows into independent observations.
"""

from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import zipfile

import torch

from ..v6.data import BOS, CAPTION_LENGTH, EOS, PAD, VOCAB, Observation, render_tokens
from ..v6.neural import parameter_hash
from ..v6.observer import METRIC, METRIC_DIGEST, observe_tensors
from ..v7.data import VIEWS, make_batch
from ..v7.model import observation_digest
from ..v7.sources import canonical, digest
from .emission import output_digests
from .media import _read as read_media_record


AREA = Path(__file__).resolve().parents[1]
METRIC_ABSOLUTE_TOLERANCE = 1e-7
TRAINING_ARTIFACTS = {"raw-media.zip", "training-outputs.jsonl.gz", "trajectory-ledger.jsonl.gz",
                      "history.json", "gradient-probes.json", "model.pt", "registration.json"}
SEED_RECIPES = ("seed*1000003 + 20261024 + zero_based_step",
                "seed*1000033 + 20261025 + zero_based_step")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(actual, expected):
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and actual.keys() == expected.keys()
                and all(_same(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, (list, tuple)):
        return (isinstance(actual, (list, tuple)) and len(actual) == len(expected)
                and all(_same(a, e) for a, e in zip(actual, expected)))
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)):
        return (type(actual) in {int, float} and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=0., abs_tol=METRIC_ABSOLUTE_TOLERANCE))
    return actual == expected


class _Audit:
    def __init__(self, directory, kind):
        self.started = (time.perf_counter_ns(), time.process_time_ns())
        self.root = Path(directory).resolve()
        self.counts, self.files = Counter(), {}
        self.phase = "sealed_result_validation"
        self.report = {"schema": "hepta.ndu-abc.raw-evidence-audit.v1", "kind": kind,
                       "directory": str(self.root), "status": "failed", "passed": False,
                       "errors": [], "metric_absolute_tolerance": METRIC_ABSOLUTE_TOLERANCE,
                       "read_only": True, "outputs_regenerated": False,
                       "new_outcomes_used_for_tuning": False,
                       "authenticates_external_outcome_owner": False}

    def file(self, path, expected=None, expected_bytes=None):
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                self.counts["file_bytes_hashed"] += len(block)
        after = path.stat()
        identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == identity,
                f"File changed during hashing: {path.name}")
        value = digest.hexdigest()
        self.counts["file_sha256_checks"] += 1
        require(expected is None or value == expected, f"File hash mismatch: {path.name}")
        require(expected_bytes is None or after.st_size == expected_bytes, f"File size mismatch: {path.name}")
        self.files[str(path)] = {"sha256": value, "bytes": after.st_size, "stat": identity}
        return value

    def json(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def sealed(self):
        require((self.root / "summary.json").is_file(), "No final summary; archive may still be open")
        require(not (self.root / "failure.json").exists(), "Failed invocation cannot be certified completed")
        summary = self.json("summary.json")
        require(summary.get("status") == "completed", "Result is not sealed as completed")
        self.report["summary_file_sha256"] = self.file("summary.json")
        self.report["completion_marker_required_before_archive_open"] = True
        return summary

    def source_pins(self, pins):
        require(bool(pins), "Missing source-code pins")
        for name, expected in pins.items():
            relative = name.removeprefix("experiments/multimodal_output_portfolio/")
            path = Path(relative)
            require(not path.is_absolute() and ".." not in path.parts and len(path.parts) == 2
                    and path.parts[0] in {"v6", "v7", "abc_recovery"} and path.suffix == ".py",
                    "Unrecognized source-code pin path")
            self.file(AREA / path, expected)

    def stable(self):
        self.phase = "final_identity_validation"
        for path, record in tuple(self.files.items()):
            stat = Path(path).stat()
            require((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) == record["stat"],
                    f"File changed during audit: {path}")
        # Rehash the seal and mutable-looking streams, beyond stat-only checks.
        for name in ("summary.json", "registration.json"):
            record = self.files.get(str(self.root / name))
            if record:
                self.file(name, record["sha256"], record["bytes"])


def _run(directory, kind, operation):
    audit = _Audit(directory, kind)
    try:
        operation(audit)
        audit.stable()
        audit.report.update(status="passed", passed=True)
    except Exception as error:
        audit.report["errors"].append({"phase": audit.phase, "type": type(error).__name__, "message": str(error)})
        audit.report["stopped_at_first_failure"] = True
    audit.report.update(counts=dict(audit.counts),
                        verified_files={path: {k: v for k, v in row.items() if k != "stat"}
                                        for path, row in audit.files.items()},
                        wall_ns=time.perf_counter_ns() - audit.started[0],
                        cpu_ns=time.process_time_ns() - audit.started[1])
    return audit.report


def _observer_identity(observer, expected):
    require(not observer.training and not any(p.requires_grad for p in observer.parameters()),
            "Observer must already be frozen and in evaluation mode")
    identity = parameter_hash(observer)
    require(identity == expected, "Frozen observer parameter identity mismatch")
    return identity


def _tokens(values):
    require(isinstance(values, list) and len(values) == CAPTION_LENGTH
            and all(type(item) is int and 0 <= item < len(VOCAB) for item in values)
            and values[0] == BOS, "Invalid actual token path")
    if EOS in values:
        require(all(item == PAD for item in values[values.index(EOS) + 1:]),
                "Token path violates EOS-then-PAD sampling law")
    return values


def _line(stream, label):
    line = stream.readline(1024 * 1024 + 1)
    require(bool(line) and len(line) <= 1024 * 1024, f"Missing or oversized {label}")
    return line, json.loads(line)


def audit_training_arm(directory, corpus_train, primary_observer):
    """Audit one completed arm, one step at a time, returning pass/failure evidence.

    No archive is opened until a completed summary and its artifact hashes are
    verified. A failed report is never a partial pass. Source groups are counted
    separately from scenario rows; no independent sample size is inferred.
    Terminal log-probability values are checked for validity, not recomputed
    from intermediate parameter states that were not retained at every step.
    """
    return _run(directory, "training_arm", lambda audit: _training(audit, corpus_train, primary_observer))


def _training(audit, corpus, observer):
    summary = audit.sealed()
    require(summary.get("schema") == "hepta.ndu-abc.actual-output-training-result.v1", "Wrong training summary schema")
    require(set(summary["artifacts"]) == TRAINING_ARTIFACTS, "Incomplete training artifact census")
    for name, record in summary["artifacts"].items():
        audit.file(name, record["sha256"], record["bytes"])
    registration = audit.json("registration.json")
    require(registration["schema"] == "hepta.ndu-abc.actual-output-training-registration.v1", "Wrong registration schema")
    require(registration["source_roles_read"] == ["train"] and registration["metric_sha256"] == METRIC_DIGEST,
            "Training role or metric changed")
    require(registration["source_manifest_sha256"] == corpus.manifest["manifest_sha256"], "Training source manifest mismatch")
    require((registration["batch_seed_recipe"], registration["generation_seed_recipe"]) == SEED_RECIPES,
            "Unknown registered seed recipe")
    audit.source_pins(registration["source_sha256"])
    identity = _observer_identity(observer, registration["primary_observer_parameter_sha256"])
    audit.counts["observer_parameter_identity_checks"] += 1
    seed, training = registration["seed"], registration["training"]
    steps, batch_size, scenarios = (training[key] for key in
        ("fine_tuning_steps", "fine_tuning_conditions_per_step", "fine_tuning_scenarios_per_condition"))
    require(all(type(value) is int and value > 0 for value in (steps, batch_size, scenarios)) and scenarios >= 2,
            "Invalid expected training census")
    expected_rows = steps * batch_size * scenarios
    require(summary["completed_steps"] == steps and summary["terminal_output_rows"] == expected_rows,
            "Summary training census mismatch")
    for key in ("source_sha256", "source_manifest_sha256", "protocol_canonical_sha256", "warm_snapshot_sha256",
                "actual_output_score_used_in_optimizer", "risk_aversion", "native_auxiliary_weight", "seed"):
        require(summary[key] == registration[key], f"Registration/summary mismatch: {key}")
    require(summary["profile"] == registration["arm"], "Training arm mismatch")
    audit.report.update(seed=seed, arm=registration["arm"], expected_output_rows=expected_rows,
                        condition_occurrences=steps * batch_size, scenarios_per_condition=scenarios,
                        independent_training_seeds=1, claimed_independent_sample_size=None,
                        repeated_rows_are_not_independent_observations=True,
                        terminal_log_probability_recomputed=False)
    checkpoint_steps = sorted({0, steps, *range(training["checkpoint_interval"], steps, training["checkpoint_interval"])})
    require([row["step"] for row in summary["optimizer_checkpoints"]] == checkpoint_steps, "Checkpoint census mismatch")
    for record in summary["optimizer_checkpoints"]:
        audit.file(f"checkpoints/step-{record['step']:04d}.pt", record["sha256"], record["bytes"])
    row_hash, schedule_hash = hashlib.sha256(), hashlib.sha256()
    sources, pairs, unique_media = set(), set(), set()
    audit.phase = "streaming_media_and_score_reconstruction"
    with (gzip.open(audit.root / "training-outputs.jsonl.gz", "rt", encoding="utf-8") as stream,
          gzip.open(audit.root / "trajectory-ledger.jsonl.gz", "rt", encoding="utf-8") as trajectories,
          zipfile.ZipFile(audit.root / "raw-media.zip", "r") as archive):
        for step in range(1, steps + 1):
            batch_seed, generation_seed = seed * 1000003 + 20261024 + step - 1, seed * 1000033 + 20261025 + step - 1
            batch = make_batch(corpus, "train", batch_size, batch_seed)
            schedule_row = {"step": step, "batch_seed": batch_seed, "generation_seed": generation_seed,
                            "observation_sha256": observation_digest(batch.observation),
                            "source_ids": batch.source_ids, "views": batch.views}
            schedule_hash.update(json.dumps(schedule_row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            rows, pixels, captions = [], [], []
            for index in range(batch_size * scenarios):
                line, row = _line(stream, "training row")
                row_hash.update(line.encode())
                condition, scenario = divmod(index, scenarios)
                require((row["step"], row["condition"], row["scenario"]) == (step, condition, scenario),
                        f"Missing, duplicate or out-of-order census row at {step}/{condition}/{scenario}")
                require(row["batch_seed"] == batch_seed and row["generation_seed"] == generation_seed,
                        "Logged generation or batch seed mismatch")
                require(tuple(row["source_ids"]) == batch.source_ids[condition] and row["view"] == batch.views[condition],
                        "Logged source IDs or view differ from registered task reconstruction")
                token_path = _tokens(row["sampled_tokens"])
                image, caption = read_media_record(archive, row["raw"])
                require(render_tokens(token_path) == caption, "Sampled tokens disagree with persisted UTF8")
                require(bool(((image == 0) | (image == 1)).all()), "Saved image is not an actual Bernoulli sample")
                require(type(row["terminal_log_probability"]) in {int, float}
                        and math.isfinite(row["terminal_log_probability"]) and row["terminal_log_probability"] <= 0,
                        "Invalid logged terminal log-probability")
                sources.update(row["source_ids"])
                pairs.add(tuple(sorted(row["source_ids"])))
                unique_media.update((kind, row["raw"][kind + "_sha256"]) for kind in ("image", "text"))
                rows.append(row)
                pixels.append(image)
                captions.append(caption)
                audit.counts.update({"output_rows_read": 1, "media_member_sha256_checks": 2,
                                     "token_caption_checks": 1, "physical_complete_outputs": int(row["raw"]["required_output_complete"])})
            pixels = torch.stack(pixels)
            _, trajectory = _line(trajectories, "trajectory step")
            events = trajectory["events"]
            require(trajectory["step"] == step and [event["phase"] for event in events] ==
                    ["initialized", "action_committed", "transition_completed", "action_committed", "transition_completed"],
                    "Trajectory step/action census mismatch")
            require(events[0]["prefix"] == ["refine_semantic", "couple"] and
                    [events[index]["action"] for index in (1, 2, 3, 4)] == ["refine_image"] * 2 + ["refine_text"] * 2,
                    "Trajectory does not implement the registered fixed action program")
            repeated = Observation(*(value.repeat_interleave(scenarios, 0) for value in
                                   (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
            require(events[0]["observation_sha256"] == observation_digest(repeated), "Trajectory input identity mismatch")
            require(output_digests(pixels, torch.tensor([row["sampled_tokens"] for row in rows])) ==
                    tuple(events[-1]["output_sha256"]), "Actual pixel/token paths differ from committed terminal ledger")
            audit.counts["terminal_pixel_token_digest_checks"] += len(rows)
            scores = observe_tensors(observer, pixels, captions, batch.target.pixels.repeat_interleave(scenarios, 0),
                                     batch.target.labels.repeat_interleave(scenarios, 0))
            for row, score in zip(rows, scores):
                require(_same(row["metric"], score), f"Logged metric mismatch at step {step}, condition {row['condition']}, scenario {row['scenario']}")
                require(_same(row["actual_observed_loss"], -score["utility"]), "Observed loss is not minus actual media utility")
                audit.counts.update({"output_rows_rescored": 1, "logged_metric_fields_checked": len(score), "actual_loss_checks": 1})
            audit.counts["complete_steps_checked"] += 1
        require(stream.read(1) == "" and trajectories.read(1) == "", "Extra rows outside the registered complete census")
    require(row_hash.hexdigest() == summary["training_rows_sha256"], "Training row-stream digest mismatch")
    require(schedule_hash.hexdigest() == summary["schedule_sha256"], "Reconstructed batch schedule digest mismatch")
    require(parameter_hash(observer) == identity, "Observer changed during read-only audit")
    audit.counts["observer_parameter_identity_checks"] += 1
    audit.report.update(unique_individual_sources=len(sources), unique_unordered_source_pairs=len(pairs),
                        unique_media_members_checked=len(unique_media),
                        source_scenario_dependence="Training conditions can reuse source images; scenario rows share their condition and model update. Counts are not an independent n.")


def audit_tree_selected(directory, data, selected_indices_by_policy, corpus, observers):
    """Rescore only the union of selected (row, plan) outputs from a sealed tree.

    Each policy supplies one integer plan index per data row. All policy replay
    references are counted, but repeated choices are scored once. This audits
    saved outcomes and selected metric cells, not the policy's decision rule or
    feature computation. No unselected raw media is decoded or rescored.
    """
    return _run(directory, "selected_tree", lambda audit: _tree(
        audit, data, selected_indices_by_policy, corpus, observers))


def _tree_scores(audit, pending, batch, data, observers):
    if not pending:
        return
    pixels = torch.stack([item[1] for item in pending])
    captions = [item[2] for item in pending]
    indices = [item[0]["case"] - data["pair_start"] for item in pending]
    for name, observer in observers.items():
        scores = observe_tensors(observer, pixels, captions, batch.target.pixels[indices], batch.target.labels[indices])
        for (row, _, _), score in zip(pending, scores):
            score["joint_fact_correct"] = bool(score["caption_valid"] and all(score[key] == 0 for key in
                                              ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
            score["required_output_complete"] = row["required_output_complete"]
            require(_same(row["observer_scores"][name], score), f"Selected tree raw score mismatch: {name}")
            for metric, values in data["metrics"][name].items():
                require(_same(float(values[row["row_index"], row["plan_index"]]), float(score[metric])),
                        f"Selected data metric mismatch: {name}/{metric}")
            audit.counts.update({"selected_observer_output_rescores": 1, "logged_metric_fields_checked": len(score)})
    audit.counts["unique_selected_outputs_rescored"] += len(pending)
    pending.clear()


def _tree(audit, data, selections, corpus, observers):
    summary = audit.sealed()
    require(summary.get("schema") == "hepta.ndu-abc.actual-tree-summary.v1", "Wrong tree summary schema")
    audit.file("registration.json", summary["registration_sha256"])
    audit.file("data.pt", summary["data_file_sha256"])
    require(data["records_file"] == "raw-rows.jsonl.gz", "Unrecognized raw-row file")
    audit.file("raw-rows.jsonl.gz", summary["records_file_sha256"])
    registration = audit.json("registration.json")
    require(registration["schema"] == "hepta.ndu-abc.actual-tree-registration.v1", "Wrong tree registration schema")
    require(registration["metric_sha256"] == METRIC_DIGEST and tuple(registration["views"]) == VIEWS,
            "Tree metric or view census mismatch")
    audit.source_pins(registration["source_sha256"])
    require(summary["source_sha256"] == registration["source_sha256"], "Tree source-code bindings differ")
    require(set(observers) == set(registration["observer_parameter_sha256"]), "Observer census mismatch")
    identities = {name: _observer_identity(observer, registration["observer_parameter_sha256"][name])
                  for name, observer in observers.items()}
    audit.counts["observer_parameter_identity_checks"] += len(observers)
    require(data["observer_parameter_sha256"] == summary["observer_parameter_sha256"] == identities,
            "Tree observer identities differ")
    for key in ("role", "pair_start", "pair_count", "scenarios_per_source", "training_seed", "snapshot_sha256"):
        require(data[key] == registration[key], f"Tree data/registration mismatch: {key}")
    role, start, count, scenarios = (registration[key] for key in
                                   ("role", "pair_start", "pair_count", "scenarios_per_source"))
    require(role in {"train", "development", "forecast_fit", "forecast_calibration"}
            and all(type(value) is int for value in (start, count, scenarios))
            and start >= 0 and min(count, scenarios) > 0, "Invalid tree source range")
    source = corpus.splits[role]
    selected_sources = source.ids[2 * start:2 * (start + count)]
    require(len(selected_sources) == len(set(selected_sources)) == 2 * count, "Tree source pairs overlap or are incomplete")
    source_identity = {"manifest_record_sha256": digest(corpus.manifest),
                       "manifest_declared_sha256": corpus.manifest.get("manifest_sha256"),
                       "source_ids_sha256": hashlib.sha256("\n".join(selected_sources).encode()).hexdigest(),
                       "original_pixels_sha256": hashlib.sha256(source.images[2 * start:2 * (start + count)].contiguous().numpy().tobytes()).hexdigest(),
                       "original_labels_sha256": hashlib.sha256(source.labels[2 * start:2 * (start + count)].contiguous().numpy().tobytes()).hexdigest()}
    require(source_identity == registration["source_identity"] == summary["source_identity"], "Tree source identity mismatch")
    require(data["source_manifest_sha256"] == corpus.manifest.get("manifest_sha256"), "Tree source manifest mismatch")
    observation_seed = int.from_bytes(hashlib.sha256(canonical(("observation", role, start))).digest()[:8], "big") % (2**63)
    require(registration["observation_seed"] == observation_seed, "Tree observation seed recipe mismatch")
    require(summary["snapshot_sha256"] == registration["snapshot_sha256"], "Tree snapshot identity mismatch")
    actions = ("refine_semantic", "refine_image", "refine_text", "couple")
    plans = [()] + [(action,) for action in actions] + [(a, b) for a in actions for b in actions]
    require([tuple(plan) for plan in registration["plans"]] == plans
            and [tuple(plan) for plan in data["plans"]] == plans, "Tree plan census mismatch")
    total_rows = len(VIEWS) * count * scenarios
    require(summary["rows"] == total_rows and summary["node_rows"] == total_rows * len(plans), "Tree summary census mismatch")
    require(all(len(data[key]) == total_rows for key in ("cases", "views", "scenarios", "source_ids")), "Incomplete data row census")
    require(isinstance(selections, dict) and bool(selections), "No selected policies to audit")
    choices, wanted = {}, set()
    for policy, values in selections.items():
        require(isinstance(policy, str) and bool(policy), "Invalid selected policy identity")
        values = values.detach().cpu().tolist() if isinstance(values, torch.Tensor) else list(values)
        require(len(values) == total_rows and all(type(value) is int and 0 <= value < len(plans) for value in values),
                f"Invalid selected plan census: {policy}")
        choices[policy] = values
        wanted.update(enumerate(values))
    require(set(data["metrics"]) == set(observers), "Data observer metric census mismatch")
    for metrics in data["metrics"].values():
        require(set(metrics) == {"utility", "joint_loss", "joint_fact_correct", "required_output_complete", *METRIC["weights"]},
                "Data metric-field census mismatch")
        require(all(isinstance(value, torch.Tensor) and tuple(value.shape) == (total_rows, len(plans))
                    for value in metrics.values()), "Invalid tree metric tensor shape")
    require(set(summary["archive_sha256"]) == {f"media/{view}.zip" for view in VIEWS}, "Tree archive census mismatch")
    for name, value in summary["archive_sha256"].items():
        audit.file(name, value)
    audit.report.update(role=role, training_seed=registration["training_seed"],
                        selected_plan_indices_sha256=digest(choices), policy_rows={name: len(rows) for name, rows in choices.items()},
                        policy_replay_rows=total_rows * len(choices), expected_unique_selected_outputs=len(wanted),
                        independent_source_pairs=count, unique_individual_sources=2 * count, independent_training_seeds=1,
                        policy_scenario_rows_are_independent_observations=False, policy_decisions_recomputed=False)
    audit.phase = "selected_tree_media_and_score_reconstruction"
    found, unique_media = set(), set()
    with gzip.open(audit.root / "raw-rows.jsonl.gz", "rt", encoding="utf-8") as stream:
        for view_index, view in enumerate(VIEWS):
            batch = make_batch(corpus, role, count, registration["observation_seed"], view=view, offset=start)
            pending = []
            with zipfile.ZipFile(audit.root / f"media/{view}.zip", "r") as archive:
                for index in range(count * scenarios):
                    case, scenario = divmod(index, scenarios)
                    row_index = view_index * count * scenarios + index
                    require((data["cases"][row_index], data["views"][row_index], data["scenarios"][row_index],
                             tuple(data["source_ids"][row_index])) == (start + case, view, scenario, batch.source_ids[case]),
                            "Tree data source/view/scenario mismatch")
                    for plan_index, plan in enumerate(plans):
                        _, row = _line(stream, "tree raw row")
                        require((row["row_index"], row["plan_index"]) == (row_index, plan_index), "Tree raw-row census mismatch")
                        audit.counts["raw_tree_rows_scanned"] += 1
                        if (row_index, plan_index) not in wanted:
                            continue
                        require((row["case"], row["view"], row["scenario"], tuple(row["source_ids"]), row["role"],
                                 tuple(row["path"]), row["view_archive"]) ==
                                (start + case, view, scenario, batch.source_ids[case], role, plan, f"media/{view}.zip"),
                                "Selected raw source/view/scenario/plan mismatch")
                        tokens = _tokens(row["token_path"])
                        require(digest(tokens) == row["token_path_sha256"], "Selected token-path digest mismatch")
                        pixels, caption = read_media_record(archive, row)
                        require(render_tokens(tokens) == caption and bool(((pixels == 0) | (pixels == 1)).all()),
                                "Selected actual media/token mismatch")
                        require(output_digests(pixels[None], torch.tensor([tokens]))[0] == row["output_sha256"],
                                "Selected pixel/token output digest mismatch")
                        require(set(row["observer_scores"]) == set(observers), "Selected raw observer census mismatch")
                        unique_media.update((kind, row[kind + "_sha256"]) for kind in ("image", "text"))
                        found.add((row_index, plan_index))
                        pending.append((row, pixels, caption))
                        audit.counts.update({"media_member_sha256_checks": 2, "token_caption_checks": 1,
                                             "terminal_pixel_token_digest_checks": 1})
                        if len(pending) == 128:
                            _tree_scores(audit, pending, batch, data, observers)
                _tree_scores(audit, pending, batch, data, observers)
        require(stream.read(1) == "", "Extra raw rows outside complete tree census")
    require(found == wanted, "Missing or duplicated selected tree outcomes")
    require(identities == {name: parameter_hash(observer) for name, observer in observers.items()}, "Observer changed during audit")
    audit.counts["observer_parameter_identity_checks"] += len(observers)
    audit.report.update(unique_media_members_checked=len(unique_media),
                        unselected_media_outputs_rescored=0,
                        source_scenario_dependence="Every policy shares the same source/view/scenario rows. Replays and generation scenarios do not enlarge the independent source-pair count.")
