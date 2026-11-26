"""One independent cold prediction of the exact accepted nonsmooth candidate.

The driver imports no numerical framework/model and never changes the original
smooth gate. All outputs remain research evidence, with no production adoption.
"""
import argparse
import copy
import math
import os
from pathlib import Path
import signal
import struct
import sys
import time

from bounded_process import run_child
from profile_io import canonical, parse, read_named, read_pin, require, sha, write_new

PINS = {
    "RESULT.json": "8fff2a2525bb5ba411532e28fee28d549c491372add6feb2b58a9399d89a446e",
    "TRIAL_EVIDENCE.json": "2764a0d9cf67d34760f31f5779653bc030bba3f679f99a82e0601323ba21b6e4",
    "EDIT_RECEIPT.json": "7dd444c83b59b00948248751c19b4ae24e9f60c1139aa7c959df89eec701afce",
    "SURROGATE_STEP.json": "d71efb51f3799669aa41cdc0c4c681712b45949c2fd9d635cf52215f28fc8254",
}
PARENT = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
PROFILE = "4a8feafa490224f0ad14d318835f51d1147b8b6b93c7a56e9f9eb3ddc3d43d77"
CANDIDATE = "87ed31e17899f4ae18cbad3ea7a9b7af05cf42662da4ffd94a1c2c83cde9ef88"
STATE = "9630e1de513658155e8c0c7c6cff13a3954cf49db3534ed3051c49fa035ac66c"
FAILED = "15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105"
EXTRA_SOURCES = ("verify_nonsmooth_cold.py", "bounded_process.py", "numeric_runner.py")
LIMITS = {"child_invocations": 1, "model_loads": 1, "physical_forward_calls": 1,
          "quadratic_solves": 0, "vjp_calls": 0, "training_updates": 0,
          "child_wall_seconds": 55, "outer_wall_seconds": 90}
CAP = 1024 * 1024


def close(a, b, atol=1e-20, rtol=1e-12):
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= atol + rtol * abs(b)


def array_sha(values, shape):
    return sha(str(("<f8", shape)).encode() + struct.pack("<" + "d" * len(values), *values))


def fixture():
    # Original four-tick numeric stimulus only; no physical operator is copied.
    x = [[[0., 0., 0., 0., t / 3, 0.] for _ in range(2)] for t in range(4)]
    noise = ((.03, -.02), (-.01, .04), (.02, .02), (-.03, .01))
    for b in range(2):
        x[0][b][0], x[0][b][2] = (-.4, .6)[b], 1.
        x[2][b][1], x[2][b][3] = (.7, -.2)[b], 1.
        for t in range(4):
            x[t][b][5] = noise[t][b]
    require(array_sha([v for tick in x for row in tick for v in row], (4, 2, 6))
            == "012e6e7c0c52b2f639ba6cca41f3197391c7b08e8804ed6c6d92941bd0374a93"
            and array_sha([.59, .73], (2, 1))
            == "0a497c985158f5df5b0564153450d13370bacae293ddc9d59fd204ce8697c52b",
            "original input or initial-margin byte identity differs")
    return x, [.59, .73]


def evidence(args, protocol):
    records = {name: parse(read_named(Path(args.receipts) / name, expected, CAP)) for name, expected in PINS.items()}
    result, trial, edit, proposal = (records[name] for name in PINS)
    for receipt in (result, trial):
        require(receipt["status"] == "COMPLETED_SINGLE_TRIAL" and receipt["decision"] == "ACCEPTED"
                and receipt["parent_restored"] is True and receipt["accumulated_gradients_unchanged"] is True
                and receipt["parent_state_after_sha256"] == receipt["parent"]["state_sha256"], "accepted restored trial required")
    for receipt in records.values():
        require(receipt["original_smooth_status"] == "FAILED" and receipt["original_failed_result_sha256"] == FAILED
                and receipt["classical_jacobian_admitted"] is False, "original failed scope must remain failed")
    require(result["candidate_exported"] is True and result["candidate_adopted"] is False
            and trial["eligible_for_research_export"] is True and trial["production_adoption"] is False
            and result["parent"] == trial["parent"] and result["gate"] == trial["gate"], "trial/export identity differs")
    for key, name in (("trial_evidence", "TRIAL_EVIDENCE.json"), ("edit_receipt", "EDIT_RECEIPT.json"),
                      ("surrogate_proposal", "SURROGATE_STEP.json")):
        require(result[key]["path"] == name and result[key]["sha256"] == PINS[name], "receipt chain differs")
        read_pin(args.receipts, result[key], CAP)
    exported = result["candidate_export"]
    require(edit["trial_evidence"] == result["trial_evidence"] and trial["surrogate_proposal"] == result["surrogate_proposal"]
            and edit["learning_receipt_sha256"] == PINS["SURROGATE_STEP.json"]
            and edit["candidate_state_sha256"] == STATE == exported["model_state_sha256"]
            and edit["parent_state_sha256"] == trial["parent"]["state_sha256"]
            and exported["parent_candidate_sha256"] == PARENT == trial["parent"]["checkpoint_sha256"]
            and exported["artifact"] == {"path": "accepted_candidate.pt", "bytes": 9855, "sha256": CANDIDATE}, "full candidate chain differs")
    step, gate = proposal["algebraic_step"], trial["gate"]
    target = [v + d for v, d in zip(trial["base_output"], (1e-4, -1e-4))]
    require(target == proposal["targets"] and proposal["objective"] == trial["objective"]
            and step["ridge"] == 1e-3 and edit["max_step_norm"] == 1.0, "fixed engineering objective differs")
    phi0 = .5 * sum((v - t) ** 2 for v, t in zip(trial["base_output"], target))
    penalty = .0005 * sum(d * d for d in step["delta"])
    data = .5 * sum((v - t) ** 2 for v, t in zip(trial["trial_output"], target))
    phit, pred = data + penalty, phi0 - step["regularized_objective"]
    ared, tau = phi0 - phit, 1e-12 + 1e-6 * max(abs(phi0), abs(phit))
    require(pred > tau and ared > tau and ared / pred >= .1 and sum(d * d for d in step["delta"]) <= 1., "actual trial gate not accepted")
    expected = {"Phi0": phi0, "Phi_trial": phit, "pred": pred, "ared": ared, "tau": tau,
                "ridge_penalty": penalty, "data_objective": data, "ratio": ared / pred}
    require(all(close(gate[key], value) for key, value in expected.items()), "retained actual gate arithmetic differs")
    roots = {"native_profile_v4": Path(__file__).resolve().parent, "nonsmooth_trial_v4": Path(args.trial_code),
             "sensitivity_v4": Path(args.sensitivity_code)}
    expected_sources = {**trial["source_sha256"], **{"native_profile_v4/" + name: protocol["source_sha256"]["native_profile_v4/" + name] for name in EXTRA_SOURCES}}
    require(protocol["source_sha256"] == expected_sources and protocol["runtime"] == trial["runtime"], "complete source/runtime pins required")
    for name, expected in expected_sources.items():
        folder, filename = name.split("/")
        read_named(roots[folder] / filename, expected, CAP)
    return result, trial


def execute(args, protocol, out, report):
    result, trial = evidence(args, protocol)
    parent = parse(read_named(args.parent_profile, PROFILE, CAP))
    require(parent["checkpoint"]["sha256"] == PARENT and parent["checkpoint"]["bytes"] == 9605
            and trial["parent"]["profile_sha256"] == PROFILE and parent["runtime"] == trial["runtime"], "parent profile differs")
    read_pin(args.materials, parent["checkpoint"], 32 * CAP)
    read_pin(args.receipts, result["candidate_export"]["artifact"], 32 * CAP)
    manifest = copy.deepcopy(parent)
    manifest.update(format="research_candidate_v1", origin={"protocol_sha256": None, "coordinate_candidate_sha256": None})
    manifest["checkpoint"] = {**result["candidate_export"]["artifact"], "path":
        (Path(args.receipts).resolve() / "accepted_candidate.pt").relative_to(Path(args.materials).resolve()).as_posix()}
    profile_pin = write_new(out / "CANDIDATE_PROFILE.json", canonical(manifest) + b"\n", CAP)
    x, margin = fixture()
    task = {"schema": "hepta.smallhcsn.numeric-task.v1", "task_id": "accepted-nonsmooth-cold-only",
            "profile_sha256": profile_pin["sha256"], "candidate_sha256": CANDIDATE,
            "x": x, "initial": {"kind": "margin", "margin": margin}}
    task_pin = write_new(out / "NUMERIC_TASK.json", canonical(task) + b"\n", CAP)
    require(all(os.environ.get(k) == "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")), "freeze thread environment before child startup")
    report["child_invocations"] = 1
    pin = parse(run_child([sys.executable, "-B", str(Path(__file__).with_name("numeric_runner.py")),
        "--profile", str(out / "CANDIDATE_PROFILE.json"), "--profile-sha256", profile_pin["sha256"],
        "--material-root", args.materials, "--task", str(out / "NUMERIC_TASK.json"),
        "--task-sha256", task_pin["sha256"], "--state-root", str(out), "--output", str(out / "cold")]))
    cold = parse(read_pin(out / "cold", pin, 16 * CAP), 16 * CAP)
    require(cold["profile_sha256"] == profile_pin["sha256"] and cold["candidate_sha256"] == CANDIDATE
            and cold["model_state_sha256"] == STATE and cold["source_binding_sha256"] == trial["parent"]["source_binding_sha256"]
            and cold["task_sha256"] == task_pin["sha256"] and (cold["start_step"], cold["end_step"]) == (0, 4)
            and cold["production_adoption"] is False and cold["real_cross_user_acceptance"] is False, "cold candidate identity differs")
    observed = [row[1] - row[0] for row in cold["logits"][-1]]
    require(len(observed) == 2 and all(close(a, b, 1e-12, 1e-11) for a, b in zip(observed, trial["trial_output"])), "actual cold margins differ from accepted trial")
    read_pin(out / "cold", cold["population"], 32 * CAP)  # Original pinned runner validates all five tensors, step/config.
    read_pin(args.materials, parent["checkpoint"], 32 * CAP)
    report.update(status="PASSED_BOUNDED_ENGINEERING", verified_model_forward_calls=1,
        candidate_profile=profile_pin, task=task_pin, cold_result={"root": "cold", "artifact": pin},
        population={"root": "cold", "artifact": cold["population"]}, cold_margins=observed,
        accepted_trial_margins=trial["trial_output"], max_abs_margin_difference=max(abs(a-b) for a,b in zip(observed, trial["trial_output"])),
        parent_checkpoint_bytes_unchanged=True, candidate_sha256=CANDIDATE, candidate_state_sha256=STATE,
        source_binding_sha256=cold["source_binding_sha256"], candidate_config=trial["parent"]["config"],
        config_identity_basis="pinned accepted full checkpoint, original export config, strict frozen loader; no driver pickle decoding")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "protocol-sha256", "parent-profile", "receipts", "materials", "trial-code", "sensitivity-code", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    protocol = parse(read_named(args.protocol, args.protocol_sha256, CAP))
    require(protocol["schema"] == "hepta.smallhcsn.accepted-nonsmooth-cold.v1" and protocol["ready_for_execution"] is True
            and protocol["receipt_sha256"] == PINS and protocol["parent_profile_sha256"] == PROFILE
            and protocol["limits"] == LIMITS and protocol["comparison"] == {"rtol": 1e-11, "atol": 1e-12}, "registered cold scope differs")
    out = Path(args.output).resolve()
    require(out.is_relative_to(Path(args.materials).resolve()), "cold evidence output must stay in material root")
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    report = {"schema": "hepta.smallhcsn.accepted-nonsmooth-cold-result.v1", "status": "FAILED",
              "protocol_sha256": args.protocol_sha256, "receipt_sha256": PINS, "child_invocations": 0,
              "verified_model_forward_calls": 0, "quadratic_solves": 0, "vjp_calls": 0, "training_updates": 0,
              "original_smooth_status": "FAILED", "natural_task_benefit_claim": False, "production_adoption": False}
    started = time.monotonic()
    def expired(_signal, _frame):
        raise TimeoutError("accepted candidate cold budget expired")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(85)  # Five seconds of the 90-second outer budget remain for group cleanup.
    try:
        execute(args, protocol, out, report)
    except Exception as error:
        report["error"] = repr(error)
    finally:
        signal.alarm(0)
        imports = [name for name in sys.modules if name.split(".")[0] in ("torch", "numpy", "small_hcsn_profile", "first_order", "qualification")]
        report["driver_model_or_framework_imports"] = imports
        if imports:
            report["status"], report["error"] = "FAILED", "driver imported numerical/model modules"
        report["wall_s"] = time.monotonic() - started
        pin = write_new(out / "RESULT.json", canonical(report) + b"\n", CAP)
    print(canonical({"status": report["status"], "result": pin}).decode())
    return 0 if report["status"] == "PASSED_BOUNDED_ENGINEERING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
