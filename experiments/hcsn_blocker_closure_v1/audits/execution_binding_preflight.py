"""Synthetic checks for a concrete import/provenance repair; no study outcomes."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

import numpy as np
import torch

from experiments.hcsn_blocker_closure_v1.execution_binding import driver, state_io


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]


def run():
    started = time.process_time()
    torch.set_num_threads(1)
    checks = []

    def check(name, passed, details=None):
        checks.append(dict(name=name, passed=bool(passed), details=details))
        if not passed:
            raise AssertionError(name)

    excluded = ("experiments.hcsn_distributional_v2.runtime_eval",
                "experiments.hcsn_free_boundary_v1.training",
                "experiments.hcsn_free_boundary_v1.benchmark_models")
    check("driver_import_without_training_dependencies", all(name not in sys.modules for name in excluded))
    old = ast.parse((ROOT/"experiments/hcsn_distributional_v2/runtime_eval.py").read_text())
    new = ast.parse(Path(state_io.__file__).read_text())
    for name in ("numeric_state", "read_state"):
        old_fn = next(node for node in old.body if isinstance(node, ast.FunctionDef) and node.name == name)
        new_fn = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == name)
        check(name+"_identical_function_ast", ast.dump(old_fn) == ast.dump(new_fn))

    with tempfile.TemporaryDirectory(prefix="hcsn-binding-review-") as temporary:
        folder = Path(temporary)
        model = driver.build("value_jg", input_dim=64, output_dim=8, width=32, depth=1, seed=910007).eval()
        generator = torch.Generator().manual_seed(910008)
        x = torch.randn(1, 2, 64, generator=generator)
        dt = torch.tensor([[0.75, 1.1]], dtype=torch.float32)
        with torch.inference_mode():
            _, state, _ = model.step(x[:, 0], dt[:, 0])
            numeric = state_io.numeric_state(state)
            np.savez_compressed(folder/"state.npz", **numeric)
            restored = state_io.read_state(folder/"state.npz", 1)
            loaded = state_io.numeric_state(restored)
            check("numeric_state_roundtrip_exact", set(numeric) == set(loaded) and
                  all(np.array_equal(numeric[key], loaded[key]) for key in numeric))
            check("numeric_state_complete", set(numeric) == {
                "elapsed", "layer_0.content", "layer_0.probability", "layer_0.boundary"})
            check("serializer_copies_elapsed", not np.shares_memory(numeric["elapsed"], state["elapsed"].numpy()))
            reference_logits, reference_state, _ = model.step(x[:, 1], dt[:, 1], state)
            recovered_logits, recovered_state, _ = model.step(x[:, 1], dt[:, 1], restored)
            check("resumed_synthetic_logits_bitwise_equal", torch.equal(reference_logits, recovered_logits))
            check("resumed_synthetic_full_state_bitwise_equal",
                  driver.state_digest(reference_state) == driver.state_digest(recovered_state))
        bad = dict(numeric)
        bad.pop("layer_0.probability")
        np.savez_compressed(folder/"incomplete.npz", **bad)
        rejected = False
        try:
            state_io.read_state(folder/"incomplete.npz", 1)
        except ValueError:
            rejected = True
        check("incomplete_probability_state_rejected", rejected)

        proof = ROOT/"experiments/hcsn_blocker_closure_v1/content/PREFLIGHT.json"
        protocol = dict(schema="hcsn-blocker-content-protocol.v1", status="registered",
            public_execution_commit="a"*40,
            design=driver.load_json(ROOT/"experiments/hcsn_blocker_closure_v1/content/DESIGN.json"),
            source_sha256=driver.source_map(), preflight=dict(file=proof.relative_to(ROOT).as_posix(),
                                                              sha256=driver.sha(proof)))
        protocol_path = folder/"PROTOCOL.json"

        def exercise(candidate, expected_commit="a"*40, expected_sha=None):
            protocol_path.write_text(json.dumps(candidate, sort_keys=True, allow_nan=False)+"\n")
            return driver.verify_study_contract(folder, expected_commit,
                driver.sha(protocol_path) if expected_sha is None else expected_sha)

        check("synthetic_valid_source_contract_accepted", exercise(protocol) == protocol)
        cases = []
        changed = copy.deepcopy(protocol)
        changed["public_execution_commit"] = "b"*40
        cases.append(("wrong_training_commit_rejected", changed, {}))
        cases.append(("wrong_protocol_sha_rejected", protocol, dict(expected_sha="0"*64)))
        changed = copy.deepcopy(protocol)
        changed["design"]["formal_updates"] += 1
        cases.append(("changed_complete_design_rejected", changed, {}))
        changed = copy.deepcopy(protocol)
        changed["source_sha256"].pop(next(iter(changed["source_sha256"])))
        cases.append(("omitted_source_rejected", changed, {}))
        changed = copy.deepcopy(protocol)
        changed["source_sha256"][next(iter(changed["source_sha256"]))] = "0"*64
        cases.append(("changed_source_hash_rejected", changed, {}))
        changed = copy.deepcopy(protocol)
        changed["preflight"]["sha256"] = "0"*64
        cases.append(("changed_preflight_rejected", changed, {}))
        for name, candidate, kwargs in cases:
            rejected = False
            try:
                exercise(candidate, **kwargs)
            except ValueError:
                rejected = True
            check(name, rejected)

        exercise(protocol)
        job_dir = folder/"fixed"/driver.JOB_ID
        job_dir.mkdir(parents=True)
        job = dict(stage="fixed", task="selective_copy", arm="value_jg", seed=driver.SEED,
                   id=driver.JOB_ID, updates=96)
        (job_dir/"job.json").write_text(json.dumps(job))
        (job_dir/"selection.json").write_text("{}")
        np.savez_compressed(job_dir/"selected_state.npz", synthetic=np.array([1.0], dtype=np.float32))
        rejected = False
        try:
            driver.prepare(folder, folder/"unused-output", folder/"unused-binary", "a"*40,
                           driver.sha(protocol_path), "0"*64)
        except ValueError as error:
            rejected = "external pin" in str(error)
        check("wrong_selected_weights_pin_rejected_before_execution", rejected)
        job["id"] = "a_different_worker"
        (job_dir/"job.json").write_text(json.dumps(job))
        rejected = False
        try:
            driver.prepare(folder, folder/"unused-output", folder/"unused-binary", "a"*40,
                           driver.sha(protocol_path), driver.sha(job_dir/"selected_state.npz"))
        except ValueError as error:
            rejected = "preselected trained worker" in str(error)
        check("wrong_fixed_worker_id_rejected_before_execution", rejected)

    sources = [Path(driver.__file__), Path(state_io.__file__), Path(__file__),
               ROOT/"experiments/hcsn_blocker_closure_v1/execution_binding/measure.py",
               ROOT/"experiments/hcsn_blocker_closure_v1/execution_binding/PROTOCOL.json"]
    result = dict(schema="hcsn-execution-binding-synthetic-preflight.v1", passed=all(row["passed"] for row in checks),
        scope="Synthetic initialized model/tensors and synthetic protocol header only; no trained weights, study validation, formal test or OOD data accessed",
        checks=checks, source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        cpu_seconds_after_imports=time.process_time()-started,
        does_not_establish=["trained checkpoint binding", "native resume", "real hardware scaling", "task utility"])
    destination = BASE/"execution_binding_preflight002"
    destination.mkdir(exist_ok=False)
    (destination/"RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(dict(passed=result["passed"], checks=len(checks), result=str(destination/"RESULT.json")), sort_keys=True))


if __name__ == "__main__":
    run()
