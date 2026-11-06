"""Bind the independent source review to exact bytes; no native execution."""
import difflib
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
SOURCE = WORK / "architecture-audit/b11-host-neither-observation-candidate-20261105"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    mapping = json.loads((SOURCE / "v2/source-map.json").read_bytes())
    original_probe = (SOURCE / "source/codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs").read_bytes()
    probe = (SOURCE / "v2/candidate/codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs").read_bytes()
    old_module = (SOURCE / "candidate/codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs").read_bytes()
    module = (SOURCE / "v2/candidate/codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs").read_bytes()
    assert identity(original_probe)["git_blob"] == "2a384792e8ba88518c26943716e8c3a39a523f9b"
    assert identity(probe)["git_blob"] == "fc9faa6d47ac5fdefa216affceb51a586f8e6b81"
    assert identity(old_module)["git_blob"] == "1f08099d13cc0e282c1fa95cf0261990ff28b88b"
    assert identity(module)["git_blob"] == "b40b49ce772c402c51ddb16bb98ff73dc78cdb41"
    a, b = original_probe.splitlines(True), probe.splitlines(True)
    operations = [op for op in difflib.SequenceMatcher(a=a, b=b).get_opcodes() if op[0] != "equal"]
    assert len(operations) == 2 and all(op[0] == "insert" for op in operations)
    insertions = [b''.join(b[k:l]) for _, _, _, k, l in operations]
    assert insertions == [b'\n#[path = "token_neither_privilege_observation.rs"]\nmod neither_privileges;\n', b'    // The preceding receipt belongs only to the original eight-row phase.\n    // The separate privilege observation below owns two gated cmd processes.\n    neither_privileges::run()?;\n']
    recovered = probe
    for insertion in insertions:
        assert recovered.count(insertion) == 1
        recovered = recovered.replace(insertion, b"")
    assert recovered == original_probe
    before, after = old_module.decode(), module.decode()
    replacements = [
        ('    env.remove("B11_RELEASE");', '    env.retain(|name, _| {\n        !name.eq_ignore_ascii_case("ERRORLEVEL")\n            && !name.eq_ignore_ascii_case("B11_RELEASE")\n            && !(0..4).any(|index| {\n                name.eq_ignore_ascii_case(&format!("MATRIX_FILE_{index}"))\n                    || name.eq_ignore_ascii_case(&format!("MATRIX_DIR_{index}"))\n            })\n    });'),
        ('        "/c".to_owned(), script_path.to_string_lossy().into_owned()];', '        "/e:on".to_owned(), "/v:off".to_owned(), "/c".to_owned(), script_path.to_string_lossy().into_owned()];'),
    ]
    expected = before
    for first, last in replacements:
        assert expected.count(first) == 1
        expected = expected.replace(first, last)
    assert expected == after
    names = re.findall(rb'#\[test\]\s*fn ([A-Za-z0-9_]+)', probe)
    assert names == re.findall(rb'#\[test\]\s*fn ([A-Za-z0-9_]+)', original_probe) == [b'integrity_mechanism_probe_observation_only']
    assert not re.search(rb'#\[(?:test|ignore)', module)
    dependencies = []
    for row in mapping["original_sources"]:
        raw = Path(row["local_file"]).read_bytes()
        assert all(row[k] == v for k, v in identity(raw).items())
        dependencies.append({"repository_path": row["repository_path"], **identity(raw), "owner_original_full_GET_attestation": row["original_full_blob_GET_performed"]})
    assert len(dependencies) == 12
    report = {
        "schema": "b11-host-neither-independent-static-review-v1",
        "decision": "ACCEPT_V2_AS_OBSERVATION_CANDIDATE_ONLY",
        "reviewer": "/root/b20_finish",
        "authority": {k: mapping[k] for k in ("head", "actual_checkout", "actual_tree")},
        "original_probe": identity(original_probe), "candidate_probe": identity(probe),
        "prior_module_v1": identity(old_module), "accepted_module_v2": identity(module),
        "source_map_v2": identity((SOURCE / "v2/source-map.json").read_bytes()),
        "all_original_probe_bytes_recovered_by_removing_only_two_insertions": True,
        "original_test_name_unchanged": names[0].decode(),
        "new_test_or_ignore_attributes": False,
        "roster_preservation": {"whole_expected": 156, "exact_filter_expected": 155, "meaning": "Source preservation only; no new catalog or native result was obtained by this reviewer."},
        "dependencies_checked_against_owner_actual_source_map": dependencies,
        "resolved_findings": [{
            "id": "CMD_ENVIRONMENT_IS_NOT_FULLY_BOUND_V1", "severity": "observation-integrity",
            "old_condition": "The complete inherited environment could shadow dynamic %ERRORLEVEL%; /d did not fix command extensions or delayed expansion. Mixed-case aliases could compete with newly written owned MATRIX paths.",
            "v2_change": "Remove ERRORLEVEL, B11_RELEASE and all eight MATRIX variable aliases with eq_ignore_ascii_case before setting owned values; use /d /e:on /v:off /c.",
            "verification": "Exactly these two replacements turn all 22,651 v1 bytes into all 23,010 v2 bytes. The original probe postimage is unchanged.",
            "primary_sources": ["https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/if", "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd", "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/set_1", "https://devblogs.microsoft.com/oldnewthing/20080926-00/?p=20743"]
        }],
        "independent_source_reasoning": [
            {"area": "effective token", "finding": "OpenThreadToken on the current thread is attempted first; only ERROR_NO_TOKEN permits a process-token fallback. The recorded user/SID attributes, complete group and restricting-SID lists, integrity/policy, session, AppContainer flag and privileges are compared, with explicit primary/impersonation type and SecurityImpersonation checks."},
            {"area": "paired controls", "finding": "Ordinary direct Rust is retained separately. Ordinary and DISABLE_MAX_PRIVILEGE subjects both use the same impersonation path and actual-thread-token query. Derivation changes only an owned token; zero disabled/restricting SID counts and identity equality are checked. RevertToSelf is RAII and aborts on failure."},
            {"area": "fixture scope", "finding": "All five cohorts are prepared under one owned temporary root before impersonation. Each holds original object identity and byte-exact DACL checks; all cohorts compare ACL bytes. These are different matched objects, not reuse of the same object across subjects. Four delete routes and Both/read positive controls are retained."},
            {"area": "child gate", "finding": "The actual CreateProcessAsUserW backend supplies the tested primary token. It configures the Job list and explicit stdio handle list before creation. The parent queries the actual child process token while stdin is blocked; only exact identity/privilege/type equality permits the private release string. EOF and unexpected input exit before deletes. This gates fixture operations, not process startup."},
            {"area": "handle custody", "finding": "The gate writer is checked noninheritable and excluded from the child handle list; only the read pipe and owned combined output handle are inherited. Fixture WRITE_DAC handles are noninheritable. Returned process/thread handles are wrapped immediately; no PID reacquisition or foreign-process action is introduced."},
            {"area": "normal cleanup", "finding": "After the work closure, release input is closed, the exact owned Job is terminated, the owned process is waited up to 5000ms, and Job active-process accounting must be zero. Every condition is required before matrix.finish and success. The same 5000ms wait applies to execution; neither value changes an existing product test budget."},
            {"area": "failure cleanup", "finding": "OwnedChild Drop repeats Job termination and a 5000ms owned-handle wait before remaining fields close; errors are logged, not accepted as success. The existing Job is kill-on-close. Restoration and output-read errors propagate. The original helper exposes BREAKAWAY_OK, so this observation does not establish arbitrary-descendant lifetime isolation."},
            {"area": "physical oracle", "finding": "DeleteMatrix validates retained identity and ACL bytes, checks retained file contents and pending/link state, restores original ACLs when appropriate, then checks pathname disappearance or exact original identity. Actual physical outcomes are required for the Both controls. Cmd ERRORLEVEL observations are command-interpreter values, not Win32 API error codes."},
            {"area": "bounded native reads and build binding", "finding": "TokenBuffer uses a 65536-byte aligned allocation and bounds-checks returned extents, array arithmetic and SID spans. The actual windows-sys 0.52.0 declarations and existing Cargo features cover the APIs; the source glob includes the test-only module. This is source review, not compilation."},
        ],
        "blocking_source_findings_remaining": [],
        "scope_limits": ["No native compilation, fmt or execution was performed or accepted.", "No original whole failure or strict token assertion is closed; B11 remains OPEN.", "The all-privilege counterfactual cannot identify SeRestorePrivilege as a single causal factor.", "Read, loader, normal strict-token behavior and general descendants still require their original contracts.", "Actual launch/result/cleanup errors must remain failures or incomplete observations; no missing row may become a passing denial.", "The existing eight-row completion receipt precedes the new phase; actual acceptance of the added phase requires its own final marker and original test outcome."],
        "primary_api_sources": ["https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-impersonateloggedonuser", "https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw", "https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject", "https://learn.microsoft.com/en-us/windows/win32/sysinfo/handle-inheritance"],
        "native_calls": 0, "resource_queries": 0, "source_refs_modified": False,
        "review_status_is_not_B11_closure": True,
    }
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    path = HERE / "review.json"
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    print(json.dumps({"decision": report["decision"], "review_identity": identity(raw), "candidate_probe": report["candidate_probe"], "accepted_module_v2": report["accepted_module_v2"], "dependencies": len(dependencies), "native_calls": 0}))


if __name__ == "__main__":
    main()
