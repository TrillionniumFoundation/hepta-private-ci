"""Synthetic native-auditor contracts; no corpus, labels, Torch or model calls."""

import argparse
import copy
import gzip
import json
from pathlib import Path
import shutil
import time

import numpy as np

from ..field_bridge_v3_20261027.native_stream import NativeStreamBridge
from ..field_bridge_v3_20261027.runtime_controller import select
from . import native_session_audit as audit


def normalizer(width):
    return {"mean": [0.] * width, "scale": [1.] * width,
            "scope": "runtime_fit_only", "ddof": 0, "std_floor": 1e-6}


def controller(rep, library_sha):
    heads = []
    for stage, action in enumerate((1, 3, 4)):
        coefficient = np.zeros((89, 5))
        coefficient[-1] = [-0., -10., -10., -10., -10.]
        coefficient[-1, action], coefficient[stage * 16, action] = 0., 1.
        heads.append({"stage": stage, "normalizer": normalizer(88), "coefficient": coefficient.tolist()})
    return {"schema": "hepta.field-bridge-v3.runtime-controller.v1", "representation": rep,
        "feature_width": 88, "alpha": .01, "heads": heads, "authority": "DENY_ALL",
        "native_owner_integration": False, "native_library_sha256": library_sha,
        "transform": {"name": "k2", "k": 2, "normalizer": normalizer(16)}}


def fixture(library, cases):
    """Four causal paths stop at depths0/1/2 or finish3, under both native arms."""
    records, clock, tick_count = [], 1000, 0
    models = {rep: controller(rep, audit.digest(library)) for rep in audit.NATIVE}

    def now():
        nonlocal clock
        clock += 1
        return clock

    def append(record):
        value = {**record, "record_index": len(records), "committed_monotonic_ns": now()}
        records.append(value)
        return audit.bound(value)

    def event(index, depth, action=0):
        value = np.zeros(16)
        value[:8] = np.random.default_rng(29001 + index * 37 + depth).uniform(-.9, .9, 8)
        value[0] = -.9 if (depth < 2 and index == depth) or (depth == 2 and index == 3) else .7
        if depth:
            side = 2 * (audit.hashlib.sha256(f"{cases[index]}:{depth}".encode()).digest()[0] % 2) - 1
            value[8:12] = [1, side, 1 if index % 2 else -1, .3]
            value[12 + action - 1] = 1
        return value

    def media(index, depth):
        return {"case_id": cases[index], "depth": depth,
                "record_sha256": audit.bound({"case": cases[index], "depth": depth}), "readback_monotonic_ns": now()}

    with NativeStreamBridge(library) as bridge:
        for arm, policy in models.items():
            sessions = {i: bridge.open(case) for i, case in enumerate(cases)}
            active = list(range(len(cases)))
            histories = {i: [event(i, 0)] for i in active}
            delivered = {i: media(i, 0) for i in active}
            append({"kind": "initial_delivery", "role": "runtime_audit", "arm": arm, "case_ids": list(cases),
                    "media": [delivered[i] for i in active], "public_events": [histories[i][0].tolist() for i in active]})
            for stage in range(3):
                current = np.asarray([histories[i] for i in active])
                actions, summary = select(policy, current, bridge=bridge, sessions=[sessions[i] for i in active])
                commitment = append({"kind": "selected_actions_before_execution", "role": "runtime_audit", "arm": arm,
                    "case_ids": [cases[i] for i in active], "round": stage, "public_history": current.tolist(),
                    "selection": summary, "delivered_record_sha256": [delivered[i]["record_sha256"] for i in active],
                    "controller_sha256": audit.bound(policy)})
                survivors = []
                for action in (0, 1, 2, 3, 4):
                    group = [i for i, chosen in zip(active, actions, strict=True) if chosen == action]
                    if not group:
                        continue
                    if action == 0:
                        for i in group:
                            sessions[i].close()
                        continue
                    children = {i: media(i, stage + 1) for i in group}
                    packets = None
                    if stage < 2:
                        packets = []
                        for i in group:
                            child_event = event(i, stage + 1, action)
                            histories[i].append(child_event)
                            packets.append({"case_id": cases[i], "depth": stage + 1,
                                "output_record_sha256": children[i]["record_sha256"], "public_feedback": child_event[8:12].tolist(),
                                "after_readback_monotonic_ns": now(), "source_kind": "declared_simulated_external_verifier"})
                    append({"kind": "selected_revision_delivery", "role": "runtime_audit", "arm": arm,
                        "decision_sha256": commitment, "depth": stage + 1, "action": action,
                        "case_ids": [cases[i] for i in group], "media": [children[i] for i in group], "feedback": packets,
                        "future_or_unchosen_branches_executed": 0})
                    delivered.update(children)
                    if stage == 2:
                        for i in group:
                            sessions[i].close()
                    else:
                        survivors.extend(group)
                active = [i for i in active if i in survivors]
                if not active:
                    break
        tick_count = bridge.tick_count
        assert bridge.library.hepta_stream_live_sessions() == 0
    return models, records, tick_count


def replay(library, models, cases, records):
    with NativeStreamBridge(library) as bridge:
        verifier = audit.NativeReplay(bridge, models, cases)
        for record in records:
            verifier.process(record)
        return verifier.finish()


def reject(call):
    try:
        call()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("Expected independent native audit rejection")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def complete_fixture(out, source, library):
    fake_source, run = out / "source/field_bridge_v3_20261027", out / "run"
    fake_source.mkdir(parents=True)
    for name in ("native_stream.py", "native_stream.rs", "evidence/NATIVE_BUILD_RECEIPT.json"):
        destination = fake_source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    protocol = {"source_manifest_sha256": audit.bound("synthetic-manifest"),
                "runtime": {"conditions": ["synthetic"], "audit_pairs": 4}}
    write(fake_source / "PROTOCOL.json", protocol)
    sources = {str(p.relative_to(fake_source.parent)): audit.digest(p) for p in fake_source.rglob("*") if p.is_file()}
    freeze = {"registered_commit": "7" * 40, "allowed_phases": ["runtime-audit"], "source_files": sources,
        "protocol_sha256": audit.digest(fake_source / "PROTOCOL.json"), "native_library_sha256": audit.digest(library), "artifacts": {}}
    fixtures = {}
    for seed in audit.SEEDS:
        cases = [f"runtime_audit-{seed}-synthetic-{i:06d}" for i in range(4)]
        models, records, ticks = fixture(library, cases)
        fitted = {"models": {"current": {"representation": "current"}, "history": {"representation": "history"}, **models},
            "fixed_policy": {"node": 0, "actions": []}, "fit_identities": {"metadata": {"seed": seed, "profile": "frozen",
            "protocol_sha256": freeze["protocol_sha256"], "source_manifest_sha256": protocol["source_manifest_sha256"],
            "model_parameter_sha256": audit.bound("synthetic-model"), "reward_observer_parameter_sha256": audit.bound("synthetic-observer")}}}
        fit_dir = run / "runtime/fit" / f"{seed}-frozen"
        write(fit_dir / "READOUTS.json", fitted)
        write(fit_dir / "COMPLETE.json", {"files": {"READOUTS.json": audit.digest(fit_dir / "READOUTS.json")}})
        for name in ("READOUTS.json", "COMPLETE.json"):
            freeze["artifacts"][str((fit_dir / name).relative_to(run))] = audit.digest(fit_dir / name)
        fixtures[seed] = fitted, records, ticks
    freeze_path = run / "RUNTIME_AUDIT_FREEZE.json"
    write(freeze_path, freeze)
    for seed, (fitted, records, ticks) in fixtures.items():
        parent = run / "runtime/audit" / f"{seed}-frozen"
        selected = parent / "selected"
        selected.mkdir(parents=True)
        with gzip.open(selected / "events.jsonl.gz", "wt") as stream:
            for row in records:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        (selected / "media.h3m").write_bytes(b"synthetic-auditor-fixture-no-model-or-media-decoding")
        with gzip.open(selected / "rows.jsonl.gz", "wt") as stream:
            stream.write("{}\n")
        models = {"fixed": {"kind": "fixed", **fitted["fixed_policy"]}, **fitted["models"]}
        result = {"seed": seed, "profile": "frozen", "role": "runtime_audit", "episodes": 20,
            "model_parameter_sha256": audit.bound("synthetic-model"),
            "observer_parameter_sha256": {"reward": audit.bound("synthetic-observer")},
            "arms": ["fixed", "current", "history", "native", "reset_native"],
            "source_manifest_sha256": protocol["source_manifest_sha256"], "controller_sha256": {k: audit.bound(v) for k, v in models.items()},
            "resources": {"native_tick_calls": ticks, "native_ns": sum(row["selection"]["native_ns"] for row in records
                if row["kind"] == "selected_actions_before_execution")},
            "authority": "DENY_ALL", "native_owner_integration": False, "unchosen_continuations_executed": 0,
            "files": {name: audit.digest(selected / name) for name in ("events.jsonl.gz", "rows.jsonl.gz", "media.h3m")}}
        write(selected / "COMPLETE.json", result)
        write(parent / "START.json", {"phase": "runtime-audit", "seed": seed, "profile": "frozen",
            "freeze_sha256": audit.digest(freeze_path), "registered_commit": freeze["registered_commit"],
            "protocol_sha256": freeze["protocol_sha256"], "native_library_sha256": freeze["native_library_sha256"], "source_files": sources})
        write(parent / "COMPLETE.json", {**result, "files": {str(p.relative_to(parent)): audit.digest(p) for p in parent.rglob("*") if p.is_file()}})
    return run, fake_source, freeze_path


def main(library, source, out):
    started = time.perf_counter_ns()
    out.mkdir(parents=True, exist_ok=False)
    cases = [f"synthetic-native-audit-case-{i}" for i in range(4)]
    models, records, ticks = fixture(library, cases)
    result = replay(library, models, cases, records)
    assert result["verification_native_ticks"] == ticks == 36
    assert {arm: values["sessions"] for arm, values in result["per_arm"].items()} == {arm: 4 for arm in models}
    assert result["per_arm"]["reset_native"]["reset_calls"] == 5
    selection_index = next(i for i, row in enumerate(records) if row["kind"] == "selected_actions_before_execution")
    rejection_checks = 0
    for key in ("activation_q24", "eligibility_q24", "threshold_q24", "drive_q24", "checkpoint_before", "checkpoint_after",
                "input_digest", "temporal_digest", "source_pin", "authority", "sequence", "logical_clock_micros"):
        corrupted = copy.deepcopy(records)
        tick = corrupted[selection_index]["selection"]["native_records"][0]["ticks"][0]
        value = tick[key]
        tick[key] = [value[0] + 1, *value[1:]] if isinstance(value, list) else value + 1 if isinstance(value, int) else "x" + value[1:]
        reject(lambda: replay(library, models, cases, corrupted))
        rejection_checks += 1
    for mutate in (
        lambda row: row["selection"].__setitem__("feature_matrix_sha256", "0" * 64),
        lambda row: row["selection"]["native_records"][0].__setitem__("reset_before_round", True),
        lambda row: row["selection"]["native_records"][0]["transformed_current_event"].__setitem__(0, .123),
        lambda row: row["selection"]["action_indices"].__setitem__(0, 4),
        lambda row: row["selection"].__setitem__("native_tick_calls", 0),
        lambda row: row.__setitem__("controller_sha256", "0" * 64),
        lambda row: row.__setitem__("case_ids", [row["case_ids"][0]] * len(row["case_ids"])),
    ):
        corrupted = copy.deepcopy(records)
        mutate(corrupted[selection_index])
        reject(lambda: replay(library, models, cases, corrupted))
        rejection_checks += 1
    revision = next(i for i, row in enumerate(records) if row["kind"] == "selected_revision_delivery")
    corrupted = copy.deepcopy(records)
    corrupted[revision]["feedback"][0]["after_readback_monotonic_ns"] = 1
    reject(lambda: replay(library, models, cases, corrupted))
    rejection_checks += 1
    reject(lambda: replay(library, models, cases, records[:-1]))
    rejection_checks += 1
    reject(lambda: audit.audit(out / "not-completed", "frozen", source, out / "missing-freeze", library))
    rejection_checks += 1
    run, fake_source, freeze = complete_fixture(out, source, library)
    complete = audit.audit(run, "frozen", fake_source, freeze, library)
    assert complete["verification_native_ticks"] == 108 and complete["generator_forward_calls"] == complete["observer_forward_calls"] == 0
    damaged = run / "runtime/fit/17-frozen/READOUTS.json"
    damaged.write_bytes(damaged.read_bytes() + b" ")
    reject(lambda: audit.audit(run, "frozen", fake_source, freeze, library))
    rejection_checks += 1
    receipt = {"schema": "hepta.field-bridge.v3.native-session-audit-contract.1", "passed": True,
        "synthetic_only": True, "registered_source_roles_opened": False, "models_or_observers_loaded": False,
        "synthetic_exact_replay": result, "three_seed_inventory_fixture_verification_ticks": 108,
        "corruption_or_boundary_rejections": rejection_checks, "source_sha256": audit.digest(__file__),
        "auditor_source_sha256": audit.digest(audit.__file__), "native_library_sha256": audit.digest(library),
        "wall_ns": time.perf_counter_ns() - started}
    write(out / "NATIVE_SESSION_AUDIT_CONTRACT.json", receipt)
    print(json.dumps({"passed": True, "corruption_or_boundary_rejections": rejection_checks,
                      "receipt_sha256": audit.digest(out / "NATIVE_SESSION_AUDIT_CONTRACT.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    main(args.library, args.source, args.out)
