import datetime
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
HEAD = "eed4d6bb61b789b19f60facc79f9e031765fa4c9"
TREE = "ca1c4671ef6b2773280d01b5d76c6166252f5856"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def source(path, local_file, role, api_name):
    data = Path(local_file).read_bytes()
    api = json.loads((ROOT / "originals" / api_name).read_text())["structuredContent"]
    if api.get("sha"):
        assert identity(data)["blob"] == api["sha"]
        if api.get("encoding") == "utf-8":
            assert data == api["content"].encode()
    else:
        directory = json.loads(api["content"])
        item = next(row for row in directory if row["path"] == path)
        assert identity(data)["blob"] == item["sha"]
        assert len(data) == item["size"]
    return {"path": path, "local_file": str(Path(local_file).resolve()), "role": role,
            "fixed_head": HEAD, "fixed_url": f"https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{HEAD}/{path}",
            "binding_original_api": f"originals/{api_name}", **identity(data)}


main_api = json.loads((ROOT / "originals/main-api.json").read_text())["structuredContent"]
main_path = ROOT / "source/codex-rs/windows-sandbox-rs/src/bin/setup_main/main.rs"
main_path.write_bytes(main_api["content"].encode())
defs_api = json.loads((ROOT / "originals/defs-api.json").read_text())["structuredContent"]
defs_path = ROOT / "source/defs.bzl"
defs_path.write_bytes(defs_api["content"].encode())
base = WORKSPACE / "architecture-audit/b11-delete-boundary-20261105/source/codex-rs/windows-sandbox-rs"
build = WORKSPACE / "architecture-audit/b11-mic-physical-probe-20261105/source/codex-rs/windows-sandbox-rs"
refs = [
    source("codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs", ROOT / "source/codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs", "Full/read-only helper and exact preimage", "binding-api-0.json"),
    source("codex-rs/windows-sandbox-rs/src/bin/setup_main/win/read_acl_mutex.rs", ROOT / "source/codex-rs/windows-sandbox-rs/src/bin/setup_main/win/read_acl_mutex.rs", "named mutex exact preimage", "source-api-1.json"),
    source("codex-rs/windows-sandbox-rs/src/bin/setup_main/win_acl_tests.rs", ROOT / "source/codex-rs/windows-sandbox-rs/src/bin/setup_main/win_acl_tests.rs", "original physical provision-only helper control, unchanged", "source-api-2.json"),
    source("codex-rs/windows-sandbox-rs/src/setup.rs", base / "src/setup.rs", "actual root selection, outer waits, singleflight and original controls", "binding-api-1.json"),
    source("codex-rs/windows-sandbox-rs/src/identity.rs", base / "src/identity.rs", "initial setup plus mandatory refresh before returning credentials", "binding-api-1.json"),
    source("codex-rs/windows-sandbox-rs/src/spawn_prep.rs", base / "src/spawn_prep.rs", "normal elevated spawn caller", "binding-api-1.json"),
    source("codex-rs/windows-sandbox-rs/src/elevated_impl.rs", WORKSPACE / "architecture-audit/b11-full-restricting-caller-20261105/source/codex-rs/windows-sandbox-rs/src/elevated_impl.rs", "normal elevated capture caller", "binding-api-1.json"),
    source("codex-rs/windows-sandbox-rs/src/setup_error.rs", ROOT / "source/codex-rs/windows-sandbox-rs/src/setup_error.rs", "unchanged error codes and serialization", "source-api-3.json"),
    source("codex-rs/windows-sandbox-rs/src/bin/setup_main/main.rs", main_path, "Windows-only module registration", "main-api.json"),
    source("codex-rs/windows-sandbox-rs/Cargo.toml", build / "Cargo.toml", "existing bin and dependency declarations", "crate-api.json"),
    source("codex-rs/windows-sandbox-rs/BUILD.bazel", build / "BUILD.bazel", "existing Windows-only binary test compatibility", "crate-api.json"),
    source("defs.bzl", defs_path, "existing bin-unit-tests and source glob registration", "defs-api.json"),
]

def anchored(ref, start, end, meaning):
    text = Path(ref["local_file"]).read_text()
    begin = text.index(start)
    stop = text.index(end, begin)
    excerpt = text[begin:stop]
    return {"path": ref["path"], "blob": ref["blob"], "start_line": text[:begin].count("\n") + 1,
            "end_line": text[:stop].count("\n") + 1, "meaning": meaning,
            "exact_excerpt": excerpt, "excerpt_identity": identity(excerpt.encode())}

ref_by_path = {r["path"]: r for r in refs}
win = refs[0]
setup = ref_by_path["codex-rs/windows-sandbox-rs/src/setup.rs"]
identity_ref = ref_by_path["codex-rs/windows-sandbox-rs/src/identity.rs"]
anchors = [
    anchored(win, "fn spawn_read_acl_helper(", "struct ReadAclSubjects", "old detached same-executable, inherited environment/current-directory, no credential override"),
    anchored(win, "fn run_setup(", "fn run_read_acl_only(", "marker commit follows successful Full/ProvisionOnly body"),
    anchored(win, "fn run_read_acl_only(", "fn provision_and_hide_sandbox_users(", "old already-existing success plus refresh-only recorded-error failure"),
    anchored(setup, "struct SetupFlight", "pub fn sandbox_dir(", "existing same-process exact-payload result sharing; not a cross-process completion receipt"),
    anchored(setup, "fn run_setup_refresh_inner(", "fn profile_read_roots(", "Full refresh creates payload, waits helper and propagates nonzero error report"),
    anchored(setup, "fn report_helper_failure(", "pub fn run_elevated_setup(", "original initial Command.status and elevated INFINITE, marker check and structured error handling"),
    anchored(setup, "fn build_payload_roots(", "fn build_payload_deny_write_paths(", "unchanged readable root selection/exclusions and deny filtering"),
    anchored(identity_ref, "pub fn require_logon_sandbox_creds(", "fn desired_offline_proxy_settings(", "normal caller always refreshes before returning credentials"),
]

thread_api_path = WORKSPACE / "architecture-audit/b11-mic-physical-probe-20261105/primary/windows-threading-0.52.0.json"
thread_api = json.loads(thread_api_path.read_text())
thread_source = thread_api["content"].encode()
assert identity(thread_source)["blob"] == thread_api["sha"]
thread_signatures = [line for line in thread_source.decode().splitlines()
                     if any(f"fn {name}(" in line for name in ("CreateMutexW", "OpenMutexW", "ReleaseMutex"))]
assert len(thread_signatures) == 3
evidence = {"fixed_head": HEAD, "fixed_tree": TREE, "sources": refs, "anchors": anchors,
            "windows_sys_0_52_api": {"cached_original_api": str(thread_api_path), "display_url": thread_api.get("display_url"),
                                    "full_source": identity(thread_source), "exact_signatures": thread_signatures},
            "official_api_original": {"local_file": "originals/mutex-official-api.json", **identity((ROOT / "originals/mutex-official-api.json").read_bytes())}}
(ROOT / "source-evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")

static = json.loads((ROOT / "static-verification.json").read_text())
source_map = json.loads((ROOT / "source-map.json").read_text())
library_names = [
    "setup_completion_requires_ready_artifacts",
    "identical_setup_requests_share_one_in_flight_run",
    "report_helper_failure_uses_setup_error_report_when_clear_succeeded",
    "report_helper_failure_ignores_setup_error_report_when_clear_failed",
    "setup_refresh_skips_profiles_without_managed_filesystem_permissions",
    "setup_refresh_preserves_workspace_scoped_deny_read_paths",
    "setup_refresh_rejects_invalid_deny_read_globs",
    "gather_read_roots_includes_helper_bin_dir",
    "workspace_write_roots_remain_readable",
    "build_payload_roots_preserves_helper_roots_when_read_override_is_provided",
    "build_payload_roots_replaces_full_read_policy_when_read_override_is_provided",
    "full_read_roots_preserve_legacy_platform_defaults",
]
setup_text = Path(setup["local_file"]).read_text()
for name in library_names:
    assert f"fn {name}(" in setup_text
helper_names = ["win::tests::" + name for name in static["all_original_win_rs_inline_test_names_byte_preserved"]]
helper_names.append("win::acl_tests::provision_only_locks_plain_directory_via_handle")
new_name = "win::read_acl_mutex::tests::existing_read_acl_mutex_is_not_a_completion_receipt"

manifest = {
    "schema": "hepta.static_proposal.read_acl_readiness.v1",
    "frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "status": "STATIC_CANDIDATE_NOT_APPLIED_NOT_COMPILED_NOT_EXECUTED",
    "original_blocker": "B11",
    "original_exit_condition_and_status_modified": False,
    "source": {"repository": "TrillionniumFoundation/hepta-private-ci", "head": HEAD, "tree": TREE,
               "scope": "three exact preimage paths; relevant inherited 5b source is independently rebound to fixed eed", "files": source_map["files"]},
    "patch": {"local_file": "read-readiness.patch", **identity((ROOT / "read-readiness.patch").read_bytes()), **static["diff"]},
    "purpose": "Make Full setup await the current request's existing read ACL stage, reject an existing mutex without a completion receipt, and propagate every recorded read-stage error.",
    "intentional_behavior_changes": [
        "Full read roots nonempty: replace detached same-executable child with a synchronous call to the existing run_read_acl_only implementation at the same phase position.",
        "An existing named mutex returns an anyhow error with actual io::Error raw_os_error 183 instead of Option::None or successful skip. The newly opened non-owner handle is closed.",
        "Recorded read ACL errors now fail initial Full and explicitly non-refresh ReadAclsOnly as well as refresh. The existing detailed log and generic error text are retained.",
        "The Full progress log accurately describes the completed read stage rather than delegation.",
    ],
    "preserved": {
        "read_acl_operations_masks_sids_and_inheritance": "exact source-region byte equality; FILE_GENERIC_READ|FILE_GENERIC_EXECUTE to the original sandbox group with original OI|CI flags",
        "rootset": "unchanged build_payload_roots, helper/platform roots, canonical-existing behavior, profile/SSH exclusions, write-root removal and deny-read filtering",
        "existing_shortcuts": "missing-root skip and builtin/group RX checks deliberately remain; no full-restricting read-SID proof is inferred",
        "token_and_access_masks": "no token source, token flags, restricting SID, read-cap or four write/delete denial oracle change",
        "other_stages": "deny-read remains before the read stage; original runtime/write/deny-write operations and existing tests are unchanged apart from one truthful progress log",
        "wire_and_errors": "SetupMode, Payload, SetupErrorCode and error-report serialization unchanged; historical HelperReadAclHelperSpawnFailed variant retained",
        "dependencies_and_targets": "no Cargo, BUILD, lock, workflow, environment, feature or target declaration change",
        "thread_and_handle": "production named mutex, default descriptor, noninheritance, guard ReleaseMutex/CloseHandle unchanged; guard is acquired and dropped in the same synchronous setup thread",
    },
    "original_waits_and_compatibility": {
        "initial_non_elevated": "Command.status has no local timeout; unchanged",
        "initial_elevated": "WaitForSingleObject(INFINITE); unchanged",
        "refresh": "Command.status has no local timeout; unchanged",
        "same_process_identical_payload": "existing B64-keyed singleflight/Condvar unchanged; no independent timeout",
        "cross_process_or_different_payload": "session-wide fixed mutex is not keyed by read roots; legitimate concurrency may now fail explicitly instead of reporting an unproved success",
        "mutex_existing_without_owner": "also rejected; an object retained by another handle does not attest to completion of this request",
        "new_bounded_readiness_claim": False,
        "new_timeout_wait_retry": False,
        "possible_startup_delay": True,
        "rollback": "none added; earlier provision/ACL effects may already exist when this stage fails",
    },
    "actual_caller_chain": [
        "spawn_prep::prepare_elevated_spawn_context_for_permissions / elevated_impl capture path",
        "identity::require_logon_sandbox_creds: optional initial setup then mandatory current-roots refresh",
        "setup::{run_setup_exe_payload,run_setup_refresh_payload}: wait existing helper and propagate nonzero",
        "setup_main::win::run_setup: successful mode body precedes initial marker commit",
        "setup_main::win::run_setup_full: synchronously run_read_acl_only for nonempty roots",
        "run_read_acl_only: acquire current mutex ownership, perform unchanged read operations, reject collected errors",
    ],
    "new_physical_control": {
        "exact_source_name": new_name,
        "target": "//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests",
        "source_file": source_map["files"][2],
        "execution": "NOT_RUN",
        "scope": "one test thread, actual isolated named Win32 mutex; no subprocess, global environment or production-name mutation",
        "stages": ["actual initial owner acquired", "competing acquisition must return OS 183 and explicit not-ready error", "retain independent handle then drop owner", "released but retained object must still return OS 183 and not-ready error", "close last retained handle then actual owner acquisition succeeds"],
        "ownership": "existing guard owns only newly created mutex; independent OpenMutexW handle owned by std OwnedHandle; all drops stay in test thread",
        "does_not_prove": ["cross-process payload completion", "read ACL success for actual Full", "read SID authorization", "loader operation", "process descendants lifecycle"],
    },
    "existing_control_map": {
        "library_target": "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests",
        "library_selected_source_names": ["setup::tests::" + name for name in library_names],
        "helper_target": "//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests",
        "helper_selected_source_names": helper_names,
        "helper_selected_names_are_entire_runtime_catalog": False,
        "original_singleflight_waiter_check_seconds": 5,
        "all_old_helper_inline_bodies_byteequal": True,
        "new_actual_runs_in_this_review": 0,
    },
    "pending_native_gate": {
        "platform": "actual Windows native runner with source, toolchain, helper binaries, complete case log and before/after identity bound",
        "cargo_existing_entrypoint": "just test -p codex-windows-sandbox",
        "cargo_scope_note": "do not add --lib; the new module belongs to codex-windows-sandbox-setup bin, not library",
        "bazel_existing_targets": ["//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests", "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests"],
        "bazel_invocation": "reuse original Windows runner/configuration/budgets; this proposal adds no workflow or execution arguments",
        "catalog_requirement": "actual unfiltered helper catalog must include the new exact name and retain the original helper roster; selected names above are anchors, not an invented complete runtime count",
        "qualifying_output": "actual new-case body plus complete original helper/library status, skips/retries/cache/early-return retained; wrapper success alone insufficient",
        "remaining_end_to_end_acceptance": ["initial Full completes the actual requested read stage before marker/credentials", "refresh does likewise before spawn", "actual ACL query/set errors fail preparation", "actual concurrent distinct requests report explicit non-readiness without a success claim"],
        "full_B11_unchanged_requirements": ["outside read and loader", "allowed-root legitimate write/delete", "all four forbidden write/delete routes", "host negative controls", "normal caller and descendant/process/Job custody"],
    },
    "scope_open": [
        "No full-restricting token, finite read-root owner, per-session grant lifetime or new SpawnRequest fields.",
        "Builtin/group RX and missing-root shortcuts remain. Completed operations are not a proof that a restricting read SID can read each object.",
        "No protection against path replacement, concurrent ACL writers or per-request root-set drift after return.",
        "No rollback or removal of earlier partial grants/provisioning.",
        "No new cancellation, helper process kill, descendant lifetime, preserve_descendants or Job BREAKAWAY_OK repair.",
        "No production throughput, bounded startup or legitimate cross-process concurrency qualification.",
        "The independent ACL V3/19d2 diagnostic branch and running native jobs are not changed.",
    ],
    "static_validation": {"receipt": {"local_file": "static-verification.json", **identity((ROOT / "static-verification.json").read_bytes())},
                          "git_check_apply_inverse_commands": 4, "all_exit_codes_zero": True,
                          "postimages_checked": 3, "original_preimages_restored": 2, "new_path_removed_on_inverse": True,
                          "rust_fmt_or_compile": False, "windows_or_project_tests": False},
    "evidence": {"source_evidence": {"local_file": "source-evidence.json", **identity((ROOT / "source-evidence.json").read_bytes())},
                 "official_api": ["https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw", "https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-releasemutex"],
                 "original_api_files": [{"local_file": str(p.relative_to(ROOT)), **identity(p.read_bytes())} for p in sorted((ROOT / "originals").glob("*.json"))]},
    "archive_note": "Preserve proposed Rust source bytes but use .rs.source.txt when registering them as passive qualification evidence. Patch remains .patch. Actual create/GET publication is recorded separately.",
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({"manifest":identity((ROOT / 'manifest.json').read_bytes()),"source_evidence":identity((ROOT/'source-evidence.json').read_bytes()),"source_references":len(refs)},indent=2))
