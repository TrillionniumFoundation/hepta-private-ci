"""Independent replay of completed selected native sessions; no model import.

The media auditor independently reconstructs public events from actual delivered
bytes. This auditor binds those journals, re-encodes their causal histories, and
executes the pinned original kernel. All computation is additional verification.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

import numpy as np


SEEDS = (17, 29, 43)
NATIVE = ("native", "reset_native")
Q24 = 1 << 24
TIMINGS = {"native_ns", "bridge_roundtrip_ns"}
SOURCE_PIN = "63f198ad85cfa2aa579032256355f446cfe793a0"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def bound(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def array_digest(values):
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def member(root, name):
    path = (Path(root) / name).resolve()
    require(path.is_relative_to(Path(root).resolve()) and path.is_file(), "Unsafe or missing bound member")
    return path


def inventory(directory):
    directory = Path(directory)
    require((directory / "COMPLETE.json").is_file() and not (directory / "FAILED.json").exists(),
            "Only a successfully completed runtime stage may be audited")
    complete = read(directory / "COMPLETE.json")
    actual = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
    require(actual == {*complete["files"], "COMPLETE.json"}, "Completed runtime inventory changed")
    for name, identity in complete["files"].items():
        require(digest(member(directory, name)) == identity, f"Runtime member changed: {name}")
    return complete


def bridge_type(source):
    path = Path(source) / "native_stream.py"
    spec = importlib.util.spec_from_file_location("v3_pinned_native_replay_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.SOURCE_PIN == SOURCE_PIN and module.Q24 == Q24, "Original native pin or Q24 convention differs")
    return module.NativeStreamBridge


def history_array(value, rows, stage):
    values = np.asarray(value, dtype=np.float64)
    require(values.shape == (rows, stage + 1, 16) and np.isfinite(values).all() and np.abs(values).max() <= 1,
            "Invalid bounded causal history")
    require(np.all(values[:, 0, 8:] == 0), "Root history contains feedback or an unexecuted action")
    if stage:
        later = values[:, 1:]
        require(np.all(later[:, :, 8] == 1) and np.all(np.abs(later[:, :, 9:11]) == 1)
                and np.all((later[:, :, 12:] == 0) | (later[:, :, 12:] == 1))
                and np.all(later[:, :, 12:].sum(-1) == 1), "Invalid later feedback/action event")
    return values


def transform_event(event, controller):
    spec = controller["transform"]
    require((spec["name"], spec["k"]) in (("raw", None), ("k1", 1), ("k2", 2), ("k4", 4)),
            "Unknown registered event transform")
    mean, scale = (np.asarray(spec["normalizer"][key], dtype=np.float64) for key in ("mean", "scale"))
    require(mean.shape == scale.shape == (16,) and np.isfinite(mean).all() and np.isfinite(scale).all()
            and np.all(scale >= 1e-6) and spec["normalizer"]["scope"] == "runtime_fit_only",
            "Invalid frozen fit-only event normalization")
    return event.copy() if spec["k"] is None else np.clip((event - mean) / scale / spec["k"], -1, 1)


def head_actions(controller, stage, features):
    head = controller["heads"][stage]
    mean, scale = (np.asarray(head["normalizer"][key], dtype=np.float64) for key in ("mean", "scale"))
    coefficient = np.asarray(head["coefficient"], dtype=np.float64)
    require(mean.shape == scale.shape == (88,) and coefficient.shape == (89, 5)
            and np.isfinite(mean).all() and np.isfinite(scale).all() and np.all(scale >= 1e-6)
            and np.isfinite(coefficient).all() and head["stage"] == stage
            and head["normalizer"]["scope"] == "runtime_fit_only", "Invalid frozen native stage head")
    augmented = np.column_stack(((features - mean) / scale, np.ones(len(features))))
    scores = np.einsum("bi,ij->bj", augmented, coefficient, optimize=False)
    require(np.isfinite(scores).all(), "Nonfinite independently recomputed action score")
    return scores.argmax(1).tolist()


class NativeReplay:
    """Read-only event replay with one isolated original checkpoint per episode."""

    def __init__(self, bridge, controllers, expected_cases, role="runtime_audit"):
        self.bridge, self.role, self.expected_cases = bridge, role, set(expected_cases)
        self.controllers = {arm: model for arm, model in controllers.items() if model.get("representation") in NATIVE}
        require(self.controllers, "No native policies supplied for verification")
        self.hashes = {arm: bound(model) for arm, model in self.controllers.items()}
        for model in self.controllers.values():
            require(model["schema"] == "hepta.field-bridge-v3.runtime-controller.v1" and model["authority"] == "DENY_ALL"
                    and model["native_owner_integration"] is False and model["feature_width"] == 88
                    and model["native_library_sha256"] == bridge.binary_sha256 and len(model["heads"]) == 3,
                    "Policy authority, feature or native identity differs")
        self.live, self.seen, self.closed = {}, set(), set()
        self.counts = {arm: Counter() for arm in self.controllers}
        self.record_index, self.last_time = 0, 0
        self.coverage = hashlib.sha256()
        self.stable_ticks = hashlib.sha256()
        self.tick_start, self.native_start, self.roundtrip_start = bridge.tick_count, bridge.native_ns, bridge.roundtrip_ns

    def process(self, row):
        require(row["record_index"] == self.record_index and row["committed_monotonic_ns"] >= self.last_time > -1,
                "Journal index or chronological commitment differs")
        self.record_index += 1
        self.last_time = row["committed_monotonic_ns"]
        require(row["role"] == self.role, "Journal source role differs")
        arm, kind = row["arm"], row["kind"]
        require(kind in ("initial_delivery", "selected_actions_before_execution", "selected_revision_delivery"),
                "Unknown selected-path event kind")
        if arm not in self.controllers:
            if kind == "selected_actions_before_execution":
                selection = row["selection"]
                require(selection["native_tick_calls"] == 0 and not selection.get("native_records"),
                        "A non-native arm recorded native execution")
            return
        cases = row["case_ids"]
        require(len(cases) > 0 and len(cases) == len(set(cases)) and set(cases) <= self.expected_cases,
                "Native event has duplicate or out-of-scope cases")
        if kind == "initial_delivery":
            self.initial(row)
        elif kind == "selected_actions_before_execution":
            self.selection(row)
        else:
            self.revision(row)

    def initial(self, row):
        arm, cases = row["arm"], row["case_ids"]
        events = history_array(np.asarray(row["public_events"])[:, None], len(cases), 0)[:, 0]
        require(len(row["media"]) == len(cases), "Initial media coverage differs")
        for case, event, media in zip(cases, events, row["media"], strict=True):
            key = (arm, case)
            require(key not in self.seen and media["case_id"] == case and media["depth"] == 0
                    and 0 < media["readback_monotonic_ns"] <= row["committed_monotonic_ns"],
                    "Duplicate episode or invalid initial delivery chronology")
            self.seen.add(key)
            self.live[key] = {"session": self.bridge.open(case), "history": b"", "first": event.copy(),
                "round": 0, "pending": False, "delivered": media["record_sha256"], "feedback": None}
            self.counts[arm]["sessions"] += 1

    def selection(self, row):
        arm, cases, stage, summary = row["arm"], row["case_ids"], row["round"], row["selection"]
        controller, identity = self.controllers[arm], self.hashes[arm]
        require(type(stage) is int and 0 <= stage < 3, "Selection exceeds the registered three decisions")
        history = history_array(row["public_history"], len(cases), stage)
        require(row["controller_sha256"] == identity == summary["controller_sha256"]
                and summary["representation"] == controller["representation"] and summary["round"] == stage
                and summary["rows"] == len(cases) and summary["native_tick_calls"] == 2 * len(cases)
                and summary["public_history_sha256"] == array_digest(history)
                and summary["target_accesses"] == summary["future_events_accessed"] == 0
                and summary["authority"] == "DENY_ALL" and summary["native_owner_integration"] is False
                and summary["requires_calibration"] is True and summary["native_receipt_path"] is None,
                "Selection identity, resource, authority or causal-access declaration differs")
        records = summary["native_records"]
        require(len(records) == len(cases) == len(row["delivered_record_sha256"]), "Native decision coverage differs")
        features, recorded_ns = [], 0
        for index, (case, h, record) in enumerate(zip(cases, history, records, strict=True)):
            key, raw = (arm, case), h.astype("<f8").tobytes()
            require(key in self.live, "Native decision resumed a closed or unopened episode")
            state = self.live[key]
            require(not state["pending"] and state["round"] == stage and state["history"] == raw[:-128]
                    and np.array_equal(h[0], state["first"]) and state["session"].clock == 2 * stage
                    and row["delivered_record_sha256"][index] == state["delivered"],
                    "Native state, delivered output or immutable history prefix differs")
            if stage:
                require(np.array_equal(h[-1, 8:12], state["feedback"]) and h[-1, 12:].argmax() + 1 == state["action"],
                        "A later event does not follow its own selected action and delivered feedback")
            transformed = transform_event(h[-1], controller)
            reset = controller["representation"] == "reset_native" and stage > 0
            require(record["case"] == case and record["round"] == stage and record["controller_sha256"] == identity
                    and np.array_equal(record["raw_history"], h) and record["raw_history_sha256"] == array_digest(h)
                    and np.array_equal(record["transformed_current_event"], transformed)
                    and record["reset_before_round"] is reset and len(record["ticks"]) == 2,
                    "Native record input, transform or reset binding differs")
            readback = hashlib.sha256(b"hepta.field-v3.public-history.v1" + bytes.fromhex(bound(controller["transform"])) + raw).hexdigest()
            encoded = np.rint(transformed * Q24).astype(np.int64).tolist()
            if reset:
                state["session"].reset()
                self.counts[arm]["reset_calls"] += 1
            for start, expected in zip((0, 8), record["ticks"], strict=True):
                native, actual = state["session"].tick(encoded[start:start + 8], readback_digest=readback)
                stable = {k: v for k, v in actual.items() if k not in TIMINGS}
                require(stable == {k: v for k, v in expected.items() if k not in TIMINGS},
                        "Original-kernel state, digest, signed drive or authority receipt differs")
                require(all(type(expected[k]) is int and expected[k] >= 0 for k in TIMINGS), "Invalid recorded native timing")
                self.stable_ticks.update(canonical({"arm": arm, "tick": stable}) + b"\n")
                recorded_ns += expected["native_ns"]
            padded = np.zeros(48)
            padded[:h.size] = h.reshape(-1)
            features.append(np.r_[padded, native])
            state.update(history=raw, round=stage + 1, decision=bound(row), decision_time=row["committed_monotonic_ns"])
        features = np.asarray(features)
        actions = head_actions(controller, stage, features)
        require(summary["feature_matrix_sha256"] == array_digest(features)
                and summary["action_indices"] == actions == [r["action"] for r in records]
                and summary["native_ns"] == recorded_ns, "Native features, selected action or timing aggregation differs")
        self.counts[arm].update(decisions=len(cases), ticks=2 * len(cases), selection_batches=1,
                                recorded_native_ns=recorded_ns)
        self.counts[arm][f"round_{stage}_decisions"] += len(cases)
        for case, action, h in zip(cases, actions, history, strict=True):
            key, state = (arm, case), self.live[(arm, case)]
            state.update(action=action, pending=action != 0)
            self.coverage.update(canonical({"arm": arm, "case": case, "round": stage,
                "controller_sha256": identity, "history_sha256": array_digest(h), "action": action}) + b"\n")
            if action == 0:
                self.close_case(key)

    def revision(self, row):
        arm, depth, action = row["arm"], row["depth"], row["action"]
        require(type(depth) is int and 1 <= depth <= 3 and action in (1, 2, 3, 4)
                and row["future_or_unchosen_branches_executed"] == 0, "Illegal selected revision")
        require(len(row["media"]) == len(row["case_ids"]) and (row["feedback"] is None if depth == 3
                else len(row["feedback"]) == len(row["case_ids"])), "Revision delivery coverage differs")
        for index, (case, media) in enumerate(zip(row["case_ids"], row["media"], strict=True)):
            key = (arm, case)
            require(key in self.live, "A selected revision follows a closed or unopened episode")
            state = self.live[key]
            require(state["pending"] and state["round"] == depth and state["action"] == action
                    and row["decision_sha256"] == state["decision"] and media["case_id"] == case and media["depth"] == depth
                    and state["decision_time"] <= media["readback_monotonic_ns"] <= row["committed_monotonic_ns"],
                    "Revision differs from its earlier committed action")
            state.update(pending=False, delivered=media["record_sha256"])
            if depth == 3:
                self.close_case(key)
                continue
            packet = row["feedback"][index]
            values = np.asarray(packet["public_feedback"], dtype=np.float64)
            side = 2 * (hashlib.sha256(f"{case}:{depth}".encode()).digest()[0] % 2) - 1
            require(packet["case_id"] == case and packet["depth"] == depth
                    and packet["output_record_sha256"] == state["delivered"]
                    and packet["source_kind"] == "declared_simulated_external_verifier"
                    and media["readback_monotonic_ns"] <= packet["after_readback_monotonic_ns"] <= row["committed_monotonic_ns"]
                    and values.shape == (4,) and np.isfinite(values).all() and abs(values).max() <= 1
                    and values[0] == 1 and values[1] == side and values[2] in (-1, 1),
                    "Feedback scope, schedule or post-delivery chronology differs")
            state["feedback"] = values
            self.counts[arm]["feedback_packets"] += 1

    def close_case(self, key):
        state = self.live.pop(key)
        require(2 <= state["session"].clock <= 6, "Native episode work ceiling differs")
        self.counts[key[0]][f"sessions_with_{state['session'].clock}_ticks"] += 1
        state["session"].close()
        self.closed.add(key)

    def finish(self):
        expected = {(arm, case) for arm in self.controllers for case in self.expected_cases}
        require(not self.live and self.seen == self.closed == expected, "Native episode or terminal coverage is incomplete")
        require(not self.bridge._sessions and self.bridge.library.hepta_stream_live_sessions() == 0, "Leaked replay native state")
        ticks = self.bridge.tick_count - self.tick_start
        require(ticks == sum(v["ticks"] for v in self.counts.values()), "Uncounted verification ticks")
        return {"per_arm": {arm: dict(values) for arm, values in self.counts.items()},
                "journal_records": self.record_index, "decision_coverage_sha256": self.coverage.hexdigest(),
                "stable_tick_ledger_sha256": self.stable_ticks.hexdigest(),
                "verification_native_ticks": ticks, "verification_native_ns": self.bridge.native_ns - self.native_start,
                "verification_bridge_roundtrip_ns": self.bridge.roundtrip_ns - self.roundtrip_start}


def audit(run, profile, source, freeze_path, native=None):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    run, source, freeze_path = Path(run).resolve(), Path(source).resolve(), Path(freeze_path).resolve()
    parents = {seed: run / "runtime/audit" / f"{seed}-{profile}" for seed in SEEDS}
    require(all((path / "COMPLETE.json").is_file() and (path / "selected/COMPLETE.json").is_file()
                and not (path / "FAILED.json").exists() for path in parents.values()),
            "Wait for all three completed seed/profile signals before opening any outcome journal")
    freeze_identity = digest(freeze_path)
    freeze, protocol = read(freeze_path), read(source / "PROTOCOL.json")
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]) and "runtime-audit" in freeze["allowed_phases"]
            and freeze["protocol_sha256"] == digest(source / "PROTOCOL.json"), "Invalid pre-outcome runtime audit freeze")
    for name, identity in freeze["source_files"].items():
        require(digest(member(source.parent, name)) == identity, f"Frozen source differs: {name}")
    for name, identity in freeze["artifacts"].items():
        require(digest(member(run, name)) == identity, f"Frozen prior-stage artifact differs: {name}")
    build = read(source / "evidence/NATIVE_BUILD_RECEIPT.json")
    library = Path(native or build["binary"]).resolve()
    require(digest(library) == freeze["native_library_sha256"] == build["binary_sha256"]
            and build["source_sha256"] == digest(source / "native_stream.rs")
            and build["python_source_sha256"] == digest(source / "native_stream.py")
            and build["original_source_commit"] == SOURCE_PIN and build["kernel_and_configuration_unchanged"] is True,
            "Native binary, wrapper source or original kernel build identity differs")
    results = {}
    with bridge_type(source)(library, freeze["native_library_sha256"]) as bridge:
        for seed, parent in parents.items():
            complete, selected, start = inventory(parent), inventory(parent / "selected"), read(parent / "START.json")
            require({k: v for k, v in complete.items() if k != "files"} == {k: v for k, v in selected.items() if k != "files"},
                    "Parent and selected COMPLETE metadata differ")
            require(start["phase"] == "runtime-audit" and start["seed"] == seed and start["profile"] == profile
                    and start["freeze_sha256"] == digest(freeze_path) and start["registered_commit"] == freeze["registered_commit"]
                    and start["protocol_sha256"] == freeze["protocol_sha256"]
                    and start["native_library_sha256"] == bridge.binary_sha256
                    and all(freeze["source_files"].get(k) == v for k, v in start["source_files"].items()),
                    "Execution source/freeze/native binding differs")
            fit_dir = run / "runtime/fit" / f"{seed}-{profile}"
            for name in ("READOUTS.json", "COMPLETE.json"):
                require(freeze["artifacts"].get(str((fit_dir / name).relative_to(run))) == digest(fit_dir / name),
                        "Selected controllers were not bound before audit outcomes")
            fit = read(fit_dir / "READOUTS.json")
            meta = fit["fit_identities"]["metadata"]
            require(meta["seed"] == seed and meta["profile"] == profile and meta["protocol_sha256"] == freeze["protocol_sha256"]
                    and meta["source_manifest_sha256"] == protocol["source_manifest_sha256"]
                    and meta["model_parameter_sha256"] == selected["model_parameter_sha256"]
                    and meta["reward_observer_parameter_sha256"] == selected["observer_parameter_sha256"]["reward"],
                    "Fitted and selected generator/public observer scope differs")
            controllers = {"fixed": {"kind": "fixed", **fit["fixed_policy"]}, **fit["models"]}
            require(selected["seed"] == seed and selected["profile"] == profile and selected["role"] == "runtime_audit"
                    and selected["source_manifest_sha256"] == protocol["source_manifest_sha256"]
                    and selected["arms"] == ["fixed", "current", "history", "native", "reset_native"]
                    and selected["controller_sha256"] == {k: bound(v) for k, v in controllers.items()}
                    and selected["authority"] == "DENY_ALL" and selected["native_owner_integration"] is False
                    and selected["unchosen_continuations_executed"] == 0, "Completed selected policy or authority scope differs")
            cases = {f"runtime_audit-{seed}-{condition}-{i:06d}" for condition in protocol["runtime"]["conditions"]
                     for i in range(protocol["runtime"]["audit_pairs"])}
            require(selected["episodes"] == 5 * len(cases), "Selected episode count differs from registration")
            replay = NativeReplay(bridge, controllers, cases)
            events = parent / "selected/events.jsonl.gz"
            inputs = {"parent_complete_sha256": parent / "COMPLETE.json", "selected_complete_sha256": parent / "selected/COMPLETE.json",
                      "events_sha256": events, "readouts_sha256": fit_dir / "READOUTS.json", "fit_complete_sha256": fit_dir / "COMPLETE.json"}
            identities = {key: digest(path) for key, path in inputs.items()}
            require(identities["events_sha256"] == selected["files"]["events.jsonl.gz"], "Journal changed before replay")
            with gzip.open(events, "rt", encoding="utf-8") as stream:
                for line in stream:
                    replay.process(json.loads(line))
            result = replay.finish()
            require(result["verification_native_ticks"] == selected["resources"]["native_tick_calls"]
                    and sum(v["recorded_native_ns"] for v in result["per_arm"].values()) == selected["resources"]["native_ns"],
                    "Selected native resource ledger differs from its complete tick coverage")
            require(identities == {key: digest(path) for key, path in inputs.items()}, "Replay input changed during verification")
            results[str(seed)] = {**result, "inputs": identities,
                "controller_sha256": {arm: bound(controllers[arm]) for arm in NATIVE}}
        total = bridge.tick_count
    require(digest(freeze_path) == freeze_identity and all(digest(member(source.parent, name)) == identity
            for name, identity in freeze["source_files"].items()), "Freeze or scientific source changed during verification")
    return {"schema": "hepta.field-bridge.v3.independent-native-session-audit.1", "passed": True,
        "profile": profile, "seeds": results, "run_root": str(run), "source_root": str(source),
        "freeze_sha256": freeze_identity, "registered_commit": freeze["registered_commit"],
        "protocol_sha256": freeze["protocol_sha256"], "source_files": freeze["source_files"],
        "native_library_sha256": digest(library), "native_build_receipt_sha256": digest(source / "evidence/NATIVE_BUILD_RECEIPT.json"),
        "original_kernel_source_pin": SOURCE_PIN, "auditor_source_sha256": digest(__file__),
        "state_drive_digest_authority_comparison": "exact; only native_ns and bridge_roundtrip_ns excluded",
        "feature_transform_action_comparison": "exact; no numerical tolerance", "discrepancies": 0,
        "verification_native_ticks": total, "generator_forward_calls": 0, "observer_forward_calls": 0,
        "fitting_calls": 0, "additional_verification_only": True, "new_independent_observations": 0,
        "public_event_media_truth_scope": "Separate media audit binds identical input hashes and reconstructs actual delivered events",
        "authority": "DENY_ALL", "native_owner_integration": False, "requires_calibration": True,
        "verification_wall_ns": time.perf_counter_ns() - started, "verification_cpu_ns": time.process_time_ns() - cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--profile", choices=("frozen", "ordinary", "field"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite independent replay evidence")
    result = audit(args.run, args.profile, args.source, args.freeze, args.native)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "profile": args.profile,
                      "verification_native_ticks": result["verification_native_ticks"], "receipt_sha256": digest(args.output)}))
