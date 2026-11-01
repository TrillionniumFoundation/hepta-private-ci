"""Bind one frozen fitted Q to actual native events and fresh-process recovery."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parent
VERSION = 131101


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(values, endian="<"):
    return b"".join(struct.pack(endian + "d", value) for value in values)


def run(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    fitted_path = ROOT.parent/"evidence/fits/131101_hx_distribution.json"
    root_freeze = json.loads((ROOT.parent/"evidence/FREEZE.json").read_text())
    native_freeze = json.loads((ROOT/"RUNTIME_FREEZE.json").read_text())
    fitted = json.loads(fitted_path.read_text())
    shared = fitted["shared_model"]
    q, prior = shared["Q"], shared["prior"]
    n, flat = len(prior), [value for row in q for value in row]
    model_identity = hashlib.sha256(b"HCSN_R13_Q_VERSION_V1" + n.to_bytes(8, "big") +
                                   VERSION.to_bytes(8, "big") + encoded(flat, ">")).hexdigest()
    binary = ROOT/"evidence/build/hcsn-events-r13"
    model = destination/"frozen_fit_131101.model"
    model.write_text(f"{n} {VERSION}\n" + "\n".join(format(x, ".17g") for x in flat + prior) + "\n")
    source = sha(__file__)
    plan = {"schema": "hcsn-r13-learned-event-witness-plan-v1", "test_source_sha256": source,
        "fit_path": str(fitted_path), "fit_sha256": sha(fitted_path),
        "frozen_fit_sha256": root_freeze["fit_sha256"]["fits/131101_hx_distribution.json"],
        "root_freeze_sha256": sha(ROOT.parent/"evidence/FREEZE.json"),
        "q_row_major_f64_le_sha256": hashlib.sha256(encoded(flat)).hexdigest(),
        "prior_f64_le_sha256": hashlib.sha256(encoded(prior)).hexdigest(),
        "edges_f64_le_sha256": hashlib.sha256(encoded(shared["edges"])).hexdigest(),
        "model_identity": model_identity, "model_version": VERSION,
        "version_scope": "Explicit local witness model version; not a production model-registry version",
        "n_states": n, "theta": shared["theta"], "boundary": shared["boundary"],
        "binary_sha256": sha(binary), "source_identity": native_freeze["source_identity"],
        "candidate_horizons": [256.0, 2048.0], "candidate_seeds": [131101, 20261101, 17, 42],
        "selection_rule": "First deterministic candidate showing hit, recovery, reset and content switch. Every attempt retained. This is reachability/replay evidence, not an unbiased event-rate estimate.",
        "fixed_grid_contract": "No Q or grid change: content-major two blocks, active cells plus R1/R2 on the frozen fit's exact edges."}
    (destination/"PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")
    checks, receipts = [], []

    def check(name, value, **details):
        checks.append({"name": name, "pass": bool(value), **details})

    check("frozen_fit_identity", plan["fit_sha256"] == plan["frozen_fit_sha256"])
    check("frozen_native_binary", sha(binary) == native_freeze["binaries"]["hcsn-events-r13"])
    parsed = [float(x) for x in model.read_text().split()[2:]]
    check("text_export_preserves_every_float64_bit", encoded(parsed) == encoded(flat + prior))
    if not all(x["pass"] for x in checks):
        raise AssertionError(checks)

    def invoke(name, operation, source_path, script_text, last_argument, refused=False):
        script, checkpoint = destination/(name + ".script"), destination/(name + ".checkpoint")
        script.write_text(script_text)
        command = [str(binary), operation, str(source_path), str(script), str(checkpoint), str(last_argument)]
        response = subprocess.run(command, capture_output=True, text=True, check=False)
        archive = destination/(name + ".stdout.json.gz")
        archive.write_bytes(gzip.compress(response.stdout.encode(), mtime=0))
        receipt = {"name": name, "command": command, "returncode": response.returncode,
            "stderr": response.stderr, "stdout_archive": archive.name,
            "stdout_sha256": hashlib.sha256(response.stdout.encode()).hexdigest(),
            "checkpoint": checkpoint.name}
        receipts.append(receipt)
        if refused:
            check(name, response.returncode == 2 and not checkpoint.exists(), reason=response.stderr.strip())
            return None, checkpoint
        if response.returncode:
            raise AssertionError(receipt)
        data = json.loads(response.stdout)
        receipt.update(pid=data["pid"], time=data["time"], counts=data["counts"],
                       model_identity=data["model_identity"], checkpoint_sha256=sha(checkpoint))
        return data, checkpoint

    whole, whole_checkpoint, chosen = None, None, None
    for horizon in plan["candidate_horizons"]:
        for seed in plan["candidate_seeds"]:
            data, checkpoint = invoke(f"whole_t{int(horizon)}_seed{seed}", "init", model,
                                      f"advance {horizon:.17g}\n", seed)
            if all(x > 0 for x in data["counts"][1:]):
                whole, whole_checkpoint, chosen = data, checkpoint, {"horizon": horizon, "seed": seed}
                break
        if chosen is not None:
            break
    check("all_required_events_present", chosen is not None,
          attempted=[{"name": r["name"], "counts": r.get("counts")} for r in receipts])
    if chosen is None:
        report = {"plan": plan, "checks": checks, "process_receipts": receipts, "all_passed": False}
        (destination/"RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
        raise AssertionError("Predeclared witness candidates lacked event coverage")
    prefix, cp_prefix = invoke("prefix", "init", model, "advance 0.5\n", chosen["seed"])
    middle, cp_middle = invoke("middle", "resume", cp_prefix, "advance 63.5\n", VERSION)
    suffix, cp_suffix = invoke("suffix", "resume", cp_middle,
                               f"advance {chosen['horizon'] - 64.0:.17g}\n", VERSION)
    paths = [whole, prefix, middle, suffix]
    check("four_actual_distinct_processes", len({x["pid"] for x in paths}) == 4)
    check("whole_trace_equals_cross_process_trace", whole["jumps"] == prefix["jumps"] + middle["jumps"] + suffix["jumps"])
    check("final_checkpoint_bytes_exact", whole_checkpoint.read_bytes() == cp_suffix.read_bytes())
    check("all_paths_bind_exact_fitted_Q", all(x["model_identity"] == model_identity and
          x["model_version"] == VERSION and x["source_identity"] == plan["source_identity"] for x in paths))
    check("declared_final_clock", whole["time"] == suffix["time"] == chosen["horizon"])

    width, active = n // 2, n // 2 - 2
    state, last_time, counts, event_examples = whole["initial_state"], 0.0, [0] * 5, {}
    semantic = True
    for event in whole["jumps"]:
        a, b = event["from"] % width, event["to"] % width
        same = event["from"] // width == event["to"] // width
        if a == 0 and b == active and same:
            kind = "first_hit"
        elif a == active and b == active + 1 and same:
            kind = "refractory_phase"
        elif a == active + 1 and b < active:
            kind = "reset_keep" if same else "reset_switch"
        elif a < active and b < active and same and abs(a - b) == 1:
            kind = "active_jump"
        else:
            kind = "invalid"
        semantic = (semantic and event["from"] == state and q[event["from"]][event["to"]] > 0 and
            event["time"] > last_time and event["time"] <= chosen["horizon"] and
            event["model_version"] == VERSION and event["kind"] == kind and kind != "invalid")
        state, last_time = event["to"], event["time"]
        counts[0] += 1
        counts[1] += int(kind == "first_hit")
        counts[2] += int(kind == "refractory_phase")
        counts[3] += int(kind in ["reset_keep", "reset_switch"])
        counts[4] += int(kind == "reset_switch")
        event_examples.setdefault(kind, event)
    check("every_event_matches_fitted_Q_and_layout", semantic and state == whole["current"])
    check("independent_event_counts", counts == whole["counts"], counts=counts)
    invoke("refuse_wrong_version", "resume", cp_prefix, "advance 1\n", VERSION + 1, True)
    original = cp_prefix.read_text()
    body = original.rsplit("CHECKSUM ", 1)[0]
    lines = body.splitlines()
    lines[-1] = f"{int(lines[-1], 16) ^ 1:016x}"
    altered = "\n".join(lines) + "\n"
    changed = destination/"changed_Q.checkpoint"
    changed.write_text(altered + "CHECKSUM " + hashlib.sha256(altered.encode()).hexdigest() + "\n")
    invoke("refuse_changed_Q_identity", "resume", changed, "advance 1\n", VERSION, True)
    check("frozen_fit_and_binary_unchanged", sha(fitted_path) == plan["fit_sha256"] and sha(binary) == plan["binary_sha256"])
    report = {"schema": "hcsn-r13-learned-event-witness-v1", "plan": plan,
        "selected_witness": chosen, "counts": counts, "event_examples": event_examples,
        "final_state": whole["current"], "final_checkpoint_sha256": sha(whole_checkpoint),
        "checks": checks, "all_passed": all(x["pass"] for x in checks), "process_receipts": receipts,
        "scope": "Exact frozen fitted Q/prior exported without a parameter recomputation. A selected deterministic path witnesses actual events and fresh-process replay. No claim about event-frequency calibration, posterior Monte Carlo convergence, continuum correctness or new task confirmation."}
    (destination/"RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_passed": report["all_passed"], "checks": len(checks),
                      "selected_witness": chosen, "counts": counts}))
    if not report["all_passed"]:
        raise AssertionError("Learned event witness failed; see retained results")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT/"evidence/learned_event_witness")
    run(parser.parse_args().output)
