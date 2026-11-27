"""One frozen public CPU experiment. Every complete model rollout goes through Ledger."""
import time
COLD_START = time.monotonic()

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np

from static_support import Ledger, choose, eligible, exact_norm2, metrics, sha, write_json

HERE = Path(__file__).resolve().parent


def source_identity():
    return {p.name: sha(p.read_bytes()) for p in sorted(HERE.iterdir()) if p.suffix in (".py", ".json")}


def gradient_qualification(adapter, data, output, ledger):
    import torch
    from model_adapter import take
    first = take(data, np.arange(2))
    direction = np.random.default_rng(20261127).choice(np.array([-1., 1.]), 40)
    parent = adapter.parent.copy()
    plus = (parent.astype(np.float64) + 2. ** -8 * direction).astype("<f4")
    minus = (parent.astype(np.float64) - 2. ** -8 * direction).astype("<f4")
    if exact_norm2(plus, parent) > 1 or exact_norm2(minus, parent) > 1:
        raise ValueError("fixed gradient witness exceeds sender radius")
    try:
        adapter.model.zero_grad(set_to_none=True)
        scores, trace, _ = adapter.run(first, "QUAL_PARENT_2", gradient=True, compile_trace=True)
        loss = torch.nn.functional.cross_entropy(scores.to(torch.float64), torch.from_numpy(first["y"]))
        ledger.backward(loss)
        grads = np.concatenate((adapter.model.body.input_drive.weight.grad.detach().numpy().reshape(-1),
                                adapter.model.body.input_drive.bias.grad.detach().numpy())).astype("<f4")
        if not np.isfinite(grads).all() or not np.linalg.norm(grads.astype(np.float64)):
            raise ValueError("fixed first-order qualification has no finite nonzero gradient")
        losses = []
        witness_scores = []
        for label, theta in (("QUAL_PLUS_2", plus), ("QUAL_MINUS_2", minus)):
            adapter.set_theta(theta)
            predicted, _, _ = adapter.run(first, label)
            witness_scores.append(predicted.detach().numpy().copy())
            losses.append(float(torch.nn.functional.cross_entropy(predicted.to(torch.float64), torch.from_numpy(first["y"]))))
        observed = losses[0] - losses[1]
        predicted = float(grads.astype(np.float64) @ (plus.astype(np.float64) - minus.astype(np.float64)))
        tolerance = 1e-5 + .1 * max(abs(observed), abs(predicted))
        report = dict(observed_loss_difference=observed, predicted_gradient_difference=predicted,
                      absolute_error=abs(observed - predicted), tolerance=tolerance,
                      passed=abs(observed - predicted) <= tolerance, epsilon_tuning=False,
                      gradient_norm=float(np.linalg.norm(grads.astype(np.float64))), full_jacobian_verified=False)
        np.savez_compressed(output / "gradient_witness.npz", parent=parent, plus=plus, minus=minus,
                            gradient=grads, parent_scores=scores.detach().numpy(),
                            plus_scores=witness_scores[0], minus_scores=witness_scores[1])
        write_json(output / "GRADIENT_QUALIFICATION.json", report)
        if not report["passed"]:
            raise ValueError("single frozen finite-difference qualification failed; no epsilon retuning")
        return scores.detach().numpy().copy(), trace
    finally:
        adapter.set_theta(parent)
        adapter.model.zero_grad(set_to_none=True)


def compare_parent(first_scores, first_trace, train_scores, train_trace, retained, data, prepared, manifest):
    feature_error = float(np.abs(first_trace["receiver_features"].astype(np.float64) -
                                 train_trace["receiver_features"][:, :4].astype(np.float64)).max())
    score_error = float(np.abs(first_scores.astype(np.float64) - train_scores[:2].astype(np.float64)).max())
    if feature_error > 8e-6 or score_error > 2e-5 or (first_scores.argmax(1) != train_scores[:2].argmax(1)).any():
        raise ValueError("budgeted two-query and eighty-query parent executions disagree")
    raw_golden = (prepared / "golden_retain.json").read_bytes()
    if sha(raw_golden) != manifest["golden_retain_export"]["sha256"] or len(raw_golden) != manifest["golden_retain_export"]["bytes"]:
        raise ValueError("public historical retained witness file changed")
    original = json.loads(raw_golden)
    indices = [i for i in range(32) if i not in [4, 5, 6, 7]]
    if [original["labels"][i] for i in indices] != data["y"].tolist() or [original["groups"][i] for i in indices] != data["groups"].tolist():
        raise ValueError("public historical retained query labels/groups differ")
    margins = retained[:, 1] - retained[:, 0]
    golden = np.array([original["margins"][i] for i in indices], dtype=np.float64)
    baseline = data["baseline"][:, 1] - data["baseline"][:, 0]
    golden_base = np.array([original["baseline_margins"][i] for i in indices], dtype=np.float64)
    historical_error = float(np.abs(margins.astype(np.float64) - golden).max())
    baseline_error = float(np.abs(baseline.astype(np.float64) - golden_base).max())
    if historical_error > 2e-5 or baseline_error > 2e-5 or ((golden > 0).astype("int64") != retained.argmax(1)).any():
        raise ValueError("fixed public historical retained witness parity failed")
    return dict(two_vs_eighty_feature_error=feature_error, two_vs_eighty_score_error=score_error,
                public_retained_margin_error=historical_error, public_baseline_margin_error=baseline_error,
                decision_disagreements=0, new_holdout=False, extra_forwards=0)


def main():
    prepared, output = (Path(value).resolve() for value in sys.argv[1:3])
    output.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(output, COLD_START)
    before = source_identity()
    write_json(output / "SOURCE_BEFORE.json", before)
    manifest = json.loads((HERE / "public_inputs.json").read_text())
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    adapter = None
    failure = None
    evaluations = []
    result = dict(schema="hepta.sender40-public-cpu-result.v1", native_owner_executed=False,
                  production_eligible=False, new_confirmation_queries=0, old_test_calls=0,
                  general_capability_claim=False, dependency_setup_cost_in_separate_receipt=True)
    try:
        if (protocol["parent_seed"] != 47 or protocol["bp"]["steps"] != 16 or
                protocol["radius"]["recommended_global_absolute_frobenius"] != 1):
            raise ValueError("declarative and executable protocol disagree")
        receipt = json.loads((prepared / "PREPARED.json").read_text())
        if (receipt["input_manifest_sha256"] != sha((HERE / "public_inputs.json").read_bytes()) or
                receipt["golden_retain_sha256"] != manifest["golden_retain_export"]["sha256"]):
            raise ValueError("public preparation receipt and current input commitments differ")
        import torch
        from candidates import NAMES, generate
        from model_adapter import Adapter, combine, load_data
        versions = {name: importlib.metadata.version(name) for name in ("torch", "numpy", "scipy")}
        if versions != {"torch": "2.10.0+cpu", "numpy": "2.3.5", "scipy": "1.17.0"}:
            raise ValueError("CPU package versions differ from the frozen public lane")
        if sys.version_info[:3] != (3, 12, 3) or sys.byteorder != "little" or platform.machine() != "x86_64":
            raise ValueError("unqualified CPU interpreter/platform")
        if any(os.environ.get(key) != "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("single numerical thread contract missing")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        data = load_data(prepared, manifest)
        adapter = Adapter(prepared, manifest, ledger)
        write_json(output / "RUN_IDENTITY.json", dict(versions=versions, python=sys.version,
                   parent_checkpoint_sha256=manifest["checkpoint"]["sha256"], profile=adapter.profile,
                   actual_loaded_original_sources=adapter.loaded_sources,
                   protocol_sha256=sha((HERE / "PROTOCOL.json").read_bytes()),
                   public_inputs_sha256=sha((HERE / "public_inputs.json").read_bytes()),
                   source_commit=manifest["source_commit"], numerical_threads=1, device="cpu"))
        first, first_trace = gradient_qualification(adapter, data["train"], output, ledger)
        train_tensor, train_trace, _ = adapter.run(data["train"], "KEEP_TRAIN_80", compile_trace=True)
        train_scores = train_tensor.detach().numpy().copy()
        combined = combine(data["dev"], data["retain"])
        held_tensor, _, _ = adapter.run(combined, "KEEP_DEV32_RETAIN28")
        held = held_tensor.detach().numpy().copy()
        parity = compare_parent(first, first_trace, train_scores, train_trace, held[32:], data["retain"], prepared, manifest)
        write_json(output / "CPU_PRODUCER_QUALIFICATION.json", dict(passed=True, **parity))
        baseline_arrays = dict(train_scores=train_scores, dev_scores=held[:32], retain_scores=held[32:])
        for split in ("train", "dev", "retain"):
            for field in ("y", "query_id", "gallery_id", "groups"):
                baseline_arrays[split + "_" + field] = data[split][field]
        np.savez_compressed(output / "BASELINE_SCORES.npz", **baseline_arrays)
        baseline_sha = sha((output / "BASELINE_SCORES.npz").read_bytes())
        write_json(output / "BASELINE_SCORES_SEAL.json", dict(sha256=baseline_sha,
                   scores_dtype="F32 actual output bits", counts=dict(train=80, dev=32, retain=28),
                   source="existing budgeted KEEP evaluations", extra_model_calls=0))
        parent_correct = train_scores.argmax(1) == data["train"]["y"]
        bindings = {name: data["train"][name].tolist() for name in ("query_id", "gallery_id", "groups")}
        write_json(output / "query_bindings.json", bindings)
        np.savez_compressed(output / "baseline_train_trace.npz", **train_trace,
                            slow_ticks=np.array([0, 2, 4]), y=data["train"]["y"],
                            parent_correct=parent_correct, query_groups=data["train"]["groups"],
                            query_id=data["train"]["query_id"], gallery_id=data["train"]["gallery_id"],
                            parent_scores=train_scores)
        write_json(output / "baseline_train_trace.meta.json", dict(
            schema="hepta.sender40-original-training-trace.v1", source_commit=manifest["source_commit"],
            archive_sources=manifest["inputs"], original_python_sources=[v for v in manifest["payload_members"] if v["path"].endswith(".py")],
            parent_checkpoint_sha256=manifest["checkpoint"]["sha256"], normalizer_sha256=manifest["normalizer_sha256"],
            train_npz_sha256=next(v["sha256"] for v in manifest["payload_members"] if v["path"] == "data/train.npz"),
            query_bindings_sha256=sha((output / "query_bindings.json").read_bytes()),
            trace_sha256=sha((output / "baseline_train_trace.npz").read_bytes()),
            baseline_scores_sha256=baseline_sha,
            array_layout="slow_tick, query-major choice0/choice1, sender or feature dimension",
            source_drift_cost_bits_reproduced=True, original_flow_called_once_per_tick=True,
            query_and_gallery_actor_equal_group=True, parent_correct_selection_is_supervised=True,
            source_adapter_sha256=before["model_adapter.py"], profile=adapter.profile))
        shared_cost = dict(wall_seconds=time.monotonic() - COLD_START, cpu_seconds=time.process_time(),
                           counts=dict(ledger.counts), includes="imports/init/qualification/KEEP/raw trace and supervised P selection",
                           counted_once_in_actual_experiment=True, dependency_setup_and_public_download_excluded=True)
        write_json(output / "shared_cold_cost.json", shared_cost)
        records, vectors, _ = generate(adapter, data["train"], train_trace, train_scores, output, ledger)
        keep = dict(name="KEEP", norm=0., declaration_index=0, protection_passed=True,
                    train=metrics(train_scores, data["train"]["y"]), dev=metrics(held[:32], data["dev"]["y"]),
                    retain=metrics(held[32:], data["retain"]["y"]))
        evaluations = [keep]
        for index, name in enumerate(NAMES, 1):
            eval_start, eval_cpu = time.monotonic(), time.process_time()
            ledger.event("candidate_evaluation_started", candidate=name)
            raw = (output / name).with_suffix(".f32le").read_bytes()
            if sha(raw) != records[name]["parameter_sha256"] or raw != vectors[name].tobytes():
                raise ValueError("candidate changed after the six-way seal")
            adapter.load_candidate((output / name).with_suffix(".pt"), records[name]["checkpoint_sha256"],
                                   np.frombuffer(raw, dtype="<f4").copy())
            tr, trace, _ = adapter.run(data["train"], name + "_TRAIN_80")
            dv, _, _ = adapter.run(combined, name + "_DEV32_RETAIN28")
            tr, dv = tr.detach().numpy().copy(), dv.detach().numpy().copy()
            np.savez_compressed(output / (name + ".evaluation.npz"), train_scores=tr, dev_scores=dv[:32],
                                retained_scores=dv[32:], **trace)
            row = dict(name=name, norm=records[name]["norm"], declaration_index=index,
                       train=metrics(tr, data["train"]["y"]), dev=metrics(dv[:32], data["dev"]["y"]),
                       retain=metrics(dv[32:], data["retain"]["y"]),
                       protection_passed=eligible(dv[32:], held[32:], data["retain"]["y"]),
                       parent_correct_to_wrong=int(((held[32:].argmax(1) == data["retain"]["y"]) &
                                                   (dv[32:].argmax(1) != data["retain"]["y"])).sum()))
            adapter.set_theta(adapter.parent)
            row["evaluation_cost"] = dict(wall_seconds=time.monotonic() - eval_start,
                cpu_seconds=time.process_time() - eval_cpu, full_forwards=2, paired_queries=140,
                includes="actual checkpoint reload/two complete evaluations/metrics/NPZ serialization/restoration")
            write_json(output / (name + ".evaluation.json"), row)
            evaluations.append(row)
            ledger.event("candidate_evaluation_completed", candidate=name, cost=row["evaluation_cost"])
        selection = {}
        method_costs = {}
        for method in ("ANALYTIC_ROLE", "BP_TASK"):
            candidates = [row for row in evaluations if row["protection_passed"] and
                          (row["name"] == "KEEP" or row["name"].startswith(method + "_"))]
            winner = choose(candidates)
            signal = winner["dev"]["correct"] >= keep["dev"]["correct"] + 1 and winner["train"]["ce"] < keep["train"]["ce"]
            selection[method] = dict(selected=winner["name"], development_signal=signal,
                                     heldout_improvement_claim=False, cost_is_whole_two_candidate_method=True)
            fit_file = "analytic_cost.json" if method == "ANALYTIC_ROLE" else "bp_cost.json"
            fit_cost = json.loads((output / fit_file).read_text())
            evaluated = [row for row in evaluations if row["name"].startswith(method + "_")]
            evaluation_cost = {key: sum(row["evaluation_cost"][key] for row in evaluated)
                               for key in ("wall_seconds", "cpu_seconds", "full_forwards", "paired_queries")}
            phase_sum = {key: fit_cost[key] + evaluation_cost[key] for key in ("wall_seconds", "cpu_seconds")}
            method_costs[method] = dict(two_candidate_fit_compile=fit_cost,
                two_candidate_evaluation=evaluation_cost, exclusive_phase_sum=phase_sum,
                with_shared_cost_allocation={key: phase_sum[key] + shared_cost[key]
                                             for key in ("wall_seconds", "cpu_seconds")},
                independent_cold_method_run=False, speed_advantage_claim=False)
        write_json(output / "METHOD_COSTS.json", dict(shared_once=shared_cost, methods=method_costs,
                   interpretation="Observed phase costs; shared setup allocated separately to each comparison, not executed twice.",
                   controls_separate=True, dependency_setup_in_separate_receipt=True))
        expected_counts = dict(forwards=33, body_ticks=198, paired_queries=1114, backwards=17,
                               optimizer_steps=16, analytic_solves=2, trace_linear_replays=6)
        if ledger.counts != expected_counts:
            raise ValueError("completed execution does not match the exact frozen call ledger")
        ledger.check_time()
        result.update(status="COMPLETED", producer_qualification=parity, evaluations=evaluations, selection=selection,
                      method_costs=method_costs, shared_cost_once=shared_cost,
                      baseline_scores_sha256=baseline_sha,
                      fixed_candidate_order=list(NAMES), gradient_free_entire_experiment=False,
                      analytic_supervised_fit=True, quality_control_is_developmental=True)
    except BaseException as error:
        failure = error
        result.update(status="ABORTED", error=repr(error), partial_budget=True,
                      candidates_may_be_partial=True, retry_permitted=False,
                      completed_evaluations=evaluations)
        ledger.event("aborted", error=repr(error))
    finally:
        integrity_errors = []
        if adapter is not None:
            try:
                adapter.set_theta(adapter.parent)
                result["in_memory_parent_values_restored"] = adapter.theta().tobytes() == adapter.parent.tobytes()
            except BaseException as error:
                integrity_errors.append("parent restoration: " + repr(error))
        try:
            after = source_identity()
            write_json(output / "SOURCE_AFTER.json", after)
            result["source_unchanged"] = before == after
            if before != after:
                integrity_errors.append("source identity changed during experiment")
        except BaseException as error:
            integrity_errors.append("source readback: " + repr(error))
        try:
            result["original_parent_file_unchanged"] = sha((prepared / "parent.pt").read_bytes()) == manifest["checkpoint"]["sha256"]
            if not result["original_parent_file_unchanged"]:
                integrity_errors.append("original parent file identity changed")
        except BaseException as error:
            integrity_errors.append("parent file readback: " + repr(error))
        if integrity_errors:
            result.update(status="ABORTED", integrity_errors=integrity_errors, retry_permitted=False)
            if failure is None:
                failure = ValueError("; ".join(integrity_errors))
        result.update(counts=dict(ledger.counts), active_wall_seconds=time.monotonic() - COLD_START,
                      cpu_seconds=time.process_time())
        write_json(output / "RESULT.json", result)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
