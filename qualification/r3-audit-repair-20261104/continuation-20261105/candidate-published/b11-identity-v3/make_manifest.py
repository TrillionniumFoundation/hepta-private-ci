from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]


def pin(path):
    path = path.resolve()
    body = path.read_bytes()
    return {"path": str(path), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


source_map = json.loads((ROOT / "source-map.json").read_text())
checks = json.loads((ROOT / "static-checks.json").read_text())
native = WORKSPACE / "architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127383345954"
api = WORKSPACE / "architecture-audit/b11-mic-physical-probe-20261105/primary"
api_symbols = []
for filename, expected, symbols in [
    ("windows-security-0.52.0.json", "e474d1dfc62b7be1443f2b59eda8370477fdfa74", ["CreateRestrictedToken(", "DISABLE_MAX_PRIVILEGE", "ImpersonateLoggedOnUser(", "RevertToSelf("]),
    ("windows-threading-0.52.0.json", "6ee2c4ad6120e5a3ad34c87e67d6d9187304d9ac", ["OpenThreadToken(", "GetCurrentThread("]),
    ("windows-foundation-0.52.0.json", "6502b8224f3bebf23dca29c6ea1a68b47e7c7611", ["ERROR_NO_TOKEN"]),
]:
    value = json.loads((api / filename).read_text())
    body = value["content"].encode()
    actual = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    assert actual == expected == value["sha"]
    for symbol in symbols:
        assert symbol in value["content"]
    api_symbols.append({"official_repository": "microsoft/windows-rs", "git_blob": actual,
                        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "symbols": symbols,
                        "local_original": str((api / filename).resolve())})
fs = WORKSPACE / "research-audit/b11-current-boundary-design/windows-sys-0.52-filesystem.rs.txt"
assert pin(fs)["git_blob"] == "5cb313fe5ba69cbec6eee56b86ec13608744dae4"
fs_symbols = ["FILE_ID_INFO", "FILE_ID_128", "FileIdInfo", "FILE_ATTRIBUTE_TAG_INFO", "FileAttributeTagInfo", "FILE_READ_ATTRIBUTES", "FILE_FLAG_OPEN_REPARSE_POINT", "GetFileInformationByHandleEx"]
for symbol in fs_symbols:
    assert symbol in fs.read_text()
api_symbols.append({**pin(fs), "official_repository": "microsoft/windows-rs", "symbols": fs_symbols})

workflow = ROOT.parent / "execution-candidate-v2/candidate/.github/workflows/hepta-windows-token-mechanism-probe.yml"
assert pin(workflow)["git_blob"] == "70f3145268e042ec04fbfe85eda83ccbbc4ff79c"
for item in source_map["paths"]:
    assert "      - " + item["repository_path"] in workflow.read_text()
leaves = native / "members/b11-token-mechanism-probe/source-leaves.txt"
for item in source_map["paths"]:
    assert "100644 blob " + item["preimage"]["git_blob"] + "\t" + item["repository_path"] in leaves.read_text()

manifest = {
    "schema": "b11-same-object-deny-repair-candidate-v3",
    "status": "STATIC_SOURCE_CANDIDATE_PENDING_ORIGINAL_WINDOWS",
    "target_pr": 4884,
    "base_head": source_map["base_head"], "base_tree": source_map["base_tree"],
    "native5_actual_checkout": "582f5315f4f632444ae3782d9381f69ed1ae555d",
    "native5_actual_tree": "1718e3e2235b875320f366d03cf796e2a4e92281",
    "native5_parents": ["eed4d6bb61b789b19f60facc79f9e031765fa4c9", source_map["base_head"]],
    "source_map": source_map["paths"], "change_counts": source_map["counts"],
    "source_preimage_evidence": pin(leaves),
    "native5": {
        "job_id": 127383345954, "run_id": 42066891449, "attempt": 1,
        "result": {"passed": 143, "failed": 10, "ignored": 2, "two_disjoint_harnesses_total": 155},
        "native_failure_classification": pin(native / "failure-classification.json"),
        "complete_terminal_review": pin(native / "terminal-review.json"),
        "registration_git_blob": "95b558861e290caeff721b3460f84c47dbd8a8a1",
        "actual_repair_failures": [
            "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write: ReOpenFile directory error5",
            "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes: ReOpenFile directory error5",
            "acl::tests::existing_native_deny_does_not_require_write_dac: host ReOpen succeeded, None versus Some(5)"
        ],
        "root_cause_limit": "Original error endpoints are established. Directory handles are documented to be supported by ReOpenFile with BACKUP_SEMANTICS. The actual kernel/access-check reason for error5 and the old host control's success is not uniquely established. The candidate is not declared fixed before original Windows execution.",
        "other_failures": "Strict outside delete escape, two ordinary-host Neither matrix failures before restricted construction, and four poisoned tests remain separately classified. No blanket containment or weakened expectation is introduced."
    },
    "production_contract": {
        "query_noop": "Original CreateFileW READ_CONTROL query and complete-deny recognizer remain byte-identical. Complete denies return before FileIdInfo, READ_ATTRIBUTES, or WRITE_DAC acquisition.",
        "repair": "Retain original query handle. Obtain its nonzero 128-bit FILE_ID_INFO and volume serial. Fresh OPEN_EXISTING CreateFileW uses READ_CONTROL|WRITE_DAC|FILE_READ_ATTRIBUTES, full read/write/delete sharing, BACKUP_SEMANTICS|OPEN_REPARSE_POINT. Reject final reparse points and require exact 128-bit ID plus volume serial equality before the unchanged SetEntriesInAclW/SetSecurityInfo tail.",
        "ownership": "OwnedHandle owns each successful fresh handle; all errors close it. The query handle remains alive across identity comparison and mutation. Successful access to a replacement handle never authorizes mutation before equality.",
        "no_path_setter_fallback": True,
        "compatibility_changes": [
            "Only actual repairs newly require FILE_READ_ATTRIBUTES, necessary to query FileAttributeTagInfo; a DACL that permits WRITE_DAC but denies this attribute access now fails closed.",
            "Actual repairs require a supported nonzero 128-bit file ID. Unsupported queries or all-zero IDs fail closed; no potentially nonunique 64-bit fallback.",
            "Actual repairs reject a final reparse-point object opened without following it; already-complete no-op behavior remains the original query behavior.",
            "No claim of portable compatibility with every filesystem/server, concurrent DACL writers, trusted volume administration, or pathname/ancestor custody. The retained-handle comparison covers the object selected for this mutation."
        ],
        "helper_reuse_review": {
            "public_acl": {"git_blob": "53c7053c5880da13640f3bd777998b6998da6d47", "unchanged": True},
            "existing_setup_no_reparse_dir": {"git_blob": "93d983f12f027d43dc959b6d0fea324bbdeed7c4", "why_not_reused": "Private setup binary helper performs NtCreateFile FILE_OPEN_IF and directory-only creation; it is not a query-only/existing-file helper or a reusable 128-bit identity checker."},
            "path_utils_examined": ["b8a81904fd7574f9e8429a04d070bd1031d5d981", "091a2f80f4e709aaeb750e4f5eb8fa939f7924c1"],
            "scope": "No reusable stable-128-bit query helper was found in these examined paths. This is not a claim of exhaustive current-tree content search. Uses existing windows-sys 0.52 APIs and OwnedHandle without a new dependency."
        }
    },
    "physical_controls": {
        "original_no_write_dac_case": "acl::tests::existing_native_deny_does_not_require_write_dac",
        "fixture_change": "Only task-owned file DACL gains Owner Rights plus Everyone deny WRITE_DAC. A new owned token uses DISABLE_MAX_PRIVILEGE, with no disabled/restricting SID inputs. Require no prior thread impersonation; impersonate only this test thread and revert on normal/error/panic paths before the retained restore handle is dropped. No host token, default policy or system ACL is changed.",
        "required_precursors": "READ_CONTROL and RC|READ_ATTRIBUTES opens must succeed under the controlled token. Production repair acquisition must then produce exact CreateFileW context with typed ERROR_ACCESS_DENIED. Thus an earlier FileIdInfo failure cannot satisfy the control.",
        "original_assertions": checks["original_six_no_write_dac_assertions_byte_equal_in_order"],
        "new_case": "acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object",
        "new_case_scope": "Physical rename and recreation for file then directory while the original query handle is retained with FILE_SHARE_DELETE. Both DACLs must remain byte-identical after rejected repair; the original object remains repairable through its new name, and file data remains unchanged. No mocked identity/ACL or timeout is used.",
        "negative": {
            "source": source_map["negative_source"], "patch": pin(ROOT / "remove-identity-check.patch"),
            "restore": pin(ROOT / "restore-identity-check.patch"),
            "mutation": checks["negative_semantic_change"],
            "case": "acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object",
            "required_marker": checks["negative_required_marker"],
            "required_panic_macro_line": checks["negative_expected_panic_macro_line"],
            "required_assertion": checks["negative_expected_assertion"],
            "validity": checks["negative_scope"],
            "ordinary_assertion_failure_only": True, "finally_restore_exact_positive_source_required": True,
            "native_execution": "NOT_RUN"
        }
    },
    "preservation": {
        "original_test_names": checks["original_test_names"],
        "one_new_case_only": checks["post_test_names"][-1],
        "other_original_test_bodies_and_surrounding_text_byte_equal": True,
        "production_preserved_segments": checks["production_preserved_segments"],
        "unchanged": ["Public recursive ACL query", "Masks/SIDs/order/inheritance rules", "Strict token constructors and flags", "Legacy ambient read", "Original three strict assertions", "Both original four-cell matrices", "All eight mechanism observation rows and restoration", "Dependencies/features/Cargo.lock/MODULE.bazel.lock/BUILD", "Original retry/timeout/ignored rules", "Workflow command/runner/status/artifact handling"],
        "B11": "OPEN"
    },
    "existing_execution_registration": {
        "workflow": pin(workflow), "both_changed_paths_already_trigger": True, "workflow_change_needed": False,
        "platform": "x86_64-pc-windows-msvc", "runner": "windows-latest", "outer_timeout_minutes": 120,
        "target": "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests",
        "command_source": "Exact original wrapper command and flags in pinned workflow; no rewritten selection or permissive exit handling.",
        "original_roster": 155, "expected_candidate_roster_given_same_other_sources": 156,
        "named_primary_cases": ["acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write", "acl::tests::existing_native_deny_does_not_require_write_dac", "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes", "acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object"],
        "acceptance": "Need actual noncached original Windows target, per-case raw/roster and source leaves, no early-return/skip substitution; all original strict failures remain visible. Negative requires its exact physical marker/assertion and exact finally restoration, not arbitrary failed compilation or test timeout. Neither this repair's pass nor probe pass closes strict delete isolation."
    },
    "official_primary": {
        "original_retrievals": pin(ROOT / "primary-originals.json"), "bindings": api_symbols,
        "references": [
            {"url": "https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-reopenfile", "fact": "Directory support with BACKUP_SEMANTICS; privilege-related access behavior does not establish this host's actual cause."},
            {"url": "https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew", "fact": "OPEN_REPARSE_POINT opens the reparse point itself; full sharing avoids a sharing-denial substitute."},
            {"url": "https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info", "fact": "Volume serial plus 128-bit file identifier compare open file handles."},
            {"url": "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/7ba4e65d-356b-43ca-a867-e897e5b9392a", "fact": "FileAttributeTagInformation requires FILE_READ_ATTRIBUTES."},
            {"url": "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/a00d78b9-5a5b-44cc-b389-6c67d53611ee", "fact": "FileIdInformation returns volume serial and FileId128 for the open object."},
            {"url": "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/e4185a8a-ed8d-4f98-ab55-ca34dc8916e6", "fact": "Unsupported 128-bit IDs are zero and not usable; candidate rejects them."},
            {"url": "https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken", "fact": "DISABLE_MAX_PRIVILEGE removes privileges except traversal; this test passes zero SID-list counts."},
            {"url": "https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo", "fact": "Handle-based setter and inherited ACE behavior remain the original mechanism."}
        ]
    },
    "artifacts": {name: pin(ROOT / name) for name in ["full.patch", "source-map.json", "static-checks.json", "roundtrip.json", "freeze.py"]},
    "validation": {"cloud_git_positive_negative_restore_roundtrips": True, "source_and_assert_preservation": True,
                   "rustfmt": "NOT_RUN", "rust_compile": "NOT_RUN", "Windows": "NOT_RUN", "native_acl_mutation": False,
                   "native_source_or_target_modified": False, "refs_or_PR_modified": False,
                   "original_pre_format_draft_preserved": "initial-draft/"}
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(pin(ROOT / "manifest.json"), indent=2))
