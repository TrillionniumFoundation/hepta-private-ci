import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
CI = ROOT.parent / "ci-audit/recovered-20261105"
TREE = "7d703610ae4f778ad305ebc139860d276f416e8c"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


def unpack(name, blob):
    raw = (CI / name).read_bytes()
    assert identity(raw)["blob"] == blob, name
    bundle = json.loads(raw)
    files, records = {}, []
    for entry in bundle["files"]:
        data = entry["content"].encode()
        actual = identity(data)
        assert actual["bytes"] == entry["bytes"] and actual["sha256"] == entry["sha256"]
        assert entry["name"] not in files
        files[entry["name"]] = data
        records.append({"name": entry["name"], **actual})
    return bundle, files, {"bundle": identity(raw), "files": records}


manifest = json.loads((CI / "full18-three-repairs-manifest-v3.json").read_bytes())
scopes = {s["label"]: s for s in manifest["scopes"]}


def review_scope(files, label, count, status, source):
    review = json.loads(files[label + "-review.json"])
    assert review["source"] == source
    assert review["selected_count"] == count and review["counts"] == {status: count}
    assert review["retries"] == 0 and review["original_ignored_count"] == 0
    assert review["exit_code"] == (0 if status == "PASS" else 100)
    assert review["programs_before"] == review["programs_after"]
    assert review["helpers_before"] == review["helpers_after"] == []
    assert review["exact_roster"] and review["selection_valid"] and review["source_unchanged"]
    assert review["early_return_notices"] == []
    xml = ElementTree.fromstring(files[label + ".junit.xml"])
    actual = [(c.attrib["classname"], c.attrib["name"],
               "FAIL" if c.find("failure") is not None else "ERROR" if c.find("error") is not None
               else "SKIP" if c.find("skipped") is not None else "PASS") for c in xml.iter("testcase")]
    assert len(actual) == count
    assert sorted(actual) == sorted((c["classname"], c["name"], c["result"]) for c in review["cases"])
    assert sorted((c[0], c[1]) for c in actual) == sorted((c["classname"], c["name"]) for c in scopes[label]["expected_cases"])
    raw = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", files[label + ".log"].decode())
    assert identity(files[label + ".log"])["sha256"] == review["raw"]["sha256"]
    assert identity(files[label + ".junit.xml"])["sha256"] == review["fresh_junit"]["sha256"]
    assert not re.search(r"\bskipping\b", raw, re.I)
    for case in review["cases"]:
        assert case["name"] in raw
    return review, raw


migration, mf, mr = unpack("migration-causal-original166-phase.json", "d1b0677fac6e39f4dc2a3a0ececc20e88a7ba797")
assert len(mf) == 9
negative, negative_raw = review_scope(mf, "migration-inference-negative", 1, "FAIL", "f9bfef21d511a3e9ee25fb67802d240c691f62ec")
positive, positive_raw = review_scope(mf, "migration-original-package", 166, "PASS", "b2cee2e56d32199dc67d362ec15b796b2814ee7e")
case_name = "service::tests::plugins::marketplaces::import_plugins_infers_external_official_marketplace_when_missing_from_settings"
assert f"thread '{case_name}'" in negative_raw and "marketplaces.rs:588:5:" in negative_raw
assert "<[]" in negative_raw and '>    "claude-plugins-official"' in negative_raw
assert "test result: FAILED. 0 passed; 1 failed; 0 ignored" in negative_raw
assert "marketplaces.rs:551:9:" in negative_raw and "isolated import assertions failed" in negative_raw
assert negative["cases"][0]["name"] == case_name and float(negative["cases"][0]["seconds"]) < 60
restore = json.loads(mf["migration-negative-finally-restore.json"])
assert restore["restored_exact_positive"] and restore["actual_source_at_return"] == positive["source"]
assert restore["original_exception"] is None and restore["restoration_exception"] is None
assert json.loads(mf["migration-causal-negative.json"])["qualified"]
# Bind the nested child's success to the exact named parent block. A generic
# libtest "1 passed" elsewhere in the 166-case log is insufficient evidence.
lines = positive_raw.splitlines()
start = next(i for i, line in enumerate(lines) if re.search(r"^\s+PASS\s+\[", line) and case_name in line)
end = next((i for i in range(start + 1, len(lines)) if re.search(r"^\s+(?:PASS|FAIL|TIMEOUT)\s+\[", lines[i])), len(lines))
block = "\n".join(lines[start:end]) + "\n"
assert block.count(f"test {case_name} ... ok") == 2
assert block.count("test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 165 filtered out") == 2
assert negative["filter_unmatched_count"] == 165 and positive["filter_unmatched_count"] == 0
assert len(negative["programs_before"]) == len(positive["programs_before"]) == 1

v8, vf, vr = unpack("v8-runtime-original76-terminal-phase.json", "ce0c122c1168625640e038955623a6ff0fa0e3aa")
assert len(vf) == 5
v8_review, v8_raw = review_scope(vf, "v8-and-runtime-original", 76, "PASS", TREE)
assert "--lib" not in v8_review["packages"]
assert v8_review["filter_unmatched_count"] == 0
class_counts = {}
for case in v8_review["cases"]:
    class_counts[case["classname"]] = class_counts.get(case["classname"], 0) + 1
assert class_counts == {"codex-code-mode-runtime": 68, "codex-v8-poc": 6,
                       "codex-code-mode-runtime::jit": 1, "codex-code-mode-runtime::parallel_initialization": 1}
assert len(v8_review["programs_before"]) == 4
assert v8["native_status"]["state"] == "succeeded" and v8["native_status"]["exit_code"] == 0
assert v8["native_status"]["output_complete"] and not v8["native_status"]["timed_out"]
guard = json.loads(vf["54-final-source-guard.json"])
assert guard["expected_source"] == guard["actual_source"] == TREE
assert guard["head"] == "cabcb40d36e116beaa65750e1f674c52035da785"
assert guard["ordinary_index"]["sha256"] == "8ccf08bcd5b633a38fa81be4814ae264365f1a2cdd1ed81e1633fbcc0ac31502"
assert guard["untracked_source_paths"] == guard["allowed_untracked_source_paths"] == []
assert guard["locks"]["codex-rs/Cargo.lock"]["sha256"] == "4a7a5535cf045089458468411e126b5f59bc6bbf34fc0deead9b0c1b8d84000a"
assert guard["locks"]["MODULE.bazel.lock"]["sha256"] == "11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3"

lock, lf, lr = unpack("v8-default-real-bazel-lock-phase.json", "64ef3bacc481baff02f51b738e0c8a45f8da0662")
assert len(lf) == 22 and lock["tested_source_tree"] == TREE
bootstrap = json.loads(lf["official-bazel-bootstrap.json"])
assert bootstrap["installed"]["bytes"] == 77023347
assert bootstrap["installed"]["sha256"] == "d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8"
assert bootstrap["checksum_text"].startswith(bootstrap["installed"]["sha256"] + "  bazel-9.3.0-linux-x86_64")
assert lf["official-bazel-version.stdout"] == b"bazel 9.3.0\n"
commands = []
for name, argv in [("original-bazel-lock-update", ["just", "bazel-lock-update"]),
                   ("original-bazel-lock-check", ["just", "bazel-lock-check"]),
                   ("task-owned-bazel-server-shutdown", ["bazel", "shutdown"])]:
    status = json.loads(lf[name + "-status.json"])
    command = json.loads(lf[name + "-command.json"])
    assert command["attempt"] == 1 and command["argv"] == status["argv"] == argv
    assert status["exit_code"] == 0 and status["source_before"] == status["source_after"] == TREE
    for stream in ("stdout", "stderr"):
        actual = identity(lf[name + "." + stream])
        assert actual["bytes"] == status[stream]["full"]["bytes"]
        assert actual["sha256"] == status[stream]["full"]["sha256"]
    commands.append({k: status[k] for k in ["name", "argv", "exit_code", "duration_seconds", "source_before", "source_after"]})
generation = json.loads(lf["actual-lock-generation.json"])
assert generation["generator_changed_paths"] == [] and generation["generator_after_tree"] == TREE
assert lf["actual-module-generator.patch"] == b""
assert generation["generated_module_lock"]["git_blob"] == "1904db189003cb0b559f71958518e33a45fb6bb7"
assert generation["generated_module_lock"]["sha256"] == guard["locks"]["MODULE.bazel.lock"]["sha256"]
cleanup = json.loads(lf["temporary-task-user-bazelrc-restored.json"])
assert not cleanup["exists"] and cleanup["cache_preserved"]

terminal_data = (CI / "three-repairs-v3-full-native-terminal.json").read_bytes()
assert identity(terminal_data)["blob"] == "0d851076ebfcc8795c0cbda80ab86304f612bc20"
terminal = json.loads(terminal_data)
assert terminal["source"] == TREE and terminal["source_and_ordinary_index_guards_passed"]
assert terminal["retries"] == 0
report = {
    "schema": "hepta.root.three-repairs-v3-original-scope-review.v1",
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "ORIGINAL_SCOPES_PASS_WITH_VALID_CAUSAL_CONTROLS_AND_REAL_LOCK_GATES",
    "native_job": v8["native_status"]["job_id"], "native_status": v8["native_status"],
    "source_tree": TREE, "native_terminal": identity(terminal_data),
    "skills": {"root_review_blob": "a91450eff02472366bf9bffda3478eccd786ec35", "original_passes": 9,
               "valid_marker_negative": True, "invalid_first_fixture_failure_retained": True},
    "migration": {**mr, "negative_tree": negative["source"], "positive_tree": positive["source"],
                  "original_case": case_name, "child_original_assertion": "marketplaces.rs:588:5",
                  "child_actual_left": [], "original_expected_right": ["claude-plugins-official"],
                  "exact_restoration": restore, "original_package_passes": 166,
                  "nested_success_block_lines": [start + 1, end], "nested_success_block": block,
                  "nested_success_block_identity": identity(block.encode()),
                  "raw_fresh_junit_frozen_roster_agree": True, "program_stability": True},
    "v8_runtime": {**vr, "original_cases_by_binary": class_counts, "original_passes": 76,
                   "both_original_integrations_included": True, "four_programs_stable": True,
                   "raw_fresh_junit_frozen_roster_agree": True},
    "real_bazel_lock_gates": {**lr, "official_binary": bootstrap["installed"], "commands": commands,
                              "actual_generated_changes": [], "module_lock": generation["generated_module_lock"],
                              "task_config_removed": cleanup, "existing_cache_retained": True},
    "final_source_guard": guard,
    "limits_zh": "仅上述原范围与真实锁门已通过；完整workspace与新提交托管CI尚未完成。先前f825原失败、首次Skills夹具准备失败均保留。未关闭任何原B01–B23状态。",
    "all_original_blockers_closed": False,
}
destination = ROOT / "deliverables/fourth-three-repairs-v3-root-review.json"
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"path": str(destination), **identity(destination.read_bytes()),
                  "original_passes": {"skills": 9, "migration": 166, "v8_runtime": 76},
                  "exact_nested_child_output_verified": True, "embedded_originals_verified": 36}))
