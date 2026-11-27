"""Prepared, unexecuted public boundary-program extension. No implicit retry.

The mathematical program is the immutable, separately qualified v4 source.
Only a root-reviewed input binding can enable this entry point. All model
rollouts use the original public Hybrid through the pinned pilot Adapter.
"""
import time
COLD_START = time.monotonic()

from decimal import getcontext, ROUND_HALF_EVEN
from fractions import Fraction
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT_PIN = {
    "boundary_program.py": "ea36b3768b7617275947e6d955e4d3770c33a5700de9b649b938b642e7744dde",
    "boundary_inverse.py": "e6da84d80047492c2afb5d74faafd1be227cc7775d012a50167b035cfdec025a",
    "PREREGISTERED_TARGET_RULES_V2.json": "3f56e3384c516e8ec7dcf970e2a9d535ab32f437b7d690a85946f52d1497adc1",
}
PARENT_SHA = "92756ef7d5dc98d27cb305a9132eb03aca31487ceddaa09be7456457ed3df7dd"
SOURCE_COMMIT = "bc4912ea657864d33b36a57da0b50eb35bee90af"
NORMALIZER_SHA = "7e82bcff70d5d8b94f9096f66ef6b28a6eedfad12bc763214d5cca68e75b98b0"
NAMES = ("BOUNDARY_PROGRAM_025", "BOUNDARY_PROGRAM_100", "WRONG_BOUNDARY_ROLE", "MATCHED_RANDOM")
PRIOR_NAMES = ("ANALYTIC_ROLE_025", "ANALYTIC_ROLE_100", "BP_TASK_4", "BP_TASK_16", "WRONG_ROLE", "RANDOM")
CAPS = dict(forwards=8, body_ticks=48, paired_queries=560, backwards=0,
            optimizer_steps=0, analytic_solves=2, trace_linear_replays=12,
            scalar_inverse_targets=48, root_cells=196608, root_bisections=3840,
            root_interval_evaluations=196608, root_point_evaluations=397104)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def bound_file(directory, name, binding):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()) or Path(name).is_absolute():
        raise ValueError("bound file escapes its input directory")
    expected = binding[name]
    raw = path.read_bytes()
    if len(raw) != expected["bytes"] or sha(raw) != expected["sha256"]:
        raise ValueError("bound input identity changed: " + name)
    return raw


def bind_sources(binding, helper):
    if binding.get("status") != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW":
        raise ValueError("input template is not an executable reviewed binding")
    if not re.fullmatch(r"[0-9a-f]{64}", binding.get("root_review_sha256", "")):
        raise ValueError("root review identity missing")
    if (binding.get("parent_checkpoint_sha256") != PARENT_SHA or
            binding.get("source_commit") != SOURCE_COMMIT or
            binding.get("normalizer_sha256") != NORMALIZER_SHA):
        raise ValueError("public parent/source/normalizer scope changed")
    for name, expected in ROOT_PIN.items():
        if sha((HERE / name).read_bytes()) != expected:
            raise ValueError("immutable v4 source changed: " + name)
    for name in ("static_support.py", "model_adapter.py", "candidates.py", "public_inputs.json", "PROTOCOL.json"):
        bound_file(helper, name, binding["helper_files"])
    for name in ("runner.py", "supervise.py", "prepare_evidence.py", "fetch_predecessor.py", "IDENTITY_AMENDMENT.json"):
        if sha((HERE / name).read_bytes()) != binding["adapter_source_sha256"][name]:
            raise ValueError("reviewed execution adapter changed: " + name)
    manifest = json.loads((helper / "public_inputs.json").read_text())
    profile_bytes = json.dumps(manifest["tensor_profile"], sort_keys=True, separators=(",", ":")).encode()
    if sha(profile_bytes) != binding["public_tensor_profile_sha256"]:
        raise ValueError("public registered tensor/buffer profile differs")
    if (manifest["checkpoint"]["sha256"] != PARENT_SHA or
            manifest["source_commit"] != SOURCE_COMMIT or
            manifest["normalizer_sha256"] != NORMALIZER_SHA or
            manifest["visibility"] != "PUBLIC"):
        raise ValueError("fixed public input manifest scope changed")
    return manifest


def same_array(actual, expected, label):
    import numpy as np
    if actual.dtype != expected.dtype or actual.shape != expected.shape or not np.array_equal(actual, expected):
        raise ValueError("bound baseline/data mismatch: " + label)


def load_train_trace(evidence, files, data, manifest, helper_sha):
    import numpy as np
    raw = bound_file(evidence, "baseline_train_trace.meta.json", files)
    meta = json.loads(raw)
    if (meta["parent_checkpoint_sha256"] != PARENT_SHA or meta["source_commit"] != SOURCE_COMMIT or
            meta["normalizer_sha256"] != NORMALIZER_SHA or
            meta["source_adapter_sha256"] != helper_sha or
            meta["trace_sha256"] != files["baseline_train_trace.npz"]["sha256"] or
            meta["profile"] != manifest["qualified_profile"]):
        raise ValueError("actual predecessor trace source/profile binding differs")
    bound_file(evidence, "baseline_train_trace.npz", files)
    with np.load(evidence / "baseline_train_trace.npz", allow_pickle=False) as archive:
        trace = {key: archive[key].copy() for key in archive.files}
    for key, expected in (("y", data["y"]), ("query_groups", data["groups"]),
                          ("query_id", data["query_id"]), ("gallery_id", data["gallery_id"])):
        same_array(trace[key], expected, key)
    if trace["parent_scores"].dtype != np.dtype("float32") or trace["parent_scores"].shape != (80, 2):
        raise ValueError("actual predecessor parent score schema")
    if not np.isfinite(trace["parent_scores"]).all():
        raise ValueError("nonfinite predecessor train scores")
    same_array(trace["parent_correct"], trace["parent_scores"].argmax(1) == data["y"], "correct training mask")
    if not meta["source_drift_cost_bits_reproduced"] or not meta["original_flow_called_once_per_tick"]:
        raise ValueError("predecessor trace lacks qualified original graph evidence")
    return trace, meta


def predecessor_admission(evidence, files):
    """Use only completed-call/source/qualification facts, never quality to fit."""
    previous = json.loads(bound_file(evidence, "RESULT.json", files))
    expected = dict(forwards=33, body_ticks=198, paired_queries=1114, backwards=17,
                    optimizer_steps=16, analytic_solves=2, trace_linear_replays=6)
    if (previous["status"] != "COMPLETED" or previous["counts"] != expected or
            not previous["source_unchanged"] or not previous["original_parent_file_unchanged"]):
        raise ValueError("predecessor did not complete the fixed qualified public experiment")
    for filename in ("GRADIENT_QUALIFICATION.json", "CPU_PRODUCER_QUALIFICATION.json"):
        if not json.loads(bound_file(evidence, filename, files))["passed"]:
            raise ValueError("predecessor qualification failed: " + filename)
    return {key: previous[key] for key in ("counts", "cpu_seconds", "active_wall_seconds")}


def frozen_baselines(evidence, files, data, trace):
    """Read held baseline arrays only after the four candidate byte seal."""
    import numpy as np
    bound_file(evidence, "BASELINE_SCORES.npz", files)
    answer = {}
    with np.load(evidence / "BASELINE_SCORES.npz", allow_pickle=False) as archive:
        for split, n in (("train", 80), ("dev", 32), ("retain", 28)):
            for field in ("y", "query_id", "gallery_id", "groups"):
                same_array(archive[split + "_" + field], data[split][field], split + "_" + field)
            values = archive[split + "_scores"].copy()
            if values.dtype != np.dtype("float32") or values.shape != (n, 2) or not np.isfinite(values).all():
                raise ValueError("predecessor baseline score type/shape/domain")
            answer[split] = values
    same_array(answer["train"], trace["parent_scores"], "trace versus saved train baseline")
    return answer


def statistics(values):
    import numpy as np
    array = np.asarray(values, dtype=np.float64)
    if not array.size or not np.isfinite(array).all():
        raise ValueError("empty/nonfinite mechanism diagnostic")
    return dict(max_abs=float(np.max(np.abs(array))), rms=float(np.sqrt(np.mean(array * array))),
                elements=int(array.size))


def mechanism(name, parent, candidate, source_trace, actual_trace, proposal, labels):
    import numpy as np
    same_array(actual_trace["sender_keys"], source_trace["sender_keys"], "candidate raw consumed train keys")
    delta = candidate.astype(np.float64) - parent.astype(np.float64)
    matrix = np.vstack((delta[:36].reshape(4, 9).T, delta[36:]))
    # F64 frozen-state surrogate, not a shadow model or exact F32 recurrent replay.
    frozen_z = source_trace["sender_z"].astype(np.float64) + source_trace["sender_keys"].astype(np.float64) @ matrix
    roles = np.asarray([0 if c == int(labels[q]) else 1 for q in range(80) for c in range(2)])
    target = proposal["boundary_prototypes"][roles].transpose(1, 0, 2)
    assigned = proposal["boundary_prototypes"][1 - roles].transpose(1, 0, 2) if name == "WRONG_BOUNDARY_ROLE" else target
    failed = np.repeat(~source_trace["parent_correct"], 2)
    return dict(
        frozen_z_model="parent actual F32 z promotedF64 plus F64 K times representedF32 parameter delta; includes arithmetic and recurrent mismatch",
        actual_minus_frozen_z=statistics(actual_trace["sender_z"].astype(np.float64) - frozen_z),
        failed_train_true_boundary_error=statistics(actual_trace["sender_boundary"][:, failed] - target[:, failed]),
        failed_train_assigned_boundary_error=statistics(actual_trace["sender_boundary"][:, failed] - assigned[:, failed]),
        parent_failed_true_boundary_error=statistics(source_trace["sender_boundary"][:, failed] - target[:, failed]),
        receiver_first_passage_change=statistics(actual_trace["receiver_first_hit_f64"] - source_trace["receiver_first_hit_f64"]),
        receiver_value_change=statistics(actual_trace["receiver_value_f64"] - source_trace["receiver_value_f64"]),
        direct_scalar_F_at_candidate_z_calls=0, diagnostic_is_not_ndu_or_task_optimality=True)


def main():
    if len(sys.argv) != 6:
        raise SystemExit("runner.py BINDING_JSON HELPER_DIR PREPARED_DIR EVIDENCE_DIR NEW_OUTPUT_DIR")
    binding_path, helper, prepared, evidence, output = (Path(value).resolve() for value in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=False)
    binding = json.loads(binding_path.read_text())
    result = dict(schema="hepta.public-boundary8-result.v1", status="STARTED", model_calls_before_entry=0,
                  new_backward=0, new_optimizer_steps=0, new_llm_api_calls=0,
                  conversational_editor_cost="UNAVAILABLE_NOT_MEASURED_ZERO", native_owner=False,
                  production=False, new_heldout_queries=0, original_test_calls=0,
                  author_vit_benchmark_reproduction=False)
    json_new(output / "ENTRY.json", dict(binding_sha256=sha(binding_path.read_bytes()), **result))
    ledger, adapter, failure = None, None, None
    own_before = {p.name: sha(p.read_bytes()) for p in HERE.iterdir() if p.suffix in (".py", ".json")}
    try:
        manifest = bind_sources(binding, helper)
        if sys.version_info[:3] != (3, 12, 3) or sys.byteorder != "little" or platform.machine() != "x86_64":
            raise ValueError("unqualified public CPU interpreter/platform")
        for name, expected in (("torch", "2.10.0+cpu"), ("numpy", "2.3.5"), ("scipy", "1.17.0")):
            if importlib.metadata.version(name) != expected:
                raise ValueError("unqualified public dependency version: " + name)
        if any(os.environ.get(key) != "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("single numerical thread contract missing")
        context = getcontext()
        if context.prec != 28 or context.rounding != ROUND_HALF_EVEN:
            raise ValueError("unqualified outer Decimal context; frozen grid requires28 half-even")
        sys.path.insert(0, str(helper))
        support = importlib.import_module("static_support")
        model_module = importlib.import_module("model_adapter")
        candidate_module = importlib.import_module("candidates")
        for name, module in (("static_support.py", support), ("model_adapter.py", model_module), ("candidates.py", candidate_module)):
            if Path(module.__file__).resolve() != helper / name:
                raise ValueError("imported predecessor helper path differs")
        import numpy as np
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)

        class BoundaryLedger(support.Ledger):
            def __init__(self):
                self.path = output / "calls.jsonl"
                self.path.touch(exist_ok=False)
                self.start = COLD_START
                self.counts = {name: 0 for name in CAPS}
                self.event("opened", caps=CAPS, full_model_budget_is_incremental=True)

            def charge(self, name, amount=1):
                if name not in CAPS or type(amount) is not int or amount < 0:
                    raise ValueError("unknown counter/nonnegative integer charge required")
                if self.counts[name] + amount > CAPS[name]:
                    raise RuntimeError("frozen extension budget exceeded: " + name)
                self.counts[name] += amount

            def check_time(self):
                if time.process_time() > 120 or time.monotonic() - COLD_START > 180:
                    raise RuntimeError("extension CPU/wall budget exhausted")

        ledger = BoundaryLedger()
        files = binding["pilot_files"]
        # Raw byte identity checks may read compressed evidence, but do not decode
        # candidate quality or held scores before all new candidates are sealed.
        for name in files:
            bound_file(evidence, name, files)
        prior_cost = predecessor_admission(evidence, files)
        data = model_module.load_data(prepared, manifest)
        adapter = model_module.Adapter(prepared, manifest, ledger)
        manifest = dict(manifest, qualified_profile=adapter.profile)
        trace, meta = load_train_trace(evidence, files, data["train"], manifest,
                                      binding["helper_files"]["model_adapter.py"]["sha256"])
        parent = adapter.parent.copy()
        json_new(output / "ACTUAL_PUBLIC_SOURCE.json", dict(
            parent_checkpoint_sha256=PARENT_SHA, loaded_sources=adapter.loaded_sources,
            profile=adapter.profile, normalizer_sha256=NORMALIZER_SHA,
            trace_sha256=files["baseline_train_trace.npz"]["sha256"],
            canonical_file_loaded=False, registered_tensor_profile=manifest["tensor_profile"],
            cold_model_initialization_cost_included=True, full_model_calls=0))
        program = importlib.import_module("boundary_program")
        inverse = importlib.import_module("boundary_inverse")
        if Path(program.__file__).resolve() != HERE / "boundary_program.py" or Path(inverse.__file__).resolve() != HERE / "boundary_inverse.py":
            raise ValueError("immutable mathematical module import path differs")
        config = adapter.model.body.config
        constants = inverse.Constants(mu0=config.base_drift, drift_scale=config.drift_scale,
            cost0=config.cost, cost_span=config.cost_span, sigma=config.sigma, rho=config.discount,
            eta=math.exp(-config.stages * math.log1p(config.discount * config.refractory / config.stages)),
            gain=config.gain, maintenance=config.maintenance)
        root_receipts = []
        original_inverse = program.invert_boundary

        def start_operation(kind, descriptor):
            ledger.check_time()
            if kind == "scalar_coupled_qvi_inverse":
                ledger.charge("scalar_inverse_targets")
            elif kind == "shared_10x4_fit":
                ledger.charge("analytic_solves")
            else:
                raise ValueError("unregistered mathematical operation")
            ledger.event("operation_started", operation=kind, descriptor=descriptor)

        def recorded_inverse(*args, **kwargs):
            index = len(root_receipts)
            started = time.monotonic()
            try:
                record = dict(original_inverse(*args, **kwargs))
            except BaseException as error:
                record = dict(status="ABSTAIN_OR_EXCEPTION", error=repr(error), **getattr(error, "evidence", {}))
                record["elapsed_wall_seconds"] = time.monotonic() - started
                json_new(output / ("root_%02d.json" % index), record)
                root_receipts.append(record)
                charge_root(record)
                raise
            record["elapsed_wall_seconds"] = time.monotonic() - started
            json_new(output / ("root_%02d.json" % index), record)
            root_receipts.append(record)
            charge_root(record)
            return record

        def charge_root(record):
            for target, source in (("root_cells", "cells"), ("root_bisections", "bisections"),
                                   ("root_interval_evaluations", "interval_evaluations"),
                                   ("root_point_evaluations", "point_evaluations")):
                ledger.charge(target, int(record.get(source, 0)))
            ledger.event("inverse_completed_or_abstained", status=record["status"],
                         domain_complete=record.get("domain_complete", False))

        program.invert_boundary = recorded_inverse
        try:
            proposal = program.construct(trace,
                adapter.model.body.raw_cost[:4].detach().numpy().copy(),
                adapter.model.body.reset_absolute[:4].detach().numpy().copy(),
                constants, start_operation, wall_seconds=max(.001, 180 - (time.monotonic() - COLD_START)))
        finally:
            program.invert_boundary = original_inverse
        np.savez_compressed(output / "REAL_PROPOSAL_ARRAYS.npz", **proposal["directions"],
                            boundary_prototypes=proposal["boundary_prototypes"],
                            target_z=proposal["target_z"], reference_z=proposal["reference_z"])
        json_new(output / "REAL_PROPOSAL.json", {key: value for key, value in proposal.items()
                 if key not in ("directions", "boundary_prototypes", "target_z", "reference_z")})
        vectors, records = {}, {}
        for name, source, dose in ((NAMES[0], "BOUNDARY_PROGRAM", .25), (NAMES[1], "BOUNDARY_PROGRAM", 1.),
                                  (NAMES[2], "WRONG_BOUNDARY_ROLE", 1.), (NAMES[3], "MATCHED_RANDOM", 1.)):
            ledger.check_time()
            real_delta = support.flat_from_matrix(proposal["directions"][source]) * dose
            theta, budget = support.realized(parent, real_delta)
            if support.exact_norm2(theta, parent) > 1:
                raise ValueError("compiled F32 boundary candidate outside fixed radius")
            vectors[name] = theta.copy()
            records[name] = candidate_module.save_candidate(name, theta, adapter, output, budget,
                dict(fixed_dose=dose, program=source, frozen_rule=True, task_gradient=False,
                     supervised_training_donors=True, continuous_norm=float(np.linalg.norm(real_delta)),
                     rounding_policy_helper_sha256=binding["helper_files"]["static_support.py"]["sha256"]))
        adapter.set_theta(parent)
        random_n2 = support.exact_norm2(vectors[NAMES[3]], parent)
        boundary_n2 = support.exact_norm2(vectors[NAMES[1]], parent)
        json_new(output / "CANDIDATES_SEALED.json", dict(candidate_order=NAMES, records=records,
            all_new_candidate_quality_unread=True, exact_f32_norm_equality_claim=False,
            random_minus_boundary_squared_norm=dict(numerator=str((random_n2-boundary_n2).numerator),
                                                    denominator=str((random_n2-boundary_n2).denominator)),
            counts=dict(ledger.counts), native_owner=False))

        baseline = frozen_baselines(evidence, files, data, trace)
        keep = dict(name="KEEP", norm=0., declaration_index=0, protection_passed=True,
                    **{split: support.metrics(baseline[split], data[split]["y"]) for split in baseline})
        prior = [keep]
        for index, name in enumerate(PRIOR_NAMES, 1):
            record = json.loads(bound_file(evidence, name + ".json", files))
            with np.load(evidence / (name + ".evaluation.npz"), allow_pickle=False) as archive:
                values = {"train": archive["train_scores"], "dev": archive["dev_scores"], "retain": archive["retained_scores"]}
            if any(value.dtype != np.dtype("float32") for value in values.values()):
                raise ValueError("prior candidate actual output dtype differs")
            prior.append(dict(name=name, norm=record["norm"], declaration_index=index,
                protection_passed=support.eligible(values["retain"], baseline["retain"], data["retain"]["y"]),
                **{split: support.metrics(values[split], data[split]["y"]) for split in values}))
        evaluations = [keep]
        combined = model_module.combine(data["dev"], data["retain"])
        for index, name in enumerate(NAMES, 1):
            raw = (output / (name + ".f32le")).read_bytes()
            if raw != vectors[name].tobytes() or sha(raw) != records[name]["parameter_sha256"]:
                raise ValueError("candidate changed after the four-way seal")
            adapter.load_candidate(output / (name + ".pt"), records[name]["checkpoint_sha256"], vectors[name])
            # Exactly 4 train calls x 3 slow ticks = 12 recorded linear replays.
            train_scores, actual_trace, _ = adapter.run(data["train"], name + "_TRAIN80", compile_trace=True)
            held_scores, _, _ = adapter.run(combined, name + "_DEV32_RETAIN28", compile_trace=False)
            tr, held = train_scores.detach().numpy().copy(), held_scores.detach().numpy().copy()
            np.savez_compressed(output / (name + ".evaluation.npz"), train_scores=tr, dev_scores=held[:32],
                                retained_scores=held[32:], **actual_trace)
            row = dict(name=name, norm=records[name]["norm"], declaration_index=index,
                train=support.metrics(tr, data["train"]["y"]), dev=support.metrics(held[:32], data["dev"]["y"]),
                retain=support.metrics(held[32:], data["retain"]["y"]),
                protection_passed=support.eligible(held[32:], baseline["retain"], data["retain"]["y"]),
                mechanism=mechanism(name, parent, vectors[name], trace, actual_trace, proposal, data["train"]["y"]))
            json_new(output / (name + ".evaluation.json"), row)
            evaluations.append(row)
            adapter.set_theta(parent)
        selection = {}
        for method, rows in (("BOUNDARY_PROGRAM", evaluations), ("ANALYTIC_ROLE", prior), ("BP_TASK", prior)):
            winner = support.choose([row for row in rows if row["protection_passed"] and
                                     (row["name"] == "KEEP" or row["name"].startswith(method + "_"))])
            selection[method] = dict(selected=winner["name"],
                development_signal=winner["dev"]["correct"] >= keep["dev"]["correct"] + 1 and winner["train"]["ce"] < keep["train"]["ce"],
                new_heldout_claim=False, quality_matched_speedup_claim=False)
        expected = dict(forwards=8, body_ticks=48, paired_queries=560, backwards=0,
                        optimizer_steps=0, analytic_solves=2, trace_linear_replays=12, scalar_inverse_targets=24)
        if any(ledger.counts[key] != value for key, value in expected.items()):
            raise ValueError("completed extension has a different frozen operation ledger")
        ledger.check_time()
        result.update(status="COMPLETED", evaluations=evaluations, predecessor_evaluations=prior,
            selection=selection, predecessor_counts=prior_cost["counts"],
            predecessor_cpu_seconds=prior_cost["cpu_seconds"], predecessor_wall_seconds=prior_cost["active_wall_seconds"],
            total_project_full_forwards=41, total_project_backwards=17, total_project_optimizer_steps=16,
            incremental_parameter_gradient_free=True, whole_comparative_project_gradient_free=False,
            all_failed_controls_retained=True, generated_candidates=len(records))
    except BaseException as error:
        failure = error
        result.update(status="ABSTAIN_OR_ABORTED", error=repr(error), partial_budget=True,
                      retry_permitted=False, no_root_proof=False)
        if ledger is not None:
            ledger.event("aborted", error=repr(error))
    finally:
        problems = []
        if adapter is not None:
            try:
                adapter.set_theta(adapter.parent)
                result["parent_restored_in_memory"] = adapter.theta().tobytes() == adapter.parent.tobytes()
            except BaseException as error:
                problems.append("parent restore: " + repr(error))
        after = {p.name: sha(p.read_bytes()) for p in HERE.iterdir() if p.suffix in (".py", ".json")}
        result["adapter_source_unchanged"] = after == own_before
        if after != own_before:
            problems.append("adapter source changed during execution")
        try:
            result["original_parent_file_unchanged"] = sha((prepared / "parent.pt").read_bytes()) == PARENT_SHA
            for name, expected in binding["helper_files"].items():
                bound_file(helper, name, binding["helper_files"])
            for name in binding["pilot_files"]:
                bound_file(evidence, name, binding["pilot_files"])
        except BaseException as error:
            problems.append("bound input readback: " + repr(error))
        if not result.get("original_parent_file_unchanged", False):
            problems.append("original public parent identity changed")
        if problems:
            result.update(status="ABSTAIN_OR_ABORTED", integrity_errors=problems)
            failure = failure or ValueError("; ".join(problems))
        result.update(counts=None if ledger is None else dict(ledger.counts),
                      active_wall_seconds=time.monotonic() - COLD_START, cpu_seconds=time.process_time())
        json_new(output / "RESULT.json", result)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
