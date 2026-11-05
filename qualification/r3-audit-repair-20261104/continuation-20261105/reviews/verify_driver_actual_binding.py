"""Cloud-only verification of the original foundation-to-driver handoff.

This reads copied original evidence. It does not invoke a native process, mutate
product source, or substitute for the launcher's mandatory native reopen guards.
"""
from pathlib import Path
import base64
import datetime
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hepta-audit-fifth/inputs/driver-actual-foundation-root-review.json"
FOUNDATION = ROOT / "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2/terminal-originals"
CANDIDATE = ROOT / "ci-audit/recovered-20261105/b16-ai395-driver-v7-bound-candidate-v1"
RUNTIME = ROOT / "architecture-audit/b16-guarded-native-runner-20261105/original-ignored-catalog-v7/v7-candidate"
LAUNCHER = ROOT / "architecture-audit/b16-driver-launcher-template-20261105/launch_driver_v7.py"


def ident(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read(path):
    return json.loads(path.read_bytes())


def check(path, pin):
    actual = ident(path.read_bytes())
    assert all(actual[key] == pin[key] for key in ("bytes", "sha256")), str(path)
    if "git_blob" in pin:
        assert actual["blob"] == pin["git_blob"], str(path)
    if "blob" in pin:
        assert actual["blob"] == pin["blob"], str(path)
    return actual


def content_same(a, b):
    return all(a[k] == b[k] for k in ("bytes", "sha256"))


def graph(metadata):
    return {"workspace_members": sorted(metadata["workspace_members"]),
            "nodes": sorted(({"id": n["id"], "features": sorted(n["features"]),
                              "deps": sorted(n.get("deps", []), key=lambda d: (d["name"], d["pkg"]))}
                             for n in metadata["resolve"]["nodes"]), key=lambda n: n["id"])}


binding_path = CANDIDATE / "driver-binding-DISABLED-actual-foundation-v1.json"
request_path = CANDIDATE / "launch-request-DISABLED-actual-foundation-v1.json"
b, request = read(binding_path), read(request_path)
old = read(ROOT / "ci-audit/recovered-20261105/b16-ai395-driver-v7-disabled-v1/driver-binding-DISABLED-v2.json")
old_request = read(ROOT / "architecture-audit/b16-driver-launcher-template-20261105/launch-request-CI-DISABLED-v2.json")
assert b == request["binding"]
assert b["execute"] is False and b["approval_reference"] is None
assert request["root_execution_guard"] is None and b["authorized_epoch"] == "driver"
assert request["idempotency_key"] == "hepta-ai395-b16-driver-v7-20261105-v1"
assert request["timeout_seconds"] == 21600
assert request["expected_launcher"] == ident(LAUNCHER.read_bytes())
assert request["install_bundle"] == old_request["install_bundle"]
assert {k: v for k, v in request.items() if k != "binding"} == {k: v for k, v in old_request.items() if k != "binding"}
changed_keys = {k for k in old if old[k] != b[k]}
assert changed_keys == {"initial_tree", "previous_epoch_receipt", "baseline_metadata", "locks",
                        "harness_attempt_context", "previous_epoch_binding", "previous_epoch_launch_terminal",
                        "baseline_metadata_source_guards"}, changed_keys
old_context, new_context = dict(old["harness_attempt_context"]), dict(b["harness_attempt_context"])
assert old_context.pop("kind") == "DISABLED_DRIVER_TEMPLATE_PENDING_ACTUAL_FOUNDATION_TERMINAL"
assert new_context.pop("kind") == "DISABLED_DRIVER_CANDIDATE_BOUND_TO_ACTUAL_FOUNDATION_TERMINAL"
assert old_context == new_context

previous = read(FOUNDATION / "epoch-terminal.json")
launch = read(FOUNDATION / "launcher-terminal.json")
prior_binding = read(FOUNDATION / "binding.json")
originals = {}
for key, name in (("previous_epoch_receipt", "epoch-terminal.json"),
                  ("previous_epoch_binding", "binding.json"),
                  ("previous_epoch_launch_terminal", "launcher-terminal.json")):
    originals[key] = check(FOUNDATION / name, b[key])
assert previous["epoch"] == "foundation" and previous["status"] == "QUALIFIED"
assert previous["error"] is None and previous["final_guard"] is True
assert previous["platform_matrix_or_B16_closed"] is False
assert previous["post_hygiene_tests_run"] is False
assert launch["original_runner_exit_code"] == launch["launcher_exit_code"] == 0
assert launch["error"] is None and launch["external_guard_error"] is None
assert launch["no_other_epoch_started"] is True
assert prior_binding["approval_reference"] == launch["root_execution_guard"] == "9ef6f66dca8ec960aad511a6fb9a973b7c3349a8"
assert prior_binding["execute"] is True and prior_binding["authorized_epoch"] == "foundation"
assert launch["epoch_terminal_path"] == b["previous_epoch_receipt"]["path"]
assert b["previous_epoch_binding"]["path"] == str(Path(launch["epoch_terminal_path"]).parent.parent / "binding.json")
assert previous["final_tree"] == b["initial_tree"] == "e510f685d2aa7b9a7121a78f96af3569919e6f88"
assert previous["initial_tree"] == prior_binding["initial_tree"] == b["final_A_tree"]
assert previous["ordinary_head"] == b["ordinary_head"]
assert previous["ordinary_index"] == b["ordinary_index"] == prior_binding["ordinary_index"]
assert previous["locks"] == b["locks"] == prior_binding["locks"]
assert previous["payload_sha256"] == b["approved_payload_sha256"]
assert previous["runner_integrity_sha256"] == b["approved_runner_integrity_sha256"]
continuity_keys = ("final_A_tree", "ordinary_head", "source_directory", "target_directory",
    "target_reuse_mode", "bazel_cache_directory", "bazel_cache_owner", "tools", "environment",
    "recipe_sources", "external_build_prerequisites", "current_host_build_only_baseline", "build_only_host",
    "build_only_cache_owner", "last_tested_A_tree", "last_tested_A_artifacts", "last_tested_A_to_final_A_review",
    "A_helper_basename_roster", "approved_payload_sha256", "approved_runner_integrity_sha256")
assert all(prior_binding[k] == b[k] for k in continuity_keys)
assert len(b["tools"]) == 8 and len(b["A_helper_basename_roster"]) == 33
assert b["allowed_untracked_source_paths"] == []
assert b["min_free_bytes"] == 8000000000
assert {k: b["capacity_plan"][k] for k in ("additional_executable_families", "other_cargo_growth_bytes", "bazel_growth_bytes", "evidence_growth_bytes")} == {
    "additional_executable_families": 1, "other_cargo_growth_bytes": 12000000000,
    "bazel_growth_bytes": 8000000000, "evidence_growth_bytes": 2000000000}

sdk = launch["external_prerequisite_guards"]
assert set(sdk["before"]) == set(sdk["after"]) == {"openssl", "libcap", "tools", "v8"}
sdk_review = {}
for role in sdk["before"]:
    assert content_same(sdk["before"][role], sdk["after"][role])
    after_path = FOUNDATION / Path(sdk["after"][role]["path"]).name
    sdk_review[role] = {"before_and_after_original_records_equal": True,
                       "sha256": sdk["after"][role]["sha256"],
                       "after_original_copy_received": after_path.exists()}
    if after_path.exists():
        check(after_path, sdk["after"][role])

metadata_pin = b["baseline_metadata"]
commands = [c for c in previous["commands"] if c.get("stdout", {}).get("path") == metadata_pin["path"]]
assert len(commands) == 1
command = commands[0]
assert command == read(FOUNDATION / "B10_R2e3_final-metadata-command-terminal.json")
assert command["argv"] == ["cargo", "metadata", "--format-version=1", "--locked"]
assert command["source_before"] == metadata_pin["source_tree"] == b["initial_tree"] and command["exit_code"] == 0
assert content_same(command["stdout"], metadata_pin)
assert read(FOUNDATION / "B10_R2e3_final-metadata-command.json")["attempt"] == 1
guards = {}
for side, pin in b["baseline_metadata_source_guards"].items():
    path = FOUNDATION / Path(pin["path"]).name
    guards[side] = check(path, pin)
    guard = read(path)
    assert guard["label"] == command["name"] + "-" + side
    assert guard["expected_tree"] == guard["actual_tree"] == b["initial_tree"]
    assert guard["head"] == b["ordinary_head"] and guard["untracked"] == []
    assert content_same(guard["ordinary_index"], b["ordinary_index"])
    assert set(guard["locks"]) == set(b["locks"])
    assert all(content_same(guard["locks"][p], b["locks"][p]) for p in b["locks"])
final_guard = read(FOUNDATION / "0128-epoch-final-guard.json")
assert final_guard == {**guard, "label": "epoch-final"}
metadata_path = FOUNDATION / Path(metadata_pin["path"]).name
metadata_received = metadata_path.exists()
if metadata_received:
    check(metadata_path, metadata_pin)
    metadata = read(metadata_path)
    assert graph(metadata) == previous["metadata_graph"]
    assert metadata["workspace_root"] == b["source_directory"] + "/codex-rs"
    assert metadata["target_directory"] == b["target_directory"]
assert len(previous["metadata_graph"]["workspace_members"]) == 193
assert len(previous["metadata_graph"]["nodes"]) == 1501

bundle = request["install_bundle"]
compressed = base64.b64decode(bundle["base64"], validate=True)
assert ident(compressed) == bundle["compressed_identity"]
raw = gzip.decompress(compressed)
assert ident(raw) == bundle["uncompressed_identity"]
objects = json.loads(raw)
assert len(objects) == len({x["path"] for x in objects}) == 29
for obj in objects:
    assert ident(obj["text"].encode()) == obj["identity"]
    assert (RUNTIME / obj["path"]).read_bytes() == obj["text"].encode()
assert len(read(RUNTIME / "runner-integrity.json")["files"]) == 25
driver = read(RUNTIME / "epoch-driver.json")
negatives = [op for op in driver["operations"] if op["kind"] == "negative"]
positives = [op for op in driver["operations"] if op["kind"] == "scopes"]
assert len(negatives) == 2 and sum(len(s["exact_names"]) for op in negatives for s in op["scopes"]) == 3
assert sum(len(s["exact_names"]) for op in positives for s in op["scopes"]) == 12
phase_path = ROOT / "hepta-audit-fifth/inputs/foundation-phase-review-through-10.json"
phases = read(phase_path)
assert [phases[k] for k in ("completed_phase_count", "positive_unique", "positive_occurrences", "negative_unique", "negative_occurrences", "exact_finally_restorations")] == [10, 24, 27, 9, 10, 4]
assert len(previous["reviews"]) == 10
for review, phase in zip(previous["reviews"], phases["phases"]):
    assert review["source"] == phase["source"]

report = {
    "schema": "hepta-root-actual-foundation-driver-review-v1",
    "recorded_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "verdict": "ACCEPT_EXACT_DRIVER_CANDIDATE_WITH_MANDATORY_NATIVE_REOPEN_GUARDS",
    "candidate_binding": ident(binding_path.read_bytes()), "candidate_request": ident(request_path.read_bytes()),
    "launcher": ident(LAUNCHER.read_bytes()), "original_foundation_artifacts": originals,
    "foundation_phase_review": ident(phase_path.read_bytes()),
    "foundation_final_tree": b["initial_tree"], "runner_exit_code": 0, "launcher_exit_code": 0,
    "original_final_source_guard": ident((FOUNDATION / "0128-epoch-final-guard.json").read_bytes()),
    "metadata_command_succeeded_original_attempt": 1, "metadata_original_pin": metadata_pin,
    "metadata_original_guards": guards, "metadata_full_raw_received_and_graph_compared": metadata_received,
    "metadata_complete_original_native_reopen_and_graph_check_required_before_product_mutation": True,
    "original_sdk_guard_review": sdk_review,
    "exact_frozen_runtime_files": 29, "integrity_entries": 25, "tools": 8, "helper_roster": 33,
    "foundation_positive_occurrences": 27, "foundation_positive_unique": 24,
    "foundation_negative_occurrences": 10, "foundation_negative_unique": 9, "foundation_exact_restorations": 4,
    "driver_original_positive_parent_cases": 12, "driver_original_negative_parent_cases": 3,
    "driver_original_finally_scopes": 2, "driver_fresh_capacity_required_bytes": 48517479536,
    "foundation_completed_at": launch["completed_at"],
    "foundation_recorded_free_bytes": launch["actual_free_bytes_after"],
    "recorded_capacity_does_not_replace_fresh_launcher_measurement": True,
    "project_commands_executed_by_this_cloud_review": False, "B16_closed": False,
    "limits": ["Selected foundation phase catalogs retain original -E selections, not a new unfiltered full-suite qualification.",
               "Original negative controls are expected physical counterfactual failures, not positive test passes.",
               "No independent Root issuer, Current factory, three-pool binding, or platform-matrix acceptance is inferred.",
               "This review binds copied originals and requires the unchanged native launcher/runtime to reopen actual metadata, source, SDK and tools before execution."]
}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"output": str(OUT), "identity": ident(OUT.read_bytes()), "metadata_full_raw_received": metadata_received}))
