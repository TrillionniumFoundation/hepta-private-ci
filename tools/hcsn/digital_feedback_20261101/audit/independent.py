"""Independent formulas over retained bytes; no project implementation imports.

This was written by the statistics implementation's author. Independence here
means separate computation, not third-party authorship or independent data.
"""
import argparse
from collections import defaultdict
import copy
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student

ARMS = ("fpt_base_multi", "fpt_neutral_drift", "fpt_neutral_bank", "fpt_neutral_both",
        "fpt_pooled_sign", "fpt_common_reset", "fpt_pooled_common", "fpt_base_single",
        "fpt_base_off", "ordinary_multi", "ordinary_single", "acc_free_off",
        "acc_free_multi", "acc_structured_off", "acc_structured_multi", "bayes")
CONTRASTS = (("fpt_feedback", "fpt_base_multi", "fpt_base_single"),
             ("ordinary_feedback", "ordinary_multi", "ordinary_single"))
TRAINING_FILES = sorted(["STARTED.json", "FINISHED.json", "training_data.json.gz",
                         "probe_train.json.gz", "models/independent_decoders.json"] +
                        [f"{directory}/{arm}{suffix}" for arm in ARMS if arm != "bayes"
                         for directory, suffix in (("models", ".json"), ("training", ".json.gz"),
                                                   ("attempts", ".json"))])


def read(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Review:
    def __init__(self):
        self.numeric_count = 0
        self.equality_count = 0
        self.violations_count = 0
        self.maximum_absolute_difference = 0.
        self.violations = []

    def fail(self, path, message, observed=None, expected=None):
        self.violations_count += 1
        if len(self.violations) < 100:
            self.violations.append(dict(path=path, message=message, observed=observed, expected=expected))

    def equal(self, path, observed, expected):
        self.equality_count += 1
        if observed != expected:
            self.fail(path, "equality mismatch", observed, expected)

    def number(self, path, observed, expected):
        self.numeric_count += 1
        if (not isinstance(observed, (int, float)) or not isinstance(expected, (int, float))
                or not math.isfinite(observed) or not math.isfinite(expected)):
            self.fail(path, "nonfinite or absent numeric value", repr(observed), repr(expected))
            return
        residual = abs(float(observed) - float(expected))
        self.maximum_absolute_difference = max(self.maximum_absolute_difference, residual)
        if residual > 1e-12 + 1e-10 * abs(expected):
            self.fail(path, "numeric tolerance exceeded", observed, expected)

    def tree(self, path, observed, expected):
        """State structure is exact; numerical coordinates use declared tolerances."""
        if isinstance(expected, dict) and isinstance(observed, dict):
            self.equal(path + "/keys", sorted(observed), sorted(expected))
            for key in expected.keys() & observed.keys():
                self.tree(path + "/" + key, observed[key], expected[key])
        elif isinstance(expected, list) and isinstance(observed, list):
            self.equal(path + "/length", len(observed), len(expected))
            for i, (value, target) in enumerate(zip(observed, expected)):
                self.tree(path + f"/{i}", value, target)
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            self.number(path, observed, expected)
        else:
            self.equal(path, observed, expected)

    def report(self):
        return dict(numeric_comparisons=self.numeric_count, equality_comparisons=self.equality_count,
                    violation_count=self.violations_count, violations=self.violations,
                    violations_truncated=self.violations_count > len(self.violations),
                    maximum_absolute_difference=self.maximum_absolute_difference,
                    absolute_tolerance=1e-12, relative_tolerance=1e-10,
                    numeric_bitwise_equality_claim=False, passed=self.violations_count == 0)


def legal(public, state):
    if state["terminal"]:
        return np.zeros(6, dtype=bool)
    tick = state["tick"]
    before = tick < public["deadline"]
    can_read = (before and state["budget"] > 0 and not state["broken"] and
                state["pending"] is None and tick + public["read_delay"][tick] <= public["deadline"])
    return np.asarray([True, before, can_read, before and state["broken"], True, True], dtype=bool)


def initial_state(public):
    return dict(tick=0, budget=public["initial_budget"], pending=None, broken=False,
                last_symbol=0, last_reliability=.5, history=[], elapsed=0., charges=0.,
                terminal=False, submitted=None)


def advance(public, previous, action, completion):
    """Reconstruct all task state from public rules and actual completion only."""
    if isinstance(action, bool) or not isinstance(action, int) or not 0 <= action < 6 or not legal(public, previous)[action]:
        raise ValueError("illegal executed action")
    result = copy.deepcopy(previous)
    if action in (0, 4, 5):
        if completion is not None:
            raise ValueError("terminal action cannot complete a READ")
        result["terminal"] = True
        result["pending"] = None
        result["submitted"] = {0: None, 4: 0, 5: 1}[action]
        return result, None
    tick = previous["tick"]
    if action == 2:
        result["pending"] = {"source_tick": tick, "due_tick": tick + public["read_delay"][tick]}
        result["budget"] = previous["budget"] - 1
        result["charges"] += public["read_price"][tick]
    if action == 3:
        result["broken"] = False
        result["charges"] += public["repair_price"]
    result["tick"] = tick + 1
    result["elapsed"] += public["duration"][tick]
    result["charges"] += public["latency_price"] * public["duration"][tick]
    pending = result["pending"]
    due = pending["source_tick"] if pending is not None and pending["due_tick"] == tick + 1 else None
    if (due is None) != (completion is None):
        raise ValueError("READ completion does not match due request")
    if due is not None:
        result["pending"] = None
        if completion.get("failure", False):
            if completion.get("observation") is not None:
                raise ValueError("failed READ cannot also provide an observation")
            result["broken"] = True
        else:
            observed = completion.get("observation")
            if isinstance(observed, bool) or observed not in (0, 1):
                raise ValueError("completed READ requires a binary observation")
            reliability = public["reliability"][due]
            result["history"] += [dict(source_tick=due, observation=observed, reliability=reliability)]
            result["last_symbol"] = 2 * observed - 1
            result["last_reliability"] = reliability
    return result, due


def expected_spec(arm):
    if arm not in ARMS or arm == "bayes":
        raise ValueError("unknown trained candidate")
    values = dict(id=arm, family="first_passage_bank", terminal_mode="structured", feedback="multi",
                  drift="sustained", bank_driver="last", event_sign_readout="signed", reset="signed")
    if arm.startswith("ordinary_"):
        values.update(family="ordinary_bank", feedback=arm.rsplit("_", 1)[1])
    elif arm.startswith("acc_"):
        _, head, feedback = arm.split("_")
        values.update(family="evidence_accumulator", terminal_mode=head, feedback=feedback)
    elif arm.startswith("fpt_base_"):
        values["feedback"] = arm.rsplit("_", 1)[1]
    if arm in ("fpt_neutral_drift", "fpt_neutral_both"):
        values["drift"] = "neutral"
    if arm in ("fpt_neutral_bank", "fpt_neutral_both"):
        values["bank_driver"] = "neutral"
    if arm in ("fpt_pooled_sign", "fpt_pooled_common"):
        values["event_sign_readout"] = "pooled"
    if arm in ("fpt_common_reset", "fpt_pooled_common"):
        values["reset"] = "common"
    return values


def latent_contract(review, decision, candidate, first, path):
    cell = candidate.startswith("fpt_") or candidate.startswith("ordinary_")
    if first:
        review.equal(path + "/initial_latent", decision["latent_index"], 7 if cell else 0)
    sampled = cell and decision["action"] not in (0, 4, 5)
    review.equal(path + "/sampling_contract", decision["event"]["sampled"], sampled)
    if not sampled:
        review.equal(path + "/unchanged_latent", decision["latent_after"], decision["latent_index"])
        review.equal(path + "/no_event", decision["event"]["event"], False)
        review.equal(path + "/no_recovery", decision["event"]["recovery"], False)


def retained_label(content):
    logits = np.asarray(content.get("logits"), dtype=float)
    if logits.ndim != 1 or len(logits) < 2 or not np.isfinite(logits).all():
        raise ValueError("completed content lacks finite retained logits")
    return int(logits[1] > logits[0])


def decision_values(public, decision, label):
    action, state = decision["action"], decision["state"]
    mask = legal(public, state)
    q = np.asarray(decision["scores"]["q"], dtype=float)
    target = np.asarray(decision["teacher_q"], dtype=float)
    belief, truth = float(decision["scores"]["belief"]), float(decision["teacher_belief"])
    if (q.shape != (6,) or target.shape != (6,) or not np.isfinite(q).all()
            or not np.isfinite(target).all() or not 0 <= belief <= 1 or not 0 <= truth <= 1
            or not isinstance(action, int) or not 0 <= action < 6 or not mask[action]):
        raise ValueError("invalid decision coordinates, probabilities or legal action")
    positions = np.flatnonzero(mask).tolist()
    ordered = sorted(q[i] for i in positions)
    teacher_ordered = sorted(target[i] for i in positions)
    error = float(q[action] - target[action])
    regret = float(max(target[i] for i in positions) - target[action])
    margin = float(ordered[-1] - ordered[-2])
    comparable = [(i, j) for a, i in enumerate(positions) for j in positions[a + 1:]
                  if abs(target[i] - target[j]) > 1e-12]
    wrong_rank = sum((target[i] - target[j]) * (q[i] - q[j]) <= 0 for i, j in comparable)
    structure = max(abs(q[0]), abs(q[4] - (1 - 2 * belief)), abs(q[5] - (2 * belief - 1)))
    raw = dict(selected_q_error=error, selected_q_squared_error=error * error,
               selected_margin=margin, oracle_regret=regret, belief_squared_error=(belief - truth) ** 2,
               wrong_stop=action == 0 and max(target[i] for i in positions) > .02,
               wrong_submit=action in (4, 5) and regret > .02,
               terminal_sign_error=action in (4, 5) and target[action] < -1e-12,
               terminal_structure_error=float(structure))
    diagnostic = dict(selected_q_error=error, selected_q_mse=error * error,
        belief_prediction=belief, belief_teacher=truth, belief_calibration_bias=belief - truth,
        belief_teacher_mse=(belief - truth) ** 2,
        belief_teacher_expected_brier=(belief - truth) ** 2 + truth * (1 - truth),
        teacher_regret=regret, teacher_optimal_action=float(regret <= 1e-12),
        predicted_margin=margin, teacher_margin=float(teacher_ordered[-1] - teacher_ordered[-2]),
        chosen_prediction_margin=float(q[action] - max(q[i] for i in positions if i != action)),
        pairwise_ranking_error=float(wrong_rank / len(comparable)) if comparable else None,
        actual_label_brier=(belief - label) ** 2)
    return raw, diagnostic


def episode_values(review, episode, public, path, evaluator_label=None, world_folder=None):
    state = episode["final_state"]
    label = episode["label"] if evaluator_label is None else evaluator_label
    review.equal(path + "/label_from_evaluator", episode["label"], label)
    if label not in (0, 1) or not state["terminal"] or not episode["label_access_after_terminal"]:
        raise ValueError("valid evaluator label and a completed terminal episode required")
    submitted = state["submitted"]
    if submitted not in (None, 0, 1):
        raise ValueError("invalid submission")
    reward = 0 if submitted is None else 1 if submitted == label else -1
    outcome = dict(reward=reward, utility=reward - state["charges"], charges=state["charges"],
        correct=float(submitted == label), submitted=submitted is not None,
        reads_requested=3 - state["budget"], reads_completed=len(state["history"]), elapsed=state["elapsed"],
        decisions=len(episode["decisions"]))
    raw_rows, diagnostics = [], []
    replay = initial_state(public)
    charge_sum = 0.
    events = recoveries = completed = failed = payload = 0
    for ordinal, decision in enumerate(episode["decisions"]):
        current = f"{path}/decision_{ordinal}"
        latent_contract(review, decision, episode["candidate"], ordinal == 0, current)
        review.tree(current + "/replayed_before", decision["state"], replay)
        successor, due_source = advance(public, replay, decision["action"], decision["completion"])
        review.tree(current + "/replayed_after", decision["after"], successor)
        replay = successor
        raw, diagnostic = decision_values(public, decision, label)
        for name, value in raw.items():
            if isinstance(value, (bool, np.bool_)):
                review.equal(current + "/" + name, decision.get(name), bool(value))
            else:
                review.number(current + "/" + name, decision.get(name), value)
        if episode["controller"] == "value":
            scores = decision["scores"]["q"]
            allowed = legal(public, decision["state"])
            selected = max((i for i in range(6) if allowed[i]), key=lambda i: (scores[i], -i))
            review.equal(current + "/greedy_action", decision["action"], selected)
        if ordinal:
            review.equal(current + "/state_continuity", decision["state"], episode["decisions"][ordinal - 1]["after"])
            review.equal(current + "/latent_continuity", decision["latent_index"], episode["decisions"][ordinal - 1]["latent_after"])
        action = decision["action"]
        if action not in (0, 4, 5):
            tick = decision["state"]["tick"]
            charge_sum += public["latency_price"] * public["duration"][tick]
            charge_sum += public["read_price"][tick] if action == 2 else public["repair_price"] if action == 3 else 0
        flags = decision["event"]
        events += int(flags["event"])
        recoveries += int(flags["recovery"])
        if flags["sampled"]:
            review.equal(current + "/event", flags["event"], decision["latent_index"] < 15 <= decision["latent_after"])
            review.equal(current + "/recovery", flags["recovery"], decision["latent_after"] < 15 <= decision["latent_index"])
        content = decision.get("content")
        if due_source is None:
            review.equal(current + "/no_unsolicited_content", content, None)
        elif decision["completion"].get("failure", False):
            review.equal(current + "/failure_content", isinstance(content, dict) and "failure" in content, True)
        else:
            review.equal(current + "/completed_content", isinstance(content, dict) and "failure" not in content, True)
            if isinstance(content, dict):
                review.equal(current + "/observed_content", content.get("observation"), decision["completion"]["observation"])
                review.equal(current + "/opened_source_digest", content.get("payload_sha256"), public["packet_sha256"][due_source])
                review.equal(current + "/retained_logits_argmax", content.get("observation"), retained_label(content))
                if world_folder is not None:
                    packet_path = Path(world_folder) / public["packets"][due_source]
                    review.number(current + "/actual_payload_bytes", content.get("payload_bytes"), packet_path.stat().st_size)
        completed += int(content is not None and "failure" not in content)
        failed += int(content is not None and "failure" in content)
        payload += content.get("payload_bytes", 0) if content else 0
        raw_rows.append(raw)
        diagnostics.append(diagnostic)
    if not raw_rows:
        raise ValueError("no decision in a completed episode")
    review.equal(path + "/terminal_successor", episode["decisions"][-1]["after"], state)
    review.tree(path + "/full_replayed_terminal_state", state, replay)
    review.number(path + "/charges_from_actions", state["charges"], charge_sum)
    outcome.update(events=events, recoveries=recoveries, completed_content_calls=completed,
                   failed_content_calls=failed, payload_bytes=payload)
    for name in ("selected_q_squared_error", "oracle_regret", "belief_squared_error", "selected_margin"):
        outcome[name] = float(np.mean([row[name] for row in raw_rows]))
    for name in ("wrong_stop", "wrong_submit", "terminal_sign_error"):
        outcome[name] = sum(int(row[name]) for row in raw_rows)
    outcome["terminal_structure_error"] = max(row["terminal_structure_error"] for row in raw_rows)
    for name, value in outcome.items():
        review.number(path + "/metrics/" + name, episode["metrics"].get(name), value)
    return outcome, diagnostics


def infer(fits, means, validity):
    output = {}
    for split in ("iid", "ood"):
        for name, positive, negative in CONTRASTS:
            if any((fit, split, candidate) not in means or not validity.get((fit, split, candidate), False)
                   for fit in fits for candidate in (positive, negative)) or len(fits) < 2:
                output[(split, name)] = None
                continue
            values = [means[(fit, split, positive)] - means[(fit, split, negative)] for fit in fits]
            average = sum(values) / len(values)
            sd = math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))
            se = sd / math.sqrt(len(values))
            critical = float(student.ppf(1 - .05 / 8, len(values) - 1))
            output[(split, name)] = dict(mean=average, sample_sd=sd, standard_error=se,
                critical_t=critical, n_independent_fits=len(values), degrees_of_freedom=len(values) - 1,
                confidence_interval=[average - critical * se, average + critical * se],
                benefit_gate=average - critical * se > .02)
    return output


def audit(confirmation, protocol_path, analysis_path, seal_path=None, training=None):
    review = Review()
    protocol, analysis = read(protocol_path), read(analysis_path)
    fits = protocol["fits"]
    if len(fits) != len(set(fits)) or not fits:
        raise ValueError("nonempty unique registered fits required")
    seal = read(seal_path) if seal_path else None
    if seal:
        review.equal("seal/schema", seal.get("schema"), "digital-feedback-sealed-models-v1")
        review.equal("seal/protocol", seal["protocol"], protocol)
        review.equal("seal/fits", seal["fits"], fits)
        repository = Path(__file__).resolve().parents[4]
        namespace = Path(__file__).resolve().parents[1]
        inherited = read(namespace.parent / "digital_mechanisms_20261101/SOURCE_FREEZE.json")["source_sha256"]
        source_keys = set(inherited) | {str(path.relative_to(repository)) for path in namespace.glob("*.py")}
        source_keys.add(str(Path(protocol_path).resolve().relative_to(repository)))
        review.equal("seal/source_inventory", sorted(seal["source_sha256"]), sorted(source_keys))
        for name in ("training_files_sha256", "process_sha256"):
            review.equal("seal/" + name + "/fit_keys", sorted(seal[name]), sorted(str(f) for f in fits))
        for fit in fits:
            review.equal(f"seal/fit_{fit}/required_training_paths", sorted(seal["training_files_sha256"].get(str(fit), {})), TRAINING_FILES)
        for name, expected in seal["source_sha256"].items():
            source = repository / name
            review.equal("source/" + name, sha(source) if source.exists() else None, expected)
        remote_path = Path(seal_path).parent / seal["remote_verification_file"]
        review.equal("remote_receipt/bytes", sha(remote_path), seal["remote_verification_sha256"])
        remote = read(remote_path)
        review.equal("remote_receipt/commit", remote["commit"], seal["published_models_commit"])
        review.equal("remote_receipt/model_manifest", remote["model_manifest_sha256"], seal["model_manifest_sha256"])
        review.equal("remote_receipt/verified_flag", remote["all_blob_hashes_verified"], True)
    means, validity = {}, {}
    totals = dict(fits=0, episode_files=0, episodes=0, decisions=0, source_files=0, training_files=0, dataset_files=0)
    for fit in fits:
        folder = Path(confirmation) / f"fit_{fit}"
        completion_path = folder / "FINISHED.json"
        process_path = Path(confirmation) / "process_receipts" / f"fit_{fit}.json"
        operational = completion_path.exists() and process_path.exists() and not (folder / "FAILED.json").exists()
        review.equal(f"fit_{fit}/confirmation_completion_files", operational, True)
        if completion_path.exists():
            review.equal(f"fit_{fit}/confirmation_finished_fit", read(completion_path).get("fit"), fit)
        if process_path.exists():
            process = read(process_path)
            review.equal(f"fit_{fit}/confirmation_process_fit", process.get("fit"), fit)
            review.equal(f"fit_{fit}/confirmation_process_returncode", process.get("returncode"), 0)
            operational = operational and process.get("returncode") == 0
        if not (folder / "STARTED.json").exists():
            review.fail(str(folder), "missing confirmation STARTED")
            continue
        started = read(folder / "STARTED.json")
        review.equal(f"fit_{fit}/started/fit", started["fit"], fit)
        review.equal(f"fit_{fit}/started/preexisting", started["confirmation_preexisting"], False)
        if seal:
            review.equal(f"fit_{fit}/started/seal", started["seal_sha256"], sha(seal_path))
            review.equal(f"fit_{fit}/started/models_commit", started["published_models_commit"], seal["published_models_commit"])
            review.equal(f"fit_{fit}/chronology", datetime.fromisoformat(started["utc"]) >= datetime.fromisoformat(seal["sealed_utc"]), True)
        if training and seal:
            trained = Path(training) / f"fit_{fit}"
            for relative, expected in seal["training_files_sha256"][str(fit)].items():
                path = trained / relative
                review.equal(f"fit_{fit}/training/" + relative, sha(path) if path.exists() else None, expected)
                totals["training_files"] += 1
            for name in ("STARTED.json", "FINISHED.json"):
                review.equal(f"fit_{fit}/training_source/" + name, read(trained / name)["source_sha256"], seal["source_sha256"])
                review.equal(f"fit_{fit}/training_fit/" + name, read(trained / name).get("fit"), fit)
            review.equal(f"fit_{fit}/training_started_protocol", read(trained / "STARTED.json")["protocol"], protocol)
            review.equal(f"fit_{fit}/training_started_stage", read(trained / "STARTED.json")["stage"], "formal_fit")
            review.equal(f"fit_{fit}/training_failed_file", (trained / "FAILED.json").exists(), False)
            process = Path(training) / "process_receipts" / f"fit_{fit}.json"
            review.equal(f"fit_{fit}/training_process", sha(process), seal["process_sha256"][str(fit)])
            review.equal(f"fit_{fit}/training_process_returncode", read(process).get("returncode"), 0)
            operational = operational and read(process).get("returncode") == 0 and not (trained / "FAILED.json").exists()
            for candidate in ARMS[:-1]:
                expected = expected_spec(candidate)
                artifact = read(trained / "models" / f"{candidate}.json")
                receipt = read(trained / "training" / f"{candidate}.json.gz")
                attempt = read(trained / "attempts" / f"{candidate}.json")
                context = f"fit_{fit}/model_provenance/{candidate}"
                review.equal(context + "/fit", artifact.get("fit"), fit)
                review.equal(context + "/family", artifact.get("family"), expected["family"])
                review.equal(context + "/terminal_mode", artifact.get("terminal_mode"), expected["terminal_mode"])
                review.equal(context + "/factors", artifact.get("factors"),
                    {key: expected[key] for key in ("drift", "bank_driver", "event_sign_readout", "reset")})
                review.equal(context + "/physical_trainable", artifact.get("physical_trainable"), False)
                review.equal(context + "/receipt_fit", receipt.get("fit"), fit)
                review.equal(context + "/spec", receipt.get("spec"), expected)
                encoded = json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                review.equal(context + "/returned_model_identity", receipt.get("returned_model_sha256"), hashlib.sha256(encoded).hexdigest())
                review.equal(context + "/attempt_returned", attempt.get("returned"), True)
                review.equal(context + "/attempt_candidate", attempt.get("candidate"), candidate)
                review.equal(context + "/attempt_valid", attempt.get("valid"), receipt.get("training_valid"))
                review.equal(context + "/attempt_cpu", attempt.get("cpu_compliant"), receipt.get("cpu_compliant"))
        if not (folder / "summary.json").exists():
            review.fail(str(folder), "missing summary")
            continue
        summary = {}
        for row in read(folder / "summary.json"):
            key = (row["fit"], row["split"], row["candidate"])
            if key in summary:
                raise ValueError("duplicate registered summary identity")
            summary[key] = row
        review.equal(f"fit_{fit}/summary_identity_set", sorted(summary),
                     sorted((fit, split, arm) for split in ("iid", "ood") for arm in ARMS))
        totals["fits"] += 1
        for split in ("iid", "ood"):
            raw_path = folder / f"{split}_episodes.json.gz"
            if not raw_path.exists():
                review.fail(str(raw_path), "missing raw episodes; related inference must be null")
                continue
            episodes = read(raw_path)
            audited = read(folder / f"{split}_audits.json.gz")
            cohort = read(folder / f"{split}_cohort.json")
            world_ids = [record["id"] for record in cohort["records"]]
            world_ordinal = {world: ordinal for ordinal, world in enumerate(world_ids)}
            review.equal(f"fit_{fit}/{split}/cohort_unique_count", len(set(world_ids)), protocol[f"{split}_worlds"])
            for relative, expected_hash in cohort["files"].items():
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError("cohort file escapes declared worlds directory")
                actual_path = folder / "worlds" / relative_path
                review.equal(f"fit_{fit}/{split}/cohort_hash/{relative}",
                             sha(actual_path) if actual_path.exists() else None, expected_hash)
                totals["dataset_files"] += 1
            publics, evaluators, required_dataset_files = {}, {}, set()
            for world in world_ids:
                if Path(world).name != world:
                    raise ValueError("invalid world identifier")
                world_folder = folder / "worlds" / world
                public = publics[world] = read(world_folder / "public.json")
                evaluator = evaluators[world] = read(world_folder / "evaluator.json")
                required_dataset_files.update((world + "/public.json", world + "/evaluator.json"))
                review.equal(f"fit_{fit}/{split}/{world}/public_dimensions",
                             [public["deadline"], public["initial_budget"]], [6, 3])
                review.equal(f"fit_{fit}/{split}/{world}/label_domain", evaluator.get("label") in (0, 1), True)
                for slot, name in enumerate(public["packets"]):
                    if Path(name).name != name:
                        raise ValueError("invalid public packet filename")
                    relative = world + "/" + name
                    absent = evaluator["injected_missing"][slot]
                    review.equal(f"fit_{fit}/{split}/{relative}/present", (world_folder / name).exists(), not absent)
                    if not absent:
                        required_dataset_files.add(relative)
                        review.equal(f"fit_{fit}/{split}/{relative}/public_packet_sha", public["packet_sha256"][slot], cohort["files"].get(relative))
            review.equal(f"fit_{fit}/{split}/cohort_file_inventory", sorted(cohort["files"]), sorted(required_dataset_files))
            groups, computed_decisions, seen = defaultdict(list), defaultdict(dict), set()
            totals["episode_files"] += 1
            for episode in episodes:
                identity = (episode["candidate"], episode["world"])
                if identity in seen:
                    raise ValueError("duplicate candidate/world execution")
                seen.add(identity)
                current = f"fit_{fit}/{split}/{identity[0]}/{identity[1]}"
                review.equal(current + "/identity", [episode["fit"], episode["split"], episode["controller"]], [fit, split, "value"])
                expected_seed = protocol["execution_seed_base"] + fit * 100000 + (20000 if split == "ood" else 10000) + world_ordinal[episode["world"]]
                review.equal(current + "/paired_execution_seed", episode["seed"], expected_seed)
                public = publics[episode["world"]]
                review.equal(current + "/public_id", public["id"], episode["world"])
                values, decisions = episode_values(review, episode, public, current, evaluators[episode["world"]]["label"],
                                                   folder / "worlds" / episode["world"])
                groups[episode["candidate"]].append(values)
                for ordinal, decision in enumerate(decisions):
                    computed_decisions[episode["candidate"]][(episode["world"], ordinal)] = decision
                totals["episodes"] += 1
                totals["decisions"] += len(decisions)
            review.equal(f"fit_{fit}/{split}/candidate_set", sorted(groups), sorted(ARMS))
            for candidate in ARMS:
                key = (fit, split, candidate)
                row, values = summary.get(key), groups.get(candidate, [])
                review.equal(str(key) + "/paired_world_ids", sorted(world for arm, world in seen if arm == candidate), sorted(world_ids))
                if row is None or len(values) != protocol[f"{split}_worlds"]:
                    review.fail(str(key), "missing summary or incomplete registered world count")
                    validity[key] = False
                    continue
                review.equal(str(key) + "/worlds", row["worlds"], len(values))
                for metric in values[0]:
                    average = float(np.mean([value[metric] for value in values]))
                    review.number(str(key) + "/summary/" + metric, row["metrics"].get(metric), average)
                means[key] = float(np.mean([value["utility"] for value in values]))
                validity[key] = row.get("valid") is True and operational
                if training and candidate != "bayes":
                    receipt = read(Path(training) / f"fit_{fit}" / "training" / f"{candidate}.json.gz")
                    cpu_pass = abs(receipt["candidate_cpu_seconds"] - protocol["training_cpu_seconds"]) <= protocol["cpu_tolerance_seconds"]
                    review.equal(str(key) + "/cpu_flag", receipt["cpu_compliant"], cpu_pass)
                    expected_valid = receipt["training_valid"] is True and cpu_pass
                    review.equal(str(key) + "/valid", row.get("valid"), expected_valid)
                    validity[key] = expected_valid and operational
                diagnostic = audited.get(candidate)
                if diagnostic is None:
                    review.fail(str(key), "missing final-policy diagnostics")
                    continue
                seen_diagnostics = set()
                for item in diagnostic["decisions"]:
                    identity = (item["world"], item["decision"])
                    if identity in seen_diagnostics or identity not in computed_decisions[candidate]:
                        raise ValueError("duplicate or unknown diagnostic decision")
                    seen_diagnostics.add(identity)
                    for name, value in computed_decisions[candidate][identity].items():
                        observed = item["metrics"].get(name)
                        if value is None:
                            review.equal(str(key) + "/diagnostic/" + name, observed, None)
                        else:
                            review.number(str(key) + "/diagnostic/" + name, observed, value)
                review.equal(str(key) + "/diagnostic_count", len(seen_diagnostics), len(computed_decisions[candidate]))
    fresh = infer(fits, means, validity)
    review.equal("analysis/fits", analysis.get("fits"), fits)
    review.number("analysis/n_independent_fits", analysis.get("n_independent_fits"), len(fits))
    review.equal("analysis/all_primary_valid", analysis.get("all_primary_valid"), all(value is not None for value in fresh.values()))
    review.equal("analysis/all_four_benefit_gates", analysis.get("all_four_benefit_gates"),
                 all(value is not None and value["benefit_gate"] for value in fresh.values()))
    reported = {}
    for row in analysis["primary"]:
        key = (row["split"], row["contrast"])
        if key in reported:
            raise ValueError("duplicate primary inference")
        reported[key] = row
    review.equal("analysis/primary_keys", sorted(reported), sorted(fresh))
    for key, expected in fresh.items():
        row = reported.get(key, {})
        review.equal(str(key) + "/valid", row.get("valid"), expected is not None)
        if expected is None:
            review.equal(str(key) + "/inference", row.get("inference"), None)
            review.equal(str(key) + "/benefit_gate", row.get("benefit_gate"), None)
            continue
        inference = row.get("inference") or {}
        for name, value in expected.items():
            if name == "benefit_gate":
                review.equal(str(key) + "/" + name, row.get(name), value)
            elif name == "confidence_interval":
                observed = inference.get(name) or [None, None]
                for i in range(2):
                    review.number(str(key) + f"/ci_{i}", observed[i], value[i])
            else:
                review.number(str(key) + "/" + name, inference.get(name), value)
    totals["source_files"] = len(seal["source_sha256"]) if seal else 0
    return dict(schema="digital-feedback-separate-numeric-audit-v1", **review.report(), counts=totals,
        inputs=dict(protocol_sha256=sha(protocol_path), analysis_sha256=sha(analysis_path),
                    seal_sha256=sha(seal_path) if seal_path else None),
        source_verification="checked against seal" if seal else "not requested",
        model_bytes_verification="checked against seal" if seal and training else "not requested",
        independent_primary=[dict(split=key[0], contrast=key[1], inference=value) for key, value in fresh.items()],
        independence="Separate formulas, no project imports; same author as statistics.py, not third-party review.",
        limits="Recomputes recorded teacher-target decision metrics, not the teacher oracle, model head, cell transition draws or neural content decoder. Content observation is checked against retained logits and packet identity. Fingerprints, support strata, ECE, eight quality gates and independently fitted decoder outputs are not recomputed here. Timing truth, distribution-free inference, unseen policy support and production efficacy are not established.")


def self_check():
    # Each intentional fault is retained in the returned report.
    public = dict(deadline=6, read_delay=[1] * 6, duration=[1.] * 6,
                  latency_price=.1, read_price=[.2] * 6, repair_price=.05,
                  initial_budget=3, reliability=[.85] * 6, packet_sha256=["0" * 64] * 6)
    state = dict(terminal=False, tick=6, budget=2, broken=False, pending=None)
    decision = dict(action=5, state=state, scores=dict(q=[0., 7., 7., 7., -.6, .6], belief=.8),
                    teacher_q=[0., 0., 0., 0., -.4, .4], teacher_belief=.7)
    raw, diagnostic = decision_values(public, decision, 1)
    check = Review()
    check.number("selected_Q_mse", raw["selected_q_squared_error"], .04)
    check.number("belief_teacher_mse", raw["belief_squared_error"], .01)
    check.number("legal_margin_ignores_illegal_high_Q", raw["selected_margin"], .6)
    check.number("teacher_regret", raw["oracle_regret"], 0.)
    check.number("actual_brier", diagnostic["actual_label_brier"], .04)
    fits = [1, 2, 3]
    means = {(f, split, arm): (.1 * f if arm.endswith("multi") else 0.)
             for f in fits for split in ("iid", "ood") for arm in
             ("fpt_base_multi", "fpt_base_single", "ordinary_multi", "ordinary_single")}
    validity = {key: True for key in means}
    full = infer(fits, means, validity)
    check.number("paired_mean", full[("iid", "fpt_feedback")]["mean"], .2)
    check.number("paired_SD", full[("iid", "fpt_feedback")]["sample_sd"], .1)
    validity[(2, "iid", "fpt_base_single")] = False
    check.equal("invalid_fit_nulls_contrast", infer(fits, means, validity)[("iid", "fpt_feedback")], None)
    del means[(3, "ood", "ordinary_multi")]
    check.equal("missing_fit_nulls_contrast", infer(fits, means, validity)[("ood", "ordinary_feedback")], None)
    rejected = Review()
    rejected.number("intentional_metric_corruption", raw["selected_q_squared_error"] + .01, .04)
    rejected.number("intentional_nonfinite", float("nan"), .01)
    check.equal("numeric_faults_detected", rejected.violations_count, 2)
    delayed = dict(public, read_delay=[2, 1, 1, 1, 1, 1])
    start = initial_state(delayed)
    waiting, source = advance(delayed, start, 2, None)
    check.equal("delayed_READ_not_early", source, None)
    check.equal("delayed_READ_pending", waiting["pending"], dict(source_tick=0, due_tick=2))
    observed, source = advance(delayed, waiting, 1, dict(observation=1))
    check.equal("delayed_READ_source", source, 0)
    check.equal("history_uses_source_reliability", observed["history"], [dict(source_tick=0, observation=1, reliability=.85)])
    broken, source = advance(delayed, observed, 2, dict(failure=True))
    check.equal("failed_READ_marks_broken", broken["broken"], True)
    repaired, source = advance(delayed, broken, 3, None)
    terminal, source = advance(delayed, repaired, 4, None)
    check.tree("complete_delayed_failure_repair_submit", terminal,
        dict(tick=4, budget=1, pending=None, broken=False, last_symbol=1, last_reliability=.85,
             history=[dict(source_tick=0, observation=1, reliability=.85)], elapsed=4., charges=.85,
             terminal=True, submitted=0))
    for action, submission in ((0, None), (4, 0), (5, 1)):
        ended, source = advance(delayed, waiting, action, None)
        check.equal(f"terminal_{action}_submission", ended["submitted"], submission)
        check.equal(f"terminal_{action}_cancels_pending", ended["pending"], None)
        check.number(f"terminal_{action}_no_elapsed", ended["elapsed"], waiting["elapsed"])
    successor_rejections = []
    for name, previous, action, completion in (
            ("unsolicited", start, 1, dict(observation=1)),
            ("too_early", start, 2, dict(observation=1)),
            ("missing_due", waiting, 1, None),
            ("failure_with_observation", waiting, 1, dict(failure=True, observation=1)),
            ("read_while_broken", broken, 2, dict(observation=1))):
        try:
            advance(delayed, previous, action, completion)
        except ValueError as error:
            successor_rejections.append(dict(case=name, rejected=True, error=str(error)))
        else:
            check.fail(name, "invalid successor fixture accepted")
    altered = dict(terminal, submitted=1)
    rejected.tree("intentional_terminal_submission_corruption", altered, terminal)
    check.equal("terminal_mapping_corruption_detected", rejected.violations_count, 3)
    for candidate, index in (("fpt_base_multi", 7), ("ordinary_multi", 7), ("acc_free_off", 0), ("bayes", 0)):
        terminal_decision = dict(action=5, latent_index=index, latent_after=index,
                                 event=dict(sampled=False, event=False, recovery=False))
        latent_contract(check, terminal_decision, candidate, True, "valid_terminal_" + candidate)
    bad_terminal = dict(action=5, latent_index=7, latent_after=8,
                        event=dict(sampled=True, event=False, recovery=False))
    latent_contract(rejected, bad_terminal, "fpt_base_multi", True, "intentional_terminal_sampling")
    check.equal("terminal_sampling_and_state_change_detected", rejected.violations_count, 5)
    check.equal("retained_logits_tie_uses_zero", retained_label(dict(logits=[.5, .5, 99.])), 0)
    check.equal("retained_logits_binary_only", retained_label(dict(logits=[.1, .2, 99.])), 1)
    rejected.equal("intentional_retained_logits_label_corruption", 0, retained_label(dict(logits=[.1, .2])))
    rejected.number("intentional_payload_byte_count_corruption", 8, len(b"payload"))
    check.equal("content_identity_faults_detected", rejected.violations_count, 7)
    return dict(schema="digital-feedback-separate-audit-selfcheck-v1", **check.report(),
                expected_rejections=rejected.report(), successor_rejections=successor_rejections,
                empirical_data_used=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        result = self_check()
    else:
        if not all((args.confirmation, args.protocol, args.analysis)):
            parser.error("--confirmation, --protocol and --analysis are required")
        result = audit(args.confirmation, args.protocol, args.analysis, args.seal, args.training)
    data = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(data)
    print(data)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
