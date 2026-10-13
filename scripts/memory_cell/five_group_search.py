"""Group-level evidence search using the existing offline Reader/Encoder owner.

One shared recurrent controller, a common answer-value readout, and a fixed
menu of actual evidence views. NDU here is explicitly ONE-STEP expected score
improvement minus a declared per-Reader-call utility cost, NOT a general FBSDE.
Neither predicted value nor a controller checkpoint is independent evidence.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import itertools
import math
from pathlib import Path
import random
import time

import torch
from torch import nn
from safetensors.torch import load_file, save_file

import five_causal_experiments as c
from five_causal_native import NativeSession, admit_stage, count_forwards, public_text
from experiments.shared_stem_cell.execution import LocalEncoder, measured, parameters

SCHEMA = "hepta.five-group.bundle.v1"
PROFILE = "hepta.five-group.one-step-expected-score.v1"
ARCHITECTURE = "state-candidate-interaction-v2"
PREPROCESSOR = "five-group.public-view-and-raw-answer.mean-pool.v1"
MENU = {"rule": "empty-then-singletons-then-source-order-pairs-v1", "maximum_sources": 8}
MODES = tuple(c.ARMS["system2"]) + tuple(c.ARMS["ndu"])
ENCODING_EXECUTION = "ordered-chunks-32-items-32768-padded-tokens-v1"


def require(ok, message):
    c.require(ok, message)


def checked_tensor(value, width, *, matrix=False):
    with torch.inference_mode(False), torch.no_grad():
        t = value.detach().clone() if isinstance(value, torch.Tensor) else torch.tensor(value, dtype=torch.float32)
    require(t.device.type == "cpu" and t.dtype == torch.float32, "CPU float32 feature profile required")
    if matrix:
        if t.numel() == 0:
            t = t.reshape(0, width)
        require(t.ndim == 2 and t.shape[1] == width and len(t) <= 16, "bounded history geometry")
    else:
        require(t.shape == (width,), "feature geometry mismatch")
    require(bool(torch.isfinite(t).all()), "nonfinite feature")
    return t


class GroupValueCell(nn.Module):
    """Shared stateful proposal-value estimator plus common stateless judge.

    The judge is the SAME learned output-selection rule for every control. It
    never sees the evaluator's labels during inference. It is not a proof checker.
    """
    def __init__(self, width, hidden=32):
        super().__init__()
        require(type(width) is int and 1 <= width <= 8192, "group input width")
        require(type(hidden) is int and 1 <= hidden <= 128, "bounded group state")
        self.width, self.hidden = width, hidden
        self.project = nn.Linear(width, hidden)
        self.memory = nn.GRUCell(hidden, hidden)
        self.proposal = nn.Linear(2 * hidden, 1)
        self.answer_value = nn.Linear(2 * hidden, 1)

    def initial(self):
        return self.project.weight.new_zeros(self.hidden)

    def advance(self, observed_feature, state):
        return self.memory(torch.tanh(self.project(observed_feature)), state)

    def predict(self, candidates, state):
        features = torch.tanh(self.project(candidates))
        states = state.unsqueeze(0).expand(len(candidates), -1)
        # A linear concatenation [state, candidate] only adds a common bias;
        # its ranking cannot depend on state. Multiplicative interactions are
        # essential here. Zero state preserves the unmodulated candidate path.
        modulated = features * (1.0 + torch.tanh(states))
        return torch.sigmoid(self.proposal(torch.cat((states, modulated), -1))).flatten()

    def judge(self, view, answer):
        features = torch.cat((torch.tanh(self.project(view)), torch.tanh(self.project(answer))), -1)
        return torch.sigmoid(self.answer_value(features)).squeeze(-1)


def fit_group(selected, examples, *, steps=128, learning_rate=0.001, seed=20261013):
    """Train a candidate from ACTUALLY observed, separately judged train traces.

    Targets are bounded external outcome scores, not this model's own values.
    The caller still owns outcome authenticity and training permission. Fitting
    observed traces does not identify unsupported counterfactual actions.
    """
    require(type(steps) is int and 1 <= steps <= 10000, "optimizer budget")
    require(c.finite(learning_rate, 1e-8, 0.1) and type(seed) is int and 0 <= seed < 2**63, "optimizer profile")
    require(isinstance(examples, list) and 1 <= len(examples) <= 16384, "training census")
    rows, ids = [], set()
    for r in examples:
        require(isinstance(r, dict) and set(r) == {"id", "split", "history", "view", "answer", "outcome", "outcome_receipt_sha256"}, "training row fields")
        require(r["split"] == "train" and c.text_id(r["id"]) and r["id"] not in ids, "evaluation/duplicate training row")
        require(c.sha(r["outcome_receipt_sha256"]) and c.finite(r["outcome"], 0, 1), "observed outcome required")
        ids.add(r["id"])
        rows.append((checked_tensor(r["history"], selected.width, matrix=True),
                     checked_tensor(r["view"], selected.width), checked_tensor(r["answer"], selected.width), float(r["outcome"])))
    before = parameters(selected)
    rng = random.Random(seed)
    with torch.inference_mode(False), torch.enable_grad(), measured() as cost:
        candidate = deepcopy(selected).train().requires_grad_(True)
        optimizer = torch.optim.SGD(candidate.parameters(), lr=learning_rate)
        losses = []
        for _ in range(steps):
            history, view, answer, outcome = rows[rng.randrange(len(rows))]
            optimizer.zero_grad(set_to_none=True)
            state = candidate.initial()
            for observation in history:
                state = candidate.advance(observation, state)
            proposal = candidate.predict(view.unsqueeze(0), state)[0]
            judged = candidate.judge(view, answer)
            loss = (proposal - outcome).square() + (judged - outcome).square()
            require(bool(torch.isfinite(loss)), "nonfinite group training loss")
            loss.backward()
            nn.utils.clip_grad_norm_(candidate.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            losses.append(float(loss.detach()))
        candidate.zero_grad(set_to_none=True)
    candidate.eval().requires_grad_(False)
    require(parameters(selected) == before, "training mutated selected controller")
    return candidate, {"profile": PROFILE, "architecture": ARCHITECTURE, "steps": steps, "examples": len(rows), "mean_loss": math.fsum(losses)/len(losses),
                       "selected": before, "candidate": parameters(candidate), "cost": cost,
                       "new_encoder_calls": 0, "new_reader_calls": 0, "optimizer_state_tensor_bytes": 0,
                       "independent_outcome_authenticity_verified": False, "general_fbsde": False,
                       "counterfactual_support_established": False, "production_authority": False}


def evidence_views(request):
    c.validate_public(request)
    require(all(e["modality"] == "text" for e in request["evidence"]), "Group profile is text-only")
    n = len(request["evidence"])
    require(1 <= n <= MENU["maximum_sources"], "requires 1..8 genuine evidence sources")
    groups = [()] + [(i,) for i in range(n)] + list(itertools.combinations(range(n), 2))
    return [{"question": request["question"], "options": list(request["options"]),
             "evidence": [deepcopy(request["evidence"][i]) for i in group]} for group in groups]


def choose_next(mode, available, predicted, incumbent, *, cost, threshold, seed, round_index, views):
    require(mode in MODES and available, "invalid control or exhausted menu")
    require(len(predicted) == len(available) and all(c.finite(v, 0, 1) for v in predicted), "invalid proposal values")
    require(c.finite(incumbent, 0, 1) and c.finite(cost, 0, 1) and c.finite(threshold, 0, 1), "value units/range")
    if mode == "fixed_search":
        return min(available, key=lambda i: (-len(views[i]["evidence"]), i))
    if mode == "independent_attempts":
        return min(available, key=lambda i: c.digest([seed, i]))
    if mode == "threshold_rule" and incumbent >= threshold:
        return None
    values = list(predicted)
    if mode == "shuffled_utility" and len(values) > 1:
        # A deterministic nonidentity permutation of the SAME predicted values.
        # It changes neither observed labels nor the common output judge.
        shift = 1 + int(c.digest([seed, round_index])[:8], 16) % (len(values) - 1)
        values = values[shift:] + values[:shift]
    best = max(range(len(available)), key=lambda j: (values[j], -available[j]))
    if mode in ("ndu_allocation", "shuffled_utility") and values[best] - incumbent <= cost:
        return None
    return available[best]


def search_views(request, controller, encode, read, *, mode, maximum_calls, call_cost, threshold, seed, deadline, emit):
    """Bounded real-action loop; encode/read are the existing model-owner ports.

    Every arm first pays one empty-evidence Reader call. All select the final
    unmodified answer using the same frozen stateless answer-value readout.
    No best-of-external-label, gold-conditioned policy or hidden model retry.
    """
    require(mode in MODES and type(maximum_calls) is int and 1 <= maximum_calls <= 8, "control/call budget")
    require(c.finite(call_cost, 0, 1) and c.finite(threshold, 0, 1), "utility profile")
    require(c.finite(deadline) and type(seed) is int, "clock/seed profile")
    views = evidence_views(request)
    require(time.perf_counter() < deadline, "deadline before feature preparation")
    features = encode([public_text(v) for v in views])
    require(isinstance(features, torch.Tensor) and features.shape == (len(views), controller.width)
            and features.dtype == torch.float32 and features.device.type == "cpu"
            and bool(torch.isfinite(features).all()), "view feature mismatch")
    require(time.perf_counter() < deadline, "deadline during feature preparation")
    state = controller.initial()
    available, trace = list(range(1, len(views))), []
    incumbent, incumbent_value = None, 0.0
    action, stop_reason = 0, "call_budget"
    before = parameters(controller)
    recurrent = mode not in ("stateless", "independent_attempts", "fixed_search")
    with torch.no_grad():
        for step in range(maximum_calls):
            require(time.perf_counter() < deadline, "deadline before Reader dispatch")
            event = {"event": "reader_started", "step": step, "view": action, "public_request_sha256": c.digest(views[action])}
            emit(event)
            try:
                response = read(views[action])
                require(isinstance(response, dict) and isinstance(response.get("answer"), str)
                        and bool(response["answer"].strip()), "Reader returned no answer")
                # Encode the actual raw answer, never external scoring labels.
                observed = encode([c.canonical({"question": request["question"], "answer": response["answer"]}).decode("utf-8")])
                require(isinstance(observed, torch.Tensor) and observed.shape == (1, controller.width)
                        and observed.dtype == torch.float32 and observed.device.type == "cpu"
                        and bool(torch.isfinite(observed).all()), "answer feature mismatch")
                quality = float(controller.judge(features[action], observed[0]))
                require(c.finite(quality, 0, 1), "nonfinite common judge")
                if recurrent:
                    state = controller.advance((features[action] + observed[0]) * 0.5, state)
                    require(bool(torch.isfinite(state).all()), "nonfinite recurrent state")
                finished = {"event": "reader_finished", "step": step, "view": action,
                            "response": response, "predicted_quality": quality,
                            "quality_is_independent_truth": False, "over_deadline": time.perf_counter() >= deadline}
                emit(finished)
                trace.append(finished)
                require(time.perf_counter() < deadline, "deadline after Reader dispatch")
            except Exception as error:
                emit({"event": "reader_failed_or_unknown", "step": step, "view": action,
                      "error_type": type(error).__name__, "error": str(error)[:512], "retry_permitted": False})
                raise
            if incumbent is None or quality > incumbent_value:
                incumbent, incumbent_value = finished, quality
            if step + 1 == maximum_calls:
                break
            if not available:
                stop_reason = "menu_exhausted"
                break
            # Stateless controls receive zero state; every candidate comes from
            # exactly the same menu. Parameters never change within the run.
            prediction_state = state if recurrent else controller.initial()
            values = controller.predict(features[available], prediction_state).tolist()
            action = choose_next(mode, available, values, incumbent_value, cost=call_cost,
                                 threshold=threshold, seed=seed, round_index=step, views=views)
            emit({"event": "computation_choice", "step": step, "available": list(available),
                  "predicted_quality": values, "selected": action, "incumbent_value": incumbent_value,
                  "registered_call_cost_in_utility_units": call_cost})
            if action is None:
                stop_reason = "estimated_value_stop" if mode != "threshold_rule" else "fixed_confidence_stop"
                break
            available.remove(action)
    require(parameters(controller) == before, "selected Group parameters changed")
    return {"answer": incumbent["response"]["answer"], "selected_view": incumbent["view"],
            "selected_evidence_ids": [e["id"] for e in views[incumbent["view"]]["evidence"]],
            "reader_requests": len(trace), "maximum_reader_requests": maximum_calls,
            "stop_reason": stop_reason, "controller_parameters": before,
            "selection_criterion": "same_frozen_learned_judge_not_external_answers",
            "profile": PROFILE, "architecture": ARCHITECTURE, "general_fbsde": False, "reasoning_gain_established": False}


class NativeGroupOwner:
    """One frozen Encoder, Reader and controller per scoped research owner.

    Uses the existing LocalEncoder/NativeSession implementations. No new service,
    no copied 421M per search node, and no source-entitlement authority.
    """
    def __init__(self, root, descriptor_sha):
        self.root, self.closed = Path(root).resolve(), False
        path = c.source_file(self.root, f"bundles/{descriptor_sha}.json", descriptor_sha)
        self.spec = c.load(path)
        s = self.spec
        require(s.get("schema") == SCHEMA and s.get("profile") == PROFILE, "Group descriptor schema/profile")
        require(all(c.text_id(s.get(k)) for k in ("scope", "purpose", "generation")), "Group scope binding")
        require(s.get("menu") == MENU and c.sha(s.get("reader_checkpoint_sha256")), "Group menu/Reader binding")
        require(type(s.get("maximum_reader_calls")) is int and 1 <= s["maximum_reader_calls"] <= 8, "Group Reader cap")
        require(c.finite(s.get("call_cost"), 0, 1) and c.finite(s.get("confidence_threshold"), 0, 1), "Group value units")
        b = s.get("bindings")
        require(isinstance(b, dict) and set(b) == set(c.BINDINGS) and all(c.sha(v) for v in b.values()), "Group bindings")
        require(b["action_menu"] == c.digest(MENU) and b["preprocessor"] == c.digest(PREPROCESSOR), "Group menu/preprocessor drift")
        weights = s["controller"]
        require(weights.get("architecture") == ARCHITECTURE, "unregistered Group architecture; do not reinterpret old tensors")
        require(c.sha(weights.get("training_receipt_sha256")) and c.sha(weights.get("calibration_receipt_sha256")), "Group training/calibration lineage")
        require(b["verifier"] == c.digest({"controller_sha256": weights["sha256"], "profile": "common-stateless-answer-judge-v1"}), "Group verifier drift")
        source = c.source_file(self.root, weights["path"], weights["sha256"])
        with torch.random.fork_rng(devices=[]):
            controller = GroupValueCell(weights["width"], weights["hidden"])
        controller.load_state_dict(load_file(str(source), device="cpu"), strict=True)
        require(all(bool(torch.isfinite(t).all()) for t in controller.state_dict().values()), "nonfinite controller checkpoint")
        self.controller = controller.eval().requires_grad_(False)
        self.native = NativeSession(self.root, cache_bytes=0)
        reader = self.native.descriptor(s["reader_checkpoint_sha256"])
        require(reader["kind"] == "reader" and reader["sharing"] == "shared" and reader["bindings"] == b, "Group Reader descriptor differs")
        require(all(reader[k] == s[k] for k in ("scope", "purpose", "generation")), "cross-scope Group Reader")
        enc = s["encoder"]
        relative = Path(enc["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "Group encoder path")
        require(b["encoder"] == c.digest(enc["snapshot"]), "Group Encoder identity")
        with measured() as load_cost:
            self.encoder = LocalEncoder(self.root / relative, enc["snapshot"], enc["maximum_tokens"])
        require(self.encoder.simulated is False, "synthetic Group Encoder forbidden")
        self.load_cost = load_cost
        self.encoder_calls = 0
        self.encoder_batches = []
        self.last_run_cost = None

    def encode(self, texts, *, deadline=None):
        """Preserve all ordered views within the EXISTING physical batch caps.

        Eight sources produce 37 views, exceeding LocalEncoder's 32-item cap.
        Chunk size also respects its 32768 padded-token cap at the configured
        maximum length. No dropped views, truncation, retry or partial return.
        """
        require(not self.closed, "closed Group owner")
        require(isinstance(texts, list) and 1 <= len(texts) <= 37
                and all(isinstance(t, str) and t for t in texts), "bounded Group text census")
        maximum = self.encoder.maximum_tokens
        require(type(maximum) is int and 8 <= maximum <= 8192, "Encoder token ceiling")
        require(deadline is None or c.finite(deadline), "invalid encoding deadline")
        limit = min(32, 32768 // maximum)
        chunks = []
        for offset in range(0, len(texts), limit):
            require(deadline is None or time.perf_counter() < deadline, "deadline before Encoder chunk")
            part = texts[offset:offset+limit]
            row = {"offset": offset, "items": len(part), "public_texts_sha256": c.digest(part),
                   "status": "failed", "execution_profile": ENCODING_EXECUTION}
            with measured() as cost, count_forwards(self.encoder.model) as calls:
                try:
                    value = self.encoder.encode(part)
                    require(isinstance(value, torch.Tensor) and value.shape == (len(part), self.controller.width)
                            and value.dtype == torch.float32 and value.device.type == "cpu"
                            and bool(torch.isfinite(value).all()), "invalid Encoder chunk output")
                    require(deadline is None or time.perf_counter() < deadline, "deadline after Encoder chunk")
                    chunks.append(value.detach().clone())
                    row["status"] = "succeeded"
                except Exception as error:
                    row["error"] = type(error).__name__ + ": " + str(error)[:512]
                    raise
                finally:
                    self.encoder_calls += calls["model_calls"]
                    row["actual_forwards"] = calls["model_calls"]
                    # cost is finalized by the context manager on both paths.
                    row["cost"] = cost
                    self.encoder_batches.append(row)
        return torch.cat(chunks, dim=0)

    def run(self, request, *, mode, timeout, emit):
        require(not self.closed and c.finite(timeout, .01, 3600), "closed owner/timeout")
        started, enc_before = time.perf_counter(), self.encoder_calls
        calls_before, batches_before = len(self.native.observations), len(self.encoder_batches)
        reader_attempts = reader_errors = 0
        deadline = started + timeout
        self.last_run_cost = None
        def read(view):
            nonlocal reader_attempts, reader_errors
            require(time.perf_counter() < deadline, "deadline before native Reader")
            reader_attempts += 1
            try:
                return self.native.answer({"request": view, "checkpoint_sha256": self.spec["reader_checkpoint_sha256"],
                                           "bindings": self.spec["bindings"], "timeout_seconds": min(3600, max(.01, deadline-time.perf_counter()))},
                                          arm="group-shared-reader")
            except Exception:
                reader_errors += 1
                raise
        try:
            result = search_views(request, self.controller, lambda texts: self.encode(texts, deadline=deadline), read, mode=mode,
                                  maximum_calls=self.spec["maximum_reader_calls"], call_cost=self.spec["call_cost"],
                                  threshold=self.spec["confidence_threshold"], seed=int(c.digest(request)[:8], 16),
                                  deadline=deadline, emit=emit)
        finally:
            observations = self.native.observations[calls_before:]
            known = sum(x["model_calls"] for x in observations)
            # NativeSession may fail after a forward before recording a result.
            # The missing portion remains unknown, not silently imputed to zero.
            self.last_run_cost = {"wall_seconds": time.perf_counter()-started,
                "encoder_forwards": self.encoder_calls-enc_before,
                "encoder_batches": deepcopy(self.encoder_batches[batches_before:]),
                "reader_requests_attempted": reader_attempts, "reader_requests_failed": reader_errors,
                "reader_forwards": known if reader_errors == 0 else None,
                "reader_forwards_known_lower_bound": known,
                "reader_resource_rows": deepcopy(observations), "encoding_execution": ENCODING_EXECUTION,
                "energy_joules": None, "active_flops": None}
        result["measured"] = self.last_run_cost
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.encoder.close()
            self.native.close()
        finally:
            self.native.models.clear()
            self.native.heads.clear()
            self.native.cache.clear()


def run_registered(bundle, review, reader_review, root, output, experiment):
    require(experiment in ("system2", "ndu"), "Group runner only implements E3/E4")
    import os
    rows = admit_stage(bundle, review, os.environ.get("HEPTA_FIVE_EXPERIMENT_REVIEW_SHA256"), experiment,
                       reader_review, os.environ.get("HEPTA_FIVE_READER_REVIEW_SHA256"))
    c.check_materials(bundle, root, experiment)
    source_sha = c.file_sha(Path(__file__))
    require(all(r["implementation_sha256"] == source_sha for r in rows), "Group running-source identity mismatch")
    # One descriptor per task across all controls: same trained cell, Reader,
    # Encoder, verifier, cost profile and call cap, not model swaps by arm.
    descriptors = {}
    for r in rows:
        require(r["task_id"] not in descriptors or descriptors[r["task_id"]] == r["checkpoint_sha256"], "Group control checkpoint mismatch")
        descriptors[r["task_id"]] = r["checkpoint_sha256"]
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "frozen-bundle.json", bundle)
    previous, failures = "0" * 64, 0
    with (output / "raw-journal.jsonl").open("xb") as journal:
        for r in sorted(rows, key=lambda x: c.digest([c.PROTOCOL["bootstrap_seed"], x["trial_id"]])):
            packet = {k: r[k] for k in ("request", "checkpoint_sha256", "bindings", "timeout_seconds")}
            request_sha = c.digest(packet)
            previous = c.journal_append(journal, {"event": "started", "trial_id": r["trial_id"], "request_sha256": request_sha}, previous)
            owner, record, started = None, {"event": "finished", "trial_id": r["trial_id"], "request_sha256": request_sha,
                                           "status": "failed", "result": None}, time.perf_counter()
            trace_path = None
            try:
                owner = NativeGroupOwner(root, r["checkpoint_sha256"])
                require(owner.spec["bindings"] == r["bindings"], "registered Group bindings differ")
                remaining = r["timeout_seconds"] - (time.perf_counter()-started)
                require(remaining >= .01, "deadline during Group loading")
                trace_path = output / (c.digest(r["trial_id"]) + "-actions.jsonl")
                with trace_path.open("xb") as stream:
                    tail = "0" * 64
                    def emit(event):
                        nonlocal tail
                        tail = c.journal_append(stream, event, tail)
                    result = owner.run(r["request"], mode=r["arm"], timeout=remaining, emit=emit)
                counters = result["measured"]
                record["result"] = {"request_sha256": request_sha, "answer": result["answer"],
                                    "resources": {"active_flops": None, "energy_joules": None, "peak_memory_bytes": None,
                                                  "model_calls": counters["encoder_forwards"]+counters["reader_forwards"]}}
                record["action_trace_sha256"] = c.file_sha(trace_path)
                record["group_result"] = result
                record["load_cost"] = owner.load_cost
                record["status"] = "succeeded"
            except Exception as error:
                record["error"] = type(error).__name__ + ": " + str(error)[:1024]
                record["partial_compute_is_zero"] = False
            finally:
                if owner is not None:
                    record["observed_group_cost"] = owner.last_run_cost
                    record["load_cost"] = owner.load_cost
                    try:
                        owner.close()
                    except Exception as error:
                        record["cleanup_error"] = type(error).__name__ + ": " + str(error)[:512]
                        record["status"] = "failed"
                if trace_path is not None and trace_path.is_file():
                    record["action_trace_sha256"] = c.file_sha(trace_path)
                record["wall_seconds_including_process_start"] = time.perf_counter()-started
                if record["wall_seconds_including_process_start"] > r["timeout_seconds"]:
                    record["status"] = "timeout"
                if record["status"] != "succeeded":
                    record["result"] = None
                    failures += 1
                previous = c.journal_append(journal, record, previous)
    c.check_materials(bundle, root, experiment)
    receipt = {"schema": "hepta.five-group.execution.v1", "bundle_sha256": c.digest(bundle), "experiment": experiment,
               "planned": len(rows), "failed": failures, "raw_sha256": c.file_sha(output / "raw-journal.jsonl"),
               "profile": PROFILE, "architecture": ARCHITECTURE, "encoding_execution": ENCODING_EXECUTION,
               "model_loads_included_in_wall_time": True,
               "shared_across_nodes_not_across_control_trials": True, "same_budget_is_not_matched_compute": True,
               "hard_kernel_preemption": False, "general_fbsde": False, "production_authority": False}
    c.write_new(output / "execution-receipt.json", receipt)
    return receipt


def train_plan(plan, output):
    require(plan.get("schema") == "hepta.five-group.training.v1" and plan.get("data_kind") in ("approved_training", "historical_development"), "Group training schema/data")
    require(c.sha(plan.get("dataset_sha256")) and c.sha(plan.get("encoder_snapshot_sha256")), "training data/Encoder identity")
    require(c.digest(plan["examples"]) == plan["dataset_sha256"], "training examples hash mismatch")
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "frozen-training-plan.json", plan)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(plan["seed"])
        selected = GroupValueCell(plan["width"], plan["hidden"]).eval().requires_grad_(False)
    candidate, receipt = fit_group(selected, plan["examples"], steps=plan["steps"],
                                    learning_rate=plan["learning_rate"], seed=plan["seed"])
    path = output / "group.safetensors"
    save_file({k: v.detach().contiguous() for k, v in candidate.state_dict().items()}, str(path))
    restored = deepcopy(candidate)
    restored.load_state_dict(load_file(str(path)), strict=True)
    require(parameters(restored) == parameters(candidate), "Group checkpoint reload mismatch")
    receipt.update(checkpoint_sha256=c.file_sha(path), encoder_snapshot_sha256=plan["encoder_snapshot_sha256"],
                   dataset_sha256=plan["dataset_sha256"], reload_verified=True)
    c.write_new(output / "training-receipt.json", receipt)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("train", "run"))
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--root", type=Path)
    p.add_argument("--review", type=Path)
    p.add_argument("--reader-review", type=Path)
    p.add_argument("--experiment", choices=("system2", "ndu"))
    args = p.parse_args()
    if args.mode == "train":
        train_plan(c.load(args.plan), args.output)
        return 0
    require(all(x is not None for x in (args.root, args.review, args.reader_review, args.experiment)), "registered Group execution inputs missing")
    report = run_registered(c.load(args.plan), c.load(args.review), c.load(args.reader_review),
                            args.root, args.output, args.experiment)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
