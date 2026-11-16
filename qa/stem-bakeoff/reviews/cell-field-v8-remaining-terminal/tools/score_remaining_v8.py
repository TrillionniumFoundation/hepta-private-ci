"""Separate historical DEV scoring after all96 controls and replay are sealed.

Only the previously disclosed V5/V6 selected source roles enter these metrics.
No private evaluation key, new source cohort or confirmatory outcome is used.
The external entry rule authorizes at most preparation of a later confirmation.
"""

import argparse
from itertools import product
import json
from pathlib import Path
import sys
import time

import numpy as np

from audit_remaining_v8 import validate_sources
from remaining_audit_core_v8 import (METHODS, bind_execution_identity, canonical, check_seal, digest, file_hash,
    load_policy_record, read, require, required_hash)
from remaining_dev_statistics_v8 import AXES, summarize, validate_entry


def metrics(state, pair):
    x, y = pair
    probabilities = state.head.predict_proba(x)
    require(len(y) == 512 and probabilities.shape == (512, 4) and np.isfinite(probabilities).all()
        and np.all(probabilities >= 0) and np.allclose(probabilities.sum(axis=1), 1., rtol=0., atol=1e-12),
        "512 ordered historical sources and finite four-class predictions")
    nll = -np.log(np.maximum(probabilities[np.arange(512), y], np.finfo(float).tiny))
    correct = probabilities.argmax(axis=1) == y
    return {"nll": float(nll.mean()), "accuracy": float(correct.mean()), "sources": 512}, nll, correct


def score(workspace, run, grid, pins, audit, audit_sha256, entry_rule, entry_sha256, output):
    workspace, run, grid, pins_path, audit_path, entry_path, output = map(lambda p: Path(p).resolve(),
        (workspace, run, grid, pins, audit, entry_rule, output))
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    require(not output.exists() and run not in output.parents and audit_path.parent not in output.parents,
        "new scoring directory outside control and replay evidence")
    require(file_hash(audit_path) == required_hash({"audit": audit_sha256}, "audit")
        and file_hash(entry_path) == required_hash({"entry": entry_sha256}, "entry"), "external audit and prospective entry-rule byte pins")
    qualification, rule, pins = read(audit_path), read(entry_path), read(pins_path)
    expected_seal = required_hash(pins, "control_seal_sha256")
    require(qualification["schema"] == "hepta.independent-remaining-terminal-audit.v8"
        and qualification["status"] == "PASS" and not qualification["audit_failures"]
        and qualification["output_slots"] == 96 and qualification["control_seal_sha256"] == expected_seal
        and qualification["protocol_sha256"] == pins["protocol_sha256"]
        and qualification["source_sha256"] == pins["source_sha256"]
        and qualification["source_commit"] == pins["source_commit"]
        and qualification["selection_labels_accessed"] is False, "independent complete planning-only replay must precede DEV labels")
    check_seal(run, expected_seal)
    code, sources = validate_sources(workspace, run, pins)
    require(file_hash(run/"protocol.json") == pins["protocol_sha256"], "frozen scientific protocol unchanged")
    report, protocol = read(run/"report.json"), read(run/"protocol.json")
    bind_execution_identity(report, pins)
    validate_entry(rule, report)
    require(file_hash(audit_path.parent/"cases.json") == qualification["case_census_sha256"], "full96 independently audited cases")
    audit_rows = read(audit_path.parent/"cases.json")
    audited = {(r["fit"], r["method"]): r for r in audit_rows}
    expected = {(f"{v}-{t}-seed{s}-{h}", m) for v, t, h, s in product(*AXES) for m in METHODS}
    require(len(audit_rows) == len(audited) == 96 and set(audited) == expected
        and all(r["audit_status"] == "PASS" for r in audit_rows), "no dropped or failed replay slots")
    require(file_hash(grid/"protocol.json") == protocol["base_inputs"]["protocol_sha256"]
        and file_hash(grid/"development_seal.json") == protocol["base_inputs"]["seal_sha256"], "original historical warmup family")
    for name, sha in qualification["auditor_sources"].items():
        require(Path(name).name == name and file_hash(Path(__file__).with_name(name)) == sha, "exact audited implementation")
    scorer_files = ("score_remaining_v8.py", "remaining_dev_statistics_v8.py", "remaining_audit_core_v8.py", "audit_remaining_v8.py")
    scorer_sources = {name: file_hash(Path(__file__).with_name(name)) for name in scorer_files}
    # No historical selection loader is imported or invoked before every bound
    # control/replay/source/entry prerequisite above has passed.
    sys.path.insert(0, str(code))
    from cell_field_development_data_v7 import load_development
    from cell_field_common_run_v8 import load_warmup
    from cell_field_state import CellTrainingState
    base, data, provenance, identities, arrays = read(grid/"protocol.json"), {}, {}, {}, {}
    for v, t in product(*AXES[:2]):
        value = load_development(v, t, workspace/f"pft-data-{v}/cohorts",
            workspace/f"pft-features-{v}", workspace/"pft-data-v5/inputs")
        data[v, t] = value
        recorded = read(grid/"inputs"/f"{v}-{t}.json")
        actual = json.loads(json.dumps(value["provenance"]))
        require(set(recorded) == set(actual) and all(recorded[k] == actual[k]
            for k in actual if k not in {"cpu_ns", "wall_ns"}), "all original historical source/role identities")
        role_identity = {role: value["role_metadata"][name] for role, name in (("future", "future_test"), ("old", "old_test"))}
        identities[v, t] = digest(role_identity)
        provenance[f"{v}-{t}"] = {"selection_sources_sha256": identities[v, t],
            "historical_provenance": actual, "only_previously_disclosed_roles_scored": True}
        for role, meta in role_identity.items():
            require(len(meta["component_ids"]) == len(set(meta["component_ids"])) == 512, "512 unique original role components")
            arrays[f"{v}-{t}__{role}__components"] = np.asarray(meta["component_ids"])
    rows, warmups = [], []
    for v, t, h, s in product(*AXES):
        fit, inputs = f"{v}-{t}-seed{s}-{h}", data[v, t]
        warm, _ = load_warmup(workspace, base, fit, v, inputs["split"]["current_train"])
        old_summary, warm_losses, correct = metrics(warm, inputs["selection"]["old"])
        warm_key = fit+"__warmup_old_nll"
        arrays[warm_key] = warm_losses
        arrays[fit+"__warmup_old_correct"] = correct
        warmups.append({"fit": fit, "old": old_summary, "state_sha256": warm.digest()})
        for method in METHODS:
            directory, checked = run/fit/method, audited[fit, method]
            require(file_hash(directory/"result.json") == checked["original_result_sha256"], "unchanged audited original result")
            record = load_policy_record(directory, compressed=len(sources) == 129)
            row = {"fit": fit, "version": v, "task": t, "head": h, "seed": s, "method": method,
                "status": record["status"], "completed_steps": record["completed_steps"],
                "available": checked["available"], "complete32": checked["completed"] and not checked["actual_errors"],
                "actual_errors": checked["actual_errors"], "cpu_ns": record["policy_call_cpu_ns"],
                "wall_ns": record["policy_call_wall_ns"], "selection_sources_sha256": identities[v, t],
                "warmup_old_nll_key": warm_key, "array_keys": {}, "future": None, "old": None,
                "evaluation_scope": "actual retained prefix; only complete32 rows enter paired endpoint gates"}
            if row["available"]:
                n = record["completed_steps"]
                require(record["terminal_checkpoint"] == "checkpoints/"+str(n), "exact audited terminal checkpoint path")
                terminal = CellTrainingState.load(directory/record["terminal_checkpoint"], warm.bindings,
                    warm.protocol, warm.contexts, checked["terminal_state_sha256"])
                for role in ("future", "old"):
                    summary, loss, correct = metrics(terminal, inputs["selection"][role])
                    row[role] = summary
                    for kind, values in (("nll", loss), ("correct", correct)):
                        key = fit+"__"+method+"__"+role+"_"+kind
                        row["array_keys"][role+"_"+kind] = key
                        arrays[key] = values
            rows.append(row)
    result = summarize(rows, arrays, qualification["full_field_parities"])
    check_seal(run, expected_seal)
    validate_sources(workspace, run, pins)
    require(file_hash(entry_path) == entry_sha256 and file_hash(audit_path) == audit_sha256
        and {n: file_hash(Path(__file__).with_name(n)) for n in scorer_files} == scorer_sources,
        "entry rule, independent audit and scorer source unchanged")
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output/"per-source-dev-statistics.npz", **arrays)
    (output/"records.json").write_bytes(canonical(rows)+b"\n")
    (output/"historical-provenance.json").write_bytes(canonical(provenance)+b"\n")
    summary = {"schema": "hepta.remaining-terminal-historical-development-results.v8", **result,
        "protocol_sha256": pins["protocol_sha256"], "source_sha256": pins["source_sha256"],
        "source_commit": pins["source_commit"], "control_seal_sha256": expected_seal,
        "independent_audit_sha256": audit_sha256, "confirmation_entry_rule_sha256": entry_sha256,
        "scorer_sources": scorer_sources, "records": 96, "original_warmups": warmups,
        "records_sha256": file_hash(output/"records.json"),
        "per_source_statistics_sha256": file_hash(output/"per-source-dev-statistics.npz"),
        "historical_provenance_sha256": file_hash(output/"historical-provenance.json"),
        "control_common_input_preparation": report["common_input_preparation"],
        "new_source_cohort_selected": False, "private_evaluation_key_accessed": False,
        "control_outputs_unchanged_after_scoring": True,
        "evaluation_cpu_ns": time.process_time_ns()-cpu, "evaluation_wall_ns": time.perf_counter_ns()-began}
    (output/"evaluation.json").write_bytes(canonical(summary)+b"\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "run", "grid", "pins", "audit", "audit-sha256", "entry-rule", "entry-sha256", "output"):
        parser.add_argument("--"+name, required=True)
    value = score(**vars(parser.parse_args()))
    print(json.dumps({k: value[k] for k in ("disposition", "counts", "confirmation_entry_passed")}))
