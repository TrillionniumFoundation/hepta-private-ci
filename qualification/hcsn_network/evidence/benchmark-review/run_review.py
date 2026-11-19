"""Gate and account for one frozen, zero-model campaign arithmetic review."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


PROTOCOL_SHA256 = "9601216e77b3dc5b3b41f77d7df8f124b7ab176692b0a0b66f24773b95eec9e0"
SOURCE_COMMIT = "8fe7bc209803659cc3f4780be0940c5183ca6e9b"
REPOSITORY = Path(__file__).resolve().parents[4]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def equal_integer(value, expected, name):
    if type(value) is not int or value != expected:
        raise ValueError("invalid integer: "+name)


def finite_real(value, name, lower=0., upper=None):
    if (type(value) not in (int, float) or not math.isfinite(value) or value < lower
            or (upper is not None and value > upper)):
        raise ValueError("invalid finite scalar: "+name)


def metadata_gate(root, protocol_path):
    if digest(protocol_path) != PROTOCOL_SHA256:
        raise ValueError("different original frozen protocol")
    protocol = read_json(protocol_path)
    for name, expected in protocol["sources"].items():
        if digest(REPOSITORY/name) != expected:
            raise ValueError("changed frozen source: "+name)
    expected = {(arm, seed) for arm in protocol["arms"] for seed in protocol["seeds"]}
    if len(expected) != 30:
        raise ValueError("different original roster")
    complete, seal = read_json(root/"COMPLETE.json"), read_json(root/"EVALUATION_SEAL.json")
    for key in ("fit_children", "evaluation_children"):
        equal_integer(complete[key], 30, key)
    for key in ("fit_failures", "evaluation_failures"):
        equal_integer(complete[key], 0, key)
    if complete["all_training_selections_preceded_test_access"] is not True:
        raise ValueError("evaluation ordering is not recorded")
    if (seal["protocol_sha256"] != PROTOCOL_SHA256 or seal["source_commit"] != SOURCE_COMMIT
            or len(seal["fits"]) != 30
            or {(r["arm"], r["seed"]) for r in seal["fits"]} != expected):
        raise ValueError("incomplete or different selection seal")
    equal_integer(seal["test_examples_evaluated_before_seal"], 0, "pre-seal test cases")
    for stage in ("FIT", "EVALUATION"):
        costs = read_json(root/(stage+"_COSTS.json"))
        if len(costs) != 30 or len({r["directory"] for r in costs}) != 30:
            raise ValueError("incomplete or duplicate child-cost roster")
        indexed = {r["directory"]: r for r in costs}
        if set(indexed) != {f"{a}-s{s}" for a, s in expected}:
            raise ValueError("different child-cost roster")
        for name, cost in indexed.items():
            actual = read_json(root/("fit-processes" if stage == "FIT" else "evaluation-processes")/name/"COST.json")
            if {k: v for k, v in cost.items() if k != "directory"} != actual:
                raise ValueError("aggregate and original child cost disagree")
            equal_integer(actual["exit_code"], 0, "child terminal")
            for key in ("wall_seconds", "cpu_seconds", "maxrss_kib"):
                finite_real(actual[key], key)
            if actual["deadline_kill_sent"] is not False:
                raise ValueError("killed child cannot enter review")
    for row in seal["fits"]:
        equal_integer(row["seed"], row["seed"], "seed")
        name = f"{row['arm']}-s{row['seed']}"
        if row["directory"] != name or row["eligible_for_test"] is not True:
            raise ValueError("ineligible or differently named fit")
        equal_integer(row["terminal_exit_code"], 0, "sealed terminal")
        ordinal = row["selected_validation_index"]
        equal_integer(ordinal, ordinal, "selected validation ordinal")
        if ordinal < 0:
            raise ValueError("negative validation ordinal")
        for path, key in ((root/"fit-processes"/name/"COST.json", "terminal_cost_sha256"),
                          (root/"fits"/name/"selected.pt", "selected_sha256"),
                          (root/"fits"/name/"RESULT.json", "result_sha256"),
                          (root/"fits"/name/f"validation-{ordinal:03}.npz", "selected_validation_sha256")):
            if digest(path) != row[key]:
                raise ValueError("sealed original changed: "+str(path))
        fit = read_json(root/"fits"/name/"RESULT.json")
        if fit["arm"] != row["arm"] or fit["seed"] != row["seed"]:
            raise ValueError("fit identity disagrees with seal")
        if fit["status"] != "COMPLETED_WALL_BUDGET" or fit["selected"] != fit["validations"][ordinal]:
            raise ValueError("selected validation binding differs")
        for validation in fit["validations"]:
            finite_real(validation["accuracy"], "validation accuracy", upper=1.)
            finite_real(validation["cross_entropy"], "validation loss")
            finite_real(validation["completed_seconds"], "validation completion")
            if type(validation["eligible"]) is not bool:
                raise ValueError("validation eligibility is not a Boolean")
            if validation["eligible"] != (validation["completed_seconds"] <= protocol["budget_seconds"]):
                raise ValueError("validation eligibility differs from original deadline")
        eligible = [v for v in fit["validations"] if v["eligible"]]
        if (not eligible or fit["selected"] != max(eligible, key=lambda v: (v["accuracy"], -v["cross_entropy"]))
                or fit["selected"]["eligible"] is not True
                or fit["selected_updates"] != fit["selected"]["updates"]):
            raise ValueError("selected record is not the best eligible validation")
        equal_integer(fit["test_rows_read"], 0, "training test reads")
        evaluation = read_json(root/"evaluation"/name/"RESULT.json")
        if (evaluation["arm"] != row["arm"] or evaluation["seed"] != row["seed"]
                or evaluation["selected_checkpoint_sha256"] != row["selected_sha256"]):
            raise ValueError("evaluation model identity differs")
        equal_integer(evaluation["optimizer_calls"], 0, "evaluation optimizer calls")
        equal_integer(evaluation["test_examples"], 3498, "evaluation denominator")
        for key in ("test", "validation"):
            finite_real(evaluation[key]["accuracy"], key+" accuracy", upper=1.)
            finite_real(evaluation[key]["cross_entropy"], key+" loss")
        finite_real(evaluation["validation_saved_logit_max_abs"], "validation replay difference", upper=1e-12)
        started = read_json(root/"evaluation-processes"/name/"process"/"REQUEST.json")["started_unix"]
        if started < seal["sealed_unix_seconds"]:
            raise ValueError("evaluation process started before common selection seal")
    return {"status": "COMPLETE_ROSTER_AND_HASH_GATE_PASS", "fits": 30, "evaluation_children": 30,
            "test_labels_parsed_by_gate": False, "source_files_checked": len(protocol["sources"]),
            "source_commit": SOURCE_COMMIT, "protocol_sha256": PROTOCOL_SHA256}


def finite_arrays(root):
    import numpy as np

    checked, coordinates = 0, 0
    for row in read_json(root/"EVALUATION_SEAL.json")["fits"]:
        fit = root/"fits"/row["directory"]
        result = read_json(fit/"RESULT.json")
        paths = [(fit/f"validation-{i:03}.npz", 750) for i in range(len(result["validations"]))]
        paths.append((root/"evaluation"/row["directory"]/"predictions.npz", 3498))
        for path, rows in paths:
            with np.load(path, allow_pickle=False) as raw:
                logits, labels = raw["logits"], raw["labels"]
                if (logits.shape != (rows, 10) or labels.shape != (rows,)
                        or not np.issubdtype(logits.dtype, np.floating)
                        or not np.issubdtype(labels.dtype, np.integer)
                        or not np.isfinite(logits).all() or not ((labels >= 0) & (labels < 10)).all()):
                    raise ValueError("invalid saved prediction original: "+str(path))
                coordinates += logits.size
            checked += 1
    return {"status": "FINITE_SAVED_LOGITS_PASS", "arrays": checked, "logit_coordinates": coordinates,
            "new_model_calls": 0, "new_optimizer_calls": 0, "new_matrix_actions": 0}


def child(args):
    metadata_gate(Path(args.campaign), Path(args.protocol))
    checked = finite_arrays(Path(args.campaign))
    write_json(Path(args.output)/"FINITE_ARRAYS.json", checked)
    from qualification.hcsn_network import benchmark_review

    sys.argv = ["benchmark_review", "--campaign", args.campaign, "--protocol", args.protocol,
                "--data", args.data, "--output", str(Path(args.output)/"REVIEW.json")]
    benchmark_review.main()
    review = read_json(Path(args.output)/"REVIEW.json")
    def finite_tree(value):
        if isinstance(value, dict):
            for item in value.values():
                finite_tree(item)
        elif isinstance(value, list):
            for item in value:
                finite_tree(item)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite independent arithmetic result")
    finite_tree(review)
    if (review["status"] != "COMPLETE_ARITHMETIC_REVIEW" or review["failures"]
            or review["fits_reviewed"] != 30 or review["all_child_failures"] != 0):
        raise ValueError("original independent review did not complete all 30 fits")


def main():
    parser = argparse.ArgumentParser()
    for name in ("campaign", "protocol", "data", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    began, cpu_began = time.perf_counter(), time.process_time()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    gate = metadata_gate(Path(args.campaign), Path(args.protocol))
    write_json(out/"PRE_READ_GATE.json", gate)
    originals = {str(p): {"bytes": p.stat().st_size, "sha256": digest(p)}
                 for p in sorted(Path(args.campaign).rglob("*")) if p.is_file()}
    frozen = {"reader_wrapper_sha256": digest(Path(__file__)), "protocol_sha256": PROTOCOL_SHA256,
              "original_files": originals, "original_file_count": len(originals),
              "new_model_calls": 0, "new_optimizer_calls": 0, "originals_frozen_unix": time.time()}
    write_json(out/"SOURCE.json", frozen)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--child"]
    write_json(out/"REQUEST.json", {"command": command, "cpu": 8, "threads": 1,
               "address_space_bytes": 4*1024**3, "cpu_limits": [60, 65], "wall_limit_seconds": 90})
    env = os.environ.copy()
    env.update({key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                     "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")})
    env["PYTHONPATH"] = str(REPOSITORY)
    def limits():
        os.sched_setaffinity(0, {8})
        resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
    killed, started = False, time.perf_counter()
    with (out/"stdout").open("xb") as stdout, (out/"stderr").open("xb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env,
                                   preexec_fn=limits, start_new_session=True)
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.perf_counter()-started > 90 and not killed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    killed = True
                except ProcessLookupError:
                    pass
            time.sleep(.025)
    cost = {"exit_code": process.returncode, "wall_seconds": time.perf_counter()-started,
            "cpu_seconds": usage.ru_utime+usage.ru_stime, "user_seconds": usage.ru_utime,
            "system_seconds": usage.ru_stime, "maxrss_kib": usage.ru_maxrss,
            "deadline_kill_sent": killed, "includes_imports_checks_arithmetic_and_output": True,
            "body_timer_not_in_original_frozen_reader": True}
    write_json(out/"COST.json", cost)
    for path, value in originals.items():
        if digest(Path(path)) != value["sha256"]:
            raise ValueError("original changed during reader: "+path)
    metadata_gate(Path(args.campaign), Path(args.protocol))
    if digest(Path(__file__)) != frozen["reader_wrapper_sha256"]:
        raise ValueError("reader wrapper changed during execution")
    write_json(out/"CONTROLLER_COST.json", {"wall_seconds": time.perf_counter()-began,
               "parent_cpu_seconds": time.process_time()-cpu_began,
               "child_cpu_seconds": cost["cpu_seconds"], "originals_unchanged": True})
    print(json.dumps({"exit_code": process.returncode, "review_output": str(out)}), flush=True)
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
