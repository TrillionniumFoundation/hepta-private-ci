"""Offline independent byte/source review; no Rust, network, or candidate execution."""
from pathlib import Path
import difflib
import hashlib
import json
import re

ROOT = Path("/workspace/scratch/08f5efd48967")
C = ROOT / "network-runtime-wildcard-r26-repair"
O = ROOT / "network-runtime-wildcard-r26-independent-review"
PATH = "codex-rs/network-proxy/src/runtime.rs"

def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def exact_patch(raw, patch, reverse=False):
    lines = raw.decode().splitlines(keepends=True)
    source = patch.decode().splitlines(keepends=True)
    out, offset, i = [], 0, 2
    while i < len(source):
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", source[i])
        assert match, source[i]
        old_start, old_count, new_start, new_count = (
            int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
        start = (new_start if reverse else old_start) - 1
        assert start >= offset
        out.extend(lines[offset:start])
        offset = start
        consumed = produced = 0
        i += 1
        while i < len(source) and not source[i].startswith("@@ "):
            item = source[i]
            sign, content = item[0], item[1:]
            if reverse:
                sign = {"-": "+", "+": "-", " ": " "}[sign]
            assert sign in " +-"
            if sign in " -":
                assert offset < len(lines) and lines[offset] == content
                offset += 1
                consumed += 1
            if sign in " +":
                out.append(content)
                produced += 1
            i += 1
        assert consumed == (new_count if reverse else old_count)
        assert produced == (old_count if reverse else new_count)
    out.extend(lines[offset:])
    return "".join(out).encode()

def main():
    O.mkdir(exist_ok=True)
    handoff_raw = (C / "HANDOFF-MANIFEST.json").read_bytes()
    handoff = json.loads(handoff_raw)
    for row in handoff["files"]:
        assert pin((C / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    before, after, patch = ((C / p).read_bytes() for p in ("original/" + PATH, "source/" + PATH, "repair.patch"))
    manifest = json.loads((C / "source-manifest.json").read_bytes())
    assert pin(before) == manifest["files"][0]["before"]
    assert pin(after) == manifest["files"][0]["after"]
    assert pin(patch) == manifest["patch"]
    assert exact_patch(before, patch) == after
    assert exact_patch(after, patch, reverse=True) == before
    generated = "".join(difflib.unified_diff(
        before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
        fromfile="a/" + PATH, tofile="b/" + PATH)).encode()
    assert generated == patch
    fixtures = [
        ("host_blocked_requires_allowlist_match", 'network_settings(&["example.com"], &[])', "PASS"),
        ("add_allowed_domain_removes_matching_deny_entry", 'network_settings(&[], &["example.com"])', "PASS"),
        ("host_blocked_subdomain_wildcards_exclude_apex", 'network_settings(&["*.openai.com"], &[])', "FAIL"),
        ("host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist",
         'network_settings(&["*"], &["evil.example"])', "FAIL"),
    ]
    replay = before.decode()
    fixture_rows = []
    for name, settings, expected_status in fixtures:
        pattern = r"(?ms)^    async fn " + re.escape(name) + r"\(\) \{.*?^    \}\n"
        old = re.search(pattern, before.decode()).group()
        new = re.search(pattern, after.decode()).group()
        one = "        let state = network_proxy_state_for_policy(" + settings + ");"
        replacement = (
            "        // Domain-pattern policy is independent of ambient DNS; address guards have separate tests.\n"
            "        let state = network_proxy_state_for_policy(NetworkProxyConfig {\n"
            "            allow_local_binding: true,\n"
            "            .." + settings + "\n"
            "        });")
        assert old.count(one) == new.count(replacement) == 1
        assert old.replace(one, replacement, 1) == new
        assert new.replace(replacement, one, 1) == old
        assert replay.count(old) == 1
        replay = replay.replace(old, new, 1)
        fixture_rows.append({"name": name, "original_r26_status": expected_status,
                             "all_body_bytes_except_initial_config_preserved": True,
                             "old_function": pin(old.encode()), "new_function": pin(new.encode())})
    assert replay.encode() == after
    assert before[:before.index(b"    async fn host_blocked_requires_allowlist_match")] == after[:after.index(b"    async fn host_blocked_requires_allowlist_match")]
    # The first fixture's independent default-config broker/loopback checks remain exact.
    old_fn = re.search(r"(?ms)^    async fn host_blocked_requires_allowlist_match\(\) \{.*?^    \}\n", before.decode()).group()
    new_fn = re.search(r"(?ms)^    async fn host_blocked_requires_allowlist_match\(\) \{.*?^    \}\n", after.decode()).group()
    assert old_fn[old_fn.index("        for enabled in"): ] == new_fn[new_fn.index("        for enabled in"): ]
    assertion_counts = {key: len(re.findall(rb"\b" + key.encode() + rb"!\s*\(", before))
                        for key in ("assert", "assert_eq", "assert_ne")}
    assert assertion_counts == {key: len(re.findall(rb"\b" + key.encode() + rb"!\s*\(", after))
                                for key in assertion_counts}
    raw_log = (ROOT / "native-validation-results/r26-failure-closed/native-source51-project-r26-tests.log").read_bytes()
    assert pin(raw_log)["sha256"] == "a7f1e74cfc5f621dc2db1bf9b55da64b31ce91cb0e399fb09617ca202156ef68"
    audit = json.loads((C / "repair-audit.json").read_bytes())
    for row in audit["observed"]["failure_blocks"]:
        block = raw_log[row["byte_offset"]:row["end_byte_offset"]]
        assert pin(block)["sha256"] == row["block_sha256"] and len(block) == row["block_bytes"]
        assert b"NotAllowedLocal" in block and b">Allowed" in block
    execution = raw_log.split(b"     Summary [", 1)[0]
    for row in fixture_rows:
        matches = re.findall(rb"(?m)^\s*(PASS|FAIL|TIMEOUT)\s+\[[^\]]+\]\s+codex-network-proxy runtime::tests::"
                             + row["name"].encode() + rb"\s*$", execution)
        assert matches == [row["original_r26_status"].encode()]
    report = {
        "schema": "hepta.network-runtime-r26-independent-review.v1",
        "status": "STATIC_CLEAR_NOT_NATIVE_QUALIFICATION",
        "source_before_commit": manifest["source_before_commit"],
        "source_before_tree": manifest["source_before_tree"],
        "handoff": pin(handoff_raw), "all_handoff_files_rehashed": handoff["file_count"],
        "before": pin(before), "after": pin(after), "patch": pin(patch),
        "patch_forward_reverse_and_exact_regeneration": True,
        "four_independent_literal_replacements_reproduce_entire_after_file": True,
        "all_original_assertion_macros_counts": assertion_counts,
        "fixture_rows": fixture_rows,
        "default_broker_loopback_loop_and_production_prefix_preserved": True,
        "default_allow_local_binding_false_definition_unchanged": True,
        "dedicated_DNS_error_timeout_private_loopback_tests_not_modified": True,
        "causal_boundary": {
            "observed": "Exactly the two wildcard tests returned NotAllowedLocal where Allowed was required.",
            "source_order": "Explicit deny, then default DNS/local-address guard, then allowlist matching.",
            "inference": "For api.openai.com the local-address guard's resolver helper returned true before allowlist evaluation.",
            "not_observed": ["DNS answer", "DNS error", "actual resolver timeout event", "network/syscall trace", "candidate native PASS"],
            "other_two_fixtures": "Both passed r26; the same local-config adjustment removes the same unrelated ambient-DNS precondition from their hostname policy oracles.",
        },
        "scope": {"changed_repo_paths": [PATH], "new_total_changed_paths": 195, "rust_paths": 181,
                  "other_paths": 14, "owners": 26, "CI_selectors": 27,
                  "source51_original_194_rows_unchanged": True},
        "execution": {"Rust": False, "network_probe": False, "native_mutation": False,
                      "candidate_or_guard_test_execution": False},
        "full_log_pin": pin(raw_log),
    }
    out = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    (O / "INDEPENDENT-REVIEW.json").write_bytes(out)
    print(json.dumps({"report": pin(out), "status": report["status"]}))

if __name__ == "__main__":
    main()
