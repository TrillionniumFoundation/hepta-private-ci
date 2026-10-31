"""Independent actual-byte truth audit for complete offline runtime trees.

Only the two registered fitting/selection roles are opened. All 85 terminal
rewards and 21 public-event states per tree are rebuilt from delivered PNG/UTF8
and retained public logits. This adds observer verification, never generation.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import time

import numpy as np

from feedback_evidence import MediaIndex, ObserverArithmetic, event, feedback_values
from runtime_audit_support import child, file_sha, object_sha, records, require
from runtime_media_context import cases_for, load_context, unchanged_observers


ROLES = ("runtime_fit", "runtime_select")


def plan(node):
    require(type(node) is int and 0 <= node < 85, "Invalid complete-tree node")
    actions = []
    while node:
        actions.append((node - 1) % 4 + 1)
        node = (node - 1) // 4
    return list(reversed(actions))


def validate_packet(packet, receipt, case, private, record, depth, commit_time):
    feedback = feedback_values(record, private["pixels"], private["labels"], case, depth)
    require(set(packet) == {"case_id", "depth", "output_record_sha256", "public_feedback",
                           "after_readback_monotonic_ns", "source_kind"} and
            packet["case_id"] == case and packet["depth"] == depth and
            packet["output_record_sha256"] == receipt["record_sha256"] and
            packet["source_kind"] == "declared_simulated_external_verifier" and
            type(packet["after_readback_monotonic_ns"]) is int and
            receipt["readback_monotonic_ns"] <= packet["after_readback_monotonic_ns"] <= commit_time and
            np.array_equal(packet["public_feedback"], feedback), "Simulated feedback truth, scope or chronology differs")
    return feedback


class DeliveryAudit:
    def __init__(self, index):
        self.index, self.seen, self.last_time, self.deliveries = index, set(), 0, 0

    def read(self, receipt, case, depth, before, after=0):
        require(receipt["case_id"] == case and receipt["depth"] == depth and
                type(receipt["readback_monotonic_ns"]) is int and
                max(self.last_time, after, 1) <= receipt["readback_monotonic_ns"] <= before,
                "Delivery source/depth or readback chronology differs")
        require(type(receipt["physical_record_reused"]) is bool and
                receipt["physical_record_reused"] == (receipt["offset"] in self.seen),
                "Physical deduplication flag differs from first actual delivery")
        record = self.index.receipt(receipt)
        self.seen.add(receipt["offset"])
        self.last_time, self.deliveries = receipt["readback_monotonic_ns"], self.deliveries + 1
        return record

    def finish(self):
        require(self.seen == set(self.index.records) == self.index.used, "Unreferenced physical media or missing delivery")
        return {"logical_media_deliveries": self.deliveries, "physical_media_records": len(self.index.records),
                "physical_media_bytes": self.index.physical_bytes}


def audit_tree(directory, rows, arrays, cases, groups, arithmetic, role):
    index = MediaIndex(Path(directory) / "media.h3m")
    delivery, counts = DeliveryAudit(index), Counter()
    expected_cases = [case for group in groups for case in group]
    require(set(arrays) == {"events", "terminal_values", "source_ids", "case_ids", "conditions"} and
            arrays["case_ids"].tolist() == expected_cases and
            arrays["source_ids"].tolist() == [cases[case]["source_ids"] for case in expected_cases] and
            arrays["conditions"].tolist() == [cases[case]["condition"] for case in expected_cases] and
            arrays["events"].shape == (len(cases), 21, 16) and
            arrays["terminal_values"].shape == (len(cases), 85) and
            np.isfinite(arrays["events"]).all() and np.isfinite(arrays["terminal_values"]).all(),
            "Offline bank arrays differ from the complete source case grid")
    positions = {case: index for index, case in enumerate(expected_cases)}
    iterator = iter(rows)
    for group in groups:
        committed = []
        for node in range(85):
            try:
                row = next(iterator)
            except StopIteration as error:
                raise ValueError("Incomplete 85-node evidence tree") from error
            actions, depth = plan(node), len(plan(node))
            require(row["kind"] == "counterfactual_node_output" and row["role"] == role and row["node"] == node and
                    row["plan"] == actions and row["depth"] == depth and row["case_ids"] == group and
                    row["source_ids"] == [cases[case]["source_ids"] for case in group] and
                    row["counterfactual_access_scope"] == "offline_registered_fit_or_selection" and
                    len(row["media"]) == len(row["reward_scores"]) == len(group), "Offline tree branch/source scope differs")
            require((row["feedback"] is None if node == 0 or node >= 21 else len(row["feedback"]) == len(group)) and
                    (row["public_event"] is None if node >= 21 else np.asarray(row["public_event"]).shape == (len(group), 16)),
                    "Offline event/feedback coverage differs")
            commit_time = row["committed_monotonic_ns"]
            after = 0 if node == 0 else committed[(node - 1) // 4]
            committed.append(commit_time)
            for local, case in enumerate(group):
                private, receipt = cases[case], row["media"][local]
                record = delivery.read(receipt, case, depth, commit_time, after)
                measured = arithmetic.score(record, private["pixels"], private["labels"], "reward", depth)
                require(row["reward_scores"][local] == measured and
                        arrays["terminal_values"][positions[case], node] == measured["net_utility"],
                        "Actual delivered reward/charge differs from stored offline terminal target")
                counts["terminal_rewards"] += 1
                if node < 21:
                    feedback = None if node == 0 else validate_packet(row["feedback"][local], receipt, case, private, record, depth, commit_time)
                    public = arithmetic.public(record, private["mask"])
                    rebuilt = event(public, feedback, actions[-1] if actions else 0)
                    require(np.array_equal(row["public_event"][local], rebuilt) and
                            np.array_equal(arrays["events"][positions[case], node], rebuilt),
                            "Actual delivered public event differs from stored offline fitting state")
                    counts["public_events"] += 1
                    counts["feedback_packets"] += int(node != 0)
            counts["journal_nodes"] += 1
    require(next(iterator, None) is None, "Unexpected extra offline tree evidence")
    count = len(cases)
    expected = {"encoder_examples": count, "encoder_batches": count,
        "transition_examples": 85 * count, "transition_batches": 85 * count,
        "decoder_examples": 85 * count, "decoder_batches": 85 * count,
        "public_feature_observer_digit_examples": 42 * count, "reward_observer_digit_examples": 170 * count,
        "simulated_feedback_packets": 20 * count, "media_logical_deliveries_read_back": 85 * count,
        "offline_terminal_targets": 85 * count}
    media = delivery.finish()
    expected.update(physical_media_records=media["physical_media_records"], physical_media_bytes=media["physical_media_bytes"])
    return {**dict(counts), **media, "trees": count, "resources_reconstructed": expected}


def open_banks(run, profile, source, freeze_path):
    run, source = Path(run).resolve(), Path(source).resolve()
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    require(profile in protocol["runtime"]["profiles"], "Unknown runtime profile")
    parents = [run / "runtime" / "bank" / f"{seed}-{profile}" for seed in protocol["seeds"]]
    require(all((parent / "COMPLETE.json").is_file() and not (parent / "FAILED.json").exists() and
                all((parent / role / "COMPLETE.json").is_file() for role in ROLES) for parent in parents),
            "All three completed parent banks and six role banks are required before raw-bank access")
    freeze, frozen_files = json.loads(Path(freeze_path).read_text()), {}
    protocol_sha = file_sha(source / "PROTOCOL.json")
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]) and "runtime-bank" in freeze["allowed_phases"] and
            freeze["protocol_sha256"] == protocol_sha, "Unregistered runtime bank freeze")
    for name, digest in freeze["source_files"].items():
        frozen_files[child(source.parent, name)] = digest
    for name, digest in freeze.get("artifacts", {}).items():
        frozen_files[child(run, name)] = digest
    frozen_files[Path(freeze_path).resolve()] = file_sha(freeze_path)
    require(all(file_sha(path) == digest for path, digest in frozen_files.items()), "Frozen bank source/artifact changed")
    if profile != "frozen":
        path = run / "TRAINING_QUALIFICATION.json"
        require(path in frozen_files, "Non-frozen bank lacks frozen learning qualification")
        qualified = json.loads(path.read_text())
        require(qualified["passed"] is True and qualified["protocol_sha256"] == protocol_sha, "Learning did not qualify this bank")
    entries = []
    for seed, parent in zip(protocol["seeds"], parents, strict=True):
        outer = json.loads((parent / "COMPLETE.json").read_text())
        start = json.loads((parent / "START.json").read_text())
        require(outer["phase"] == "runtime-bank" and outer["seed"] == seed and outer["profile"] == profile and
                outer["source_roles"] == list(ROLES) and outer["source_manifest_sha256"] == protocol["source_manifest_sha256"],
                "Completed bank scope differs")
        require(start["phase"] == "runtime-bank" and start["seed"] == seed and start["profile"] == profile and
                start["role"] is None and start["freeze_sha256"] == file_sha(freeze_path) and
                start["protocol_sha256"] == protocol_sha and start["registered_commit"] == freeze["registered_commit"] and
                start["native_library_sha256"] == freeze["native_library_sha256"] and
                start["source_files"] and all(freeze["source_files"].get(k) == v for k, v in start["source_files"].items()),
                "Bank START source/phase/freeze identity differs")
        actual = {str(path.relative_to(parent)) for path in parent.rglob("*") if path.is_file() and path != parent / "COMPLETE.json"}
        require(set(outer["files"]) == actual, "Completed bank inventory differs")
        frozen_files[parent / "COMPLETE.json"] = file_sha(parent / "COMPLETE.json")
        for name, digest in outer["files"].items():
            path = child(parent, name)
            require(file_sha(path) == digest, "Completed bank evidence changed: " + name)
            frozen_files[path] = digest
        fingerprints = []
        for role in ROLES:
            directory = parent / role
            complete = json.loads((directory / "COMPLETE.json").read_text())
            pairs = protocol["runtime"]["fit_pairs" if role == "runtime_fit" else "selection_pairs"]
            require(complete["role"] == role and complete["seed"] == seed and complete["profile"] == profile and
                    complete["pairs"] == pairs and complete["rows"] == pairs * len(protocol["runtime"]["conditions"]) and
                    complete["source_manifest_sha256"] == protocol["source_manifest_sha256"] and
                    complete["metadata"]["protocol_sha256"] == protocol_sha and
                    complete["metadata"]["registered_commit"] == freeze["registered_commit"] and
                    complete["all85_open_loop_plans"] == [plan(node) for node in range(85)], "Offline bank protocol/grid differs")
            require(set(complete["files"]) == {"bank.npz", "media.h3m", "evidence.jsonl.gz"} and
                    all(outer["files"][role + "/" + name] == digest for name, digest in complete["files"].items()),
                    "Parent/child bank identity differs")
            fingerprints.append((complete["model_parameter_sha256"], complete["observer_parameter_sha256"]))
            entries.append({"seed": seed, "role": role, "directory": directory, "complete": complete,
                "inputs": {"parent_complete_sha256": file_sha(parent / "COMPLETE.json"),
                    "bank_complete_sha256": file_sha(directory / "COMPLETE.json"), **complete["files"]}})
        require(fingerprints[0] == fingerprints[1], "Fit/selection generator or observer differs")
    return protocol, freeze, frozen_files, entries


def execute(run, profile, source, freeze_path, assets):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    protocol, freeze, frozen_files, entries = open_banks(run, profile, source, freeze_path)
    corpus, observers, fingerprints, asset_identity = load_context(assets, source, ROLES, protocol)
    arithmetic, results = ObserverArithmetic(observers), []
    for item in entries:
        require(item["complete"]["observer_parameter_sha256"] == fingerprints["reward"], "Bank observer differs from pinned actual observer")
        cases, groups, panel_sha = cases_for(corpus, item["role"], item["seed"], protocol)
        with np.load(item["directory"] / "bank.npz", allow_pickle=False) as saved:
            arrays = {name: saved[name] for name in saved.files}
            summary = audit_tree(item["directory"], (row for row, _ in records(item["directory"] / "evidence.jsonl.gz")),
                                 arrays, cases, groups, arithmetic, item["role"])
        require(summary["resources_reconstructed"] == item["complete"]["resources"], "Offline work ledger differs from complete tree evidence")
        results.append({"seed": item["seed"], "role": item["role"], "inputs": item["inputs"],
                        "source_panel_sha256": panel_sha, **summary})
        print(json.dumps({"seed": item["seed"], "role": item["role"], "status": "pass", "terminal_rewards": summary["terminal_rewards"]}), flush=True)
    unchanged_observers(observers, fingerprints)
    require(all(file_sha(path) == digest for path, digest in frozen_files.items()), "Audit source or bank bytes changed during verification")
    return {"schema": "hepta.field-bridge.v3.independent-runtime-bank-media.1", "status": "pass", "passed": True,
        "profile": profile, "seeds": protocol["seeds"], "roles": list(ROLES), "banks": results,
        "protocol_sha256": freeze["protocol_sha256"], "freeze_sha256": file_sha(freeze_path),
        "source_manifest_sha256": protocol["source_manifest_sha256"], "observer_parameter_sha256": fingerprints,
        "original_assets": asset_identity, "exact_discrepancies": 0, "generator_forward_calls": 0,
        "verification_observer_digit_forwards": arithmetic.calls,
        "logical_observer_image_pairs": arithmetic.logical_images, "additional_verification_only": True,
        "new_independent_observations": 0, "verification_wall_ns": time.perf_counter_ns() - started,
        "verification_cpu_ns": time.process_time_ns() - cpu,
        "scope": "Actual-media label truth for fixed completed fit/select trees; controller fitting and selected causal execution have separate audits",
        "public_logits_scope": "Checks retained logits against exact H3M bytes and recomputes public softmax; no claim to regenerate neural decoder logits without generator execution",
        "reviewer_source_files": {name: file_sha(Path(__file__).with_name(name)) for name in
            ("runtime_bank_media_audit.py", "runtime_media_context.py", "feedback_evidence.py", "runtime_audit_support.py")}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "source", "freeze", "assets", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--profile", required=True, choices=("frozen", "ordinary", "field"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    require(not output.is_relative_to((Path(args.run) / "runtime").resolve()) and not output.exists(),
            "Audit output must be new and outside immutable runtime evidence")
    result = execute(args.run, args.profile, args.source, args.freeze, args.assets)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "receipt_sha256": file_sha(output),
                      "verification_observer_digit_forwards": result["verification_observer_digit_forwards"]}))
