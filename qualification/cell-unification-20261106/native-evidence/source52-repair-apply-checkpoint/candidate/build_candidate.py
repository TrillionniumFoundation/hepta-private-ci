#!/usr/bin/env python3
"""Build one isolated test-fixture candidate and audit exact closed evidence."""
from __future__ import annotations

from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path("/workspace/scratch/08f5efd48967")
DEST = ROOT / "network-runtime-wildcard-r26-repair"
SOURCE = "e28b0f385ee882f842911044958b2810f62f6379"
TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
PATH = "codex-rs/network-proxy/src/runtime.rs"
LOG_SHA = "a7f1e74cfc5f621dc2db1bf9b55da64b31ce91cb0e399fb09617ca202156ef68"

FIXTURES = [
    {
        "name": "host_blocked_requires_allowlist_match",
        "settings": 'network_settings(&["example.com"], &[])',
        "purpose": "Exact allowlist matching; initial example.com is allowed and public 8.8.8.8 is not in that allowlist. The separate enabled/broker/default-local loop stays unchanged.",
        "expected_r26_status": "PASS",
        "changed_setup": "Only the first state in this function. Its independent default-config loop still tests broker defaults and loopback denial.",
    },
    {
        "name": "add_allowed_domain_removes_matching_deny_entry",
        "settings": 'network_settings(&[], &["example.com"])',
        "purpose": "Normalize the explicit allow update, remove the conflicting deny entry, preserve pattern readback, then evaluate the same hostname.",
        "expected_r26_status": "PASS",
        "changed_setup": "Initial config only; original add_allowed_domain, current_patterns and all decision assertions are unchanged.",
    },
    {
        "name": "host_blocked_subdomain_wildcards_exclude_apex",
        "settings": 'network_settings(&["*.openai.com"], &[])',
        "purpose": "The subdomain pattern admits api.openai.com and excludes openai.com itself.",
        "expected_r26_status": "FAIL",
        "changed_setup": "Initial config only; original hostname, port, apex exclusion and equality assertions are unchanged.",
    },
    {
        "name": "host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist",
        "settings": 'network_settings(&["*"], &["evil.example"])',
        "purpose": "The global pattern admits two named hosts while the explicit evil.example deny entry wins.",
        "expected_r26_status": "FAIL",
        "changed_setup": "Initial config only; original hostnames, ports, all three equality assertions and deny priority are unchanged.",
    },
]

def require(value, message):
    if not value:
        raise ValueError(message)

def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def jb(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()

def put(name, raw):
    p = DEST / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        require(p.read_bytes() == raw, "existing frozen bytes differ: " + name)
    else:
        with p.open("xb") as f:
            f.write(raw)
    return pin(raw)

def tree_sha(entries):
    ordered = sorted(entries, key=lambda e: (e["path"] + ("/" if e["type"] == "tree" else "")).encode())
    body = b"".join(e["mode"].lstrip("0").encode() + b" " + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"]) for e in ordered)
    return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()

def function_spans(text):
    # Every requested test is a top-level item indented four spaces in mod tests.
    # The next top-level function/attribute is outside its closing brace.
    test_module_start = text.index("#[cfg(test)]\nmod tests {\n")
    starts = list(re.compile(r"(?m)^    (?:async )?fn ([A-Za-z0-9_]+)\(").finditer(text, test_module_start))
    result = {}
    for i, m in enumerate(starts):
        next_start = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        section = text[m.start():next_start]
        end_match = list(re.finditer(r"(?m)^    }\n", section))
        require(end_match, "missing top-level function close: " + m[1])
        end = m.start() + end_match[-1].end()
        result[m[1]] = (m.start(), end, text[m.start():end])
    return result

def main():
    source_context = ROOT / "source51-network-candidate/context/codex-rs/network-proxy/src"
    raw = (source_context / "runtime.rs").read_bytes()
    require(pin(raw) == {
        "bytes": 75473,
        "sha256": "3214446d85796e5d1c4a308ba53aab3bf7098fc18cd38cfc6f97a1cbb14d2e4f",
        "git_blob": "1a449a44381fafa4a5d6a5d0e08753f425f339fc",
    }, "source51 runtime original differs")
    text = raw.decode()
    before = function_spans(text)
    operations = []
    updated = text
    for fixture in FIXTURES:
        name = fixture["name"]
        old = "        let state = network_proxy_state_for_policy(" + fixture["settings"] + ");"
        new = (
            "        // Domain-pattern policy is independent of ambient DNS; address guards have separate tests.\n"
            "        let state = network_proxy_state_for_policy(NetworkProxyConfig {\n"
            "            allow_local_binding: true,\n"
            "            .." + fixture["settings"] + "\n"
            "        });"
        )
        original_function = before[name][2]
        require(original_function.count(old) == 1, "fixture initial state not unique: " + name)
        new_function = original_function.replace(old, new, 1)
        require(updated.count(original_function) == 1, "function not unique: " + name)
        updated = updated.replace(original_function, new_function, 1)
        operations.append({"function": name, "old": old, "new": new,
                           "original_function": original_function,
                           "candidate_function": new_function,
                           "original_function_pin": pin(original_function.encode()),
                           "candidate_function_pin": pin(new_function.encode())})
    after = function_spans(updated)
    inverse = updated
    for operation in reversed(operations):
        require(inverse.count(operation["candidate_function"]) == 1, "inverse function not unique")
        inverse = inverse.replace(operation["candidate_function"], operation["original_function"], 1)
    require(inverse.encode() == raw, "whole-file inverse differs")
    changed = sorted(name for name in before if before[name][2] != after[name][2])
    require(changed == sorted(f["name"] for f in FIXTURES), "extra changed function")
    marker = "#[cfg(test)]\nmod tests {"
    require(text.split(marker, 1)[0] == updated.split(marker, 1)[0], "production or shared test helper changed")
    require(set(before) == set(after), "test/helper names changed")
    first_name = "host_blocked_requires_allowlist_match"
    loop_marker = "        for enabled in [false, true] {"
    require(before[first_name][2].split(loop_marker, 1)[1] == after[first_name][2].split(loop_marker, 1)[1],
            "independent default config loop changed")
    assert_pattern = r"\b(assert(?:_eq|_ne)?|debug_assert(?:_eq|_ne)?)!"
    counts_before = Counter(re.findall(assert_pattern, text))
    counts_after = Counter(re.findall(assert_pattern, updated))
    require(counts_before == counts_after, "assertion token counts changed")

    tree_inputs = {}
    for key in ["root", "codex", "network", "network_src"]:
        rel = "source51-preparation/derived-trees/" + key + ".json"
        data = (ROOT / rel).read_bytes()
        obj = json.loads(data)
        require(tree_sha(obj["entries"]) == obj["expected_git_tree"], "source51 tree object differs")
        put("input/derived-trees/" + key + ".json", data)
        tree_inputs[key] = obj
    require(tree_inputs["root"]["expected_git_tree"] == TREE, "source51 root differs")
    for parent, child, name in [("root", "codex", "codex-rs"), ("codex", "network", "network-proxy"), ("network", "network_src", "src")]:
        entry = next(e for e in tree_inputs[parent]["entries"] if e["path"] == name)
        require(entry["sha"] == tree_inputs[child]["expected_git_tree"], "directory ancestry differs")
    for key in ["codex", "network", "network_src"]:
        require(not any(e["path"] == "AGENTS.md" for e in tree_inputs[key]["entries"]), "nearer instructions exist")
    entries = {e["path"]: e for e in tree_inputs["network_src"]["entries"]}
    source_pins = []
    for name in ["runtime.rs", "config.rs", "policy.rs", "state.rs"]:
        rel = "codex-rs/network-proxy/src/" + name
        data = raw if name == "runtime.rs" else (
            (DEST / "original" / rel).read_bytes() if name in ("config.rs", "policy.rs")
            else (source_context / name).read_bytes()
        )
        require(pin(data)["git_blob"] == entries[name]["sha"], "source51 direct-tree blob differs: " + name)
        put("original/" + rel, data)
        source_pins.append({"path": rel, **pin(data), "git_mode": entries[name]["mode"],
                            "immutable_source_url": "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/" + SOURCE + "/" + rel})
    agents = (ROOT / "source51-final-scope-readonly/original/AGENTS.md").read_bytes()
    require(pin(agents)["git_blob"] == next(e for e in tree_inputs["root"]["entries"] if e["path"] == "AGENTS.md")["sha"], "root instructions differ")
    put("original/AGENTS.md", agents)
    source_pins.append({"path": "AGENTS.md", **pin(agents),
                       "immutable_source_url": "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/" + SOURCE + "/AGENTS.md"})

    evidence = ROOT / "native-validation-results/r26-failure-closed"
    log = (evidence / "native-source51-project-r26-tests.log").read_bytes()
    require(len(log) == 217900 and hashlib.sha256(log).hexdigest() == LOG_SHA, "closed full log differs")
    blocks_raw = (evidence / "closed-failure-blocks.json").read_bytes()
    blocks = json.loads(blocks_raw)
    require(blocks["count"] == len(blocks["blocks"]) == 2, "failure count differs")
    put("evidence/closed-failure-blocks.json", blocks_raw)
    put("evidence/native-LOCAL-READBACK.json", (evidence / "LOCAL-READBACK.json").read_bytes())
    for n, block in enumerate(blocks["blocks"], 1):
        span = log[block["byte_offset"]:block["end_byte_offset"]]
        require(span == block["text"].encode(), "original block text/span differs")
        require(len(span) == block["block_bytes"] and hashlib.sha256(span).hexdigest() == block["block_sha256"], "block pin differs")
        require("NotAllowedLocal" in span.decode() and ">Allowed" in span.decode(), "unexpected failure signature")
        put("evidence/failure-" + str(n) + ".txt", span)

    result_re = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$")
    results = {}
    summary = None
    for line in log.decode().splitlines():
        if re.match(r"^\s*Summary\s+\[", line):
            summary = line
            break
        m = result_re.match(line)
        if m:
            key = (m[3], m[4])
            require(key not in results, "duplicate pre-summary execution row")
            results[key] = {"status": m[1], "seconds": float(m[2]), "line": line}
    require(len(results) == 1564 and Counter(x["status"] for x in results.values()) == {"PASS": 1562, "FAIL": 2}, "full closed execution counts differ")
    require(summary is not None and "3 skipped" in summary, "summary reported skip differs")
    fixture_readback = []
    for fixture, operation in zip(FIXTURES, operations):
        row = results[("codex-network-proxy", "runtime::tests::" + fixture["name"])]
        require(row["status"] == fixture["expected_r26_status"], "fixture original status differs")
        fixture_readback.append({
            **fixture, "original_execution": row, "all_original_assertions_preserved": True,
            "original_function": operation["original_function"],
            "original_function_pin": operation["original_function_pin"],
            "candidate_function_pin": operation["candidate_function_pin"],
            "source_path": PATH,
            "original_first_line": text[:before[fixture["name"]][0]].count("\n") + 1,
            "lookup_path_before": "network_settings -> default allow_local_binding=false -> test-local network_proxy_state_for_policy -> host_blocked -> explicit deny first -> DNS/local-address guard for nonliteral hosts -> allowlist",
            "candidate_boundary": "Only this fixture's first config sets the existing allow_local_binding=true. No new network request, resolver override, production setting or default is introduced.",
        })
    preserved = []
    for name, (_, _, body) in before.items():
        if name not in changed and (".host_blocked(" in body or name.startswith("host_resolves_to_non_public_ip_") or name.startswith("compile_globset_") or name == "validate_policy_against_constraints_disallows_allow_local_binding_when_managed_disabled"):
            require(body == after[name][2], "guard test changed")
            preserved.append({"function": name, "source_first_line": text[:before[name][0]].count("\n") + 1,
                              "body_pin": pin(body.encode()), "body_unchanged": True,
                              "r26_original_execution": results.get(("codex-network-proxy", "runtime::tests::" + name))})
    require(sum(x["function"].startswith("host_resolves_to_non_public_ip_") for x in preserved) == 4, "four injected resolver boundary tests missing")
    put("FIXTURE-ORACLES.json", jb({"schema": "hepta.network-runtime-r26-fixture-oracles.v1", "fixtures": fixture_readback, "preserved_related_tests": preserved,
                                  "not_all_four_failed": True, "two_passing_fixtures_are_same_precondition_repair": True}))
    put("edit-operations.json", jb({"schema": "hepta.exact-four-test-initial-state-edits.v1", "operations": operations}))
    candidate = updated.encode()
    put("source/" + PATH, candidate)
    diff = "".join(difflib.unified_diff(text.splitlines(keepends=True), updated.splitlines(keepends=True), fromfile="a/" + PATH, tofile="b/" + PATH, n=3)).encode()
    put("repair.patch", diff)
    source_manifest = (ROOT / "source51-preparation/native-candidate-r26-source.json").read_bytes()
    put("input/source51-manifest.json", source_manifest)
    source51 = json.loads(source_manifest)
    require(source51["source_commit"] == SOURCE and source51["source_tree"] == TREE and len(source51["changed_files"]) == 194, "base source manifest differs")
    require(PATH not in {r["path"] for r in source51["changed_files"]}, "runtime already in changed manifest")
    require(sum(r["path"].endswith(".rs") for r in source51["changed_files"]) == 180, "base Rust count differs")
    sm = {"schema": "hepta.network-runtime-r26-candidate-source.v1", "source_before_commit": SOURCE, "source_before_tree": TREE,
          "candidate_commit": None, "candidate_tree": None, "native_applied": False, "rust_executed": False,
          "files": [{"path": PATH, "owner": "codex-network-proxy", "git_mode": "100644", "before": pin(raw), "after": pin(candidate)}],
          "changed_from_source51_paths": [PATH], "expected_total_changed_paths_vs_framework": 195,
          "expected_rust_paths": 181, "expected_other_paths": 14, "source51_original_194_manifest_rows_unchanged": True,
          "rust_owner_count_unchanged": 26, "ci_selector_count_unchanged": 27,
          "dependency_inputs_changed": [], "lock_changes": [], "patch": pin(diff)}
    put("source-manifest.json", jb(sm))
    put("source-input-pins.json", jb({"schema": "hepta.network-runtime-r26-primary-sources.v1", "source_commit": SOURCE, "source_tree": TREE,
                                     "sources": source_pins, "nearest_guidance": "root AGENTS.md only, proven by each fixed ancestor direct tree",
                                     "root_to_src_direct_links_checked": True, "no_network_probe_performed": True}))
    audit = {
        "schema": "hepta.network-runtime-r26-repair-audit.v1",
        "status": "FROZEN_ISOLATED_FIXTURE_CANDIDATE_NOT_NATIVE_QUALIFIED",
        "source": sm,
        "observed": {
            "full_closed_log": {**pin(log), "original_local_path": str(evidence / "native-source51-project-r26-tests.log")},
            "pre_summary_unique_results": 1564, "passed": 1562, "failed": 2, "timeouts": 0, "reported_skip": 3,
            "summary_line": summary, "failure_blocks": [{k: b[k] for k in ("name", "seconds", "byte_offset", "end_byte_offset", "block_bytes", "block_sha256")} for b in blocks["blocks"]],
            "failure_signature": "Both api.openai.com Allowed assertions actually returned Blocked(NotAllowedLocal).",
            "other_two_original_results": [{"name": f["name"], **results[("codex-network-proxy", "runtime::tests::" + f["name"])]} for f in FIXTURES[:2]],
        },
        "causal_inference_from_exact_source_and_observed_return": [
            "The test helper keeps the default allow_local_binding=false and only enables this in-memory proxy config.",
            "Explicit deny has priority; an unallowed pattern yields NotAllowed, not NotAllowedLocal.",
            "api.openai.com is neither a loopback name nor an IP literal under the fixed Host parser. Its observed NotAllowedLocal therefore points to host_resolves_to_non_public_ip returning true before the allowlist decision.",
            "That helper returns true on resolver error, deadline expiry, or any non-public answer. The original failure blocks do not distinguish these causes and contain no resolver trace.",
            "The global test reached its second assertion for api.openai.com; its first example.com assertion had already completed. The subdomain test failed at its first api.openai.com assertion.",
        ],
        "unobserved": ["specific DNS answer", "specific DNS error", "actual DNS timeout event", "syscall or network trace", "candidate native PASS"],
        "minimal_change": "Only four individual hostname-pattern/list-update test initial configs explicitly set existing allow_local_binding=true; the shared helper, resolver, production config/defaults, constraints and guard order are unchanged.",
        "why_not_just_the_two_failures": "The same module has exactly two additional positive named-host policy oracles with the identical default external-DNS precondition. They passed r26 and are explicitly not called failures.",
        "preservation": {
            "whole_file_inverse_exact": True, "changed_top_level_functions": changed,
            "all_other_top_level_functions_byte_identical": True,
            "production_and_shared_test_state_helper_prefix_byte_identical": True,
            "all_test_names_preserved": True, "test_attributes_unchanged": True,
            "assertion_token_counts_before": dict(counts_before), "assertion_token_counts_after": dict(counts_after),
            "requires_allowlist_match_independent_default_config_loop_byte_identical": True,
            "four_injected_resolver_boundary_tests_byte_identical": True,
            "preserved_related_test_count": len(preserved),
            "all_original_timeouts_hosts_ports_and_assertions_preserved": True,
        },
        "safety_scope": {
            "production_default_allow_local_binding": False,
            "new_production_bypass": False, "environment_override": False,
            "allowlist_denylist_or_address_guard_implementation_changed": False,
            "shared_network_settings_helper_changed": False, "new_dependency_or_lock_change": False,
            "native_source_written": False, "tests_or_probe_run": False,
        },
    }
    put("repair-audit.json", jb(audit))
    readme = """# r26 runtime 域名策略 fixture 修复候选

基线固定为 source51 e28b0f385ee882f842911044958b2810f62f6379 / tree 763c8d2b4089f6e9806c3bbb68fa247bc2f6af36。候选只改 codex-rs/network-proxy/src/runtime.rs 内四个测试的初始 config；没有修改 canonical/native 源码，没有运行 Rust 或网络探针。

## 实际失败与限界

原 r26 两项 wildcard 用例均在 api.openai.com 的 Allowed 断言得到 Blocked(NotAllowedLocal)。固定源码先执行 deny，然后执行 DNS／local-address guard，最后判断 allowlist；该输入既非 localhost，也非 IP 字面量。因此可把失败定位到 allowlist 之前的 DNS/IP 检查路径。原失败块没有记录 DNS 答案、错误或超时事件，不能从约五秒总耗时指定其中任何一个原因。

同模块另两项命名主机策略／名单更新用例在本轮分别 PASS 0.116s 与 PASS 0.008s；它们具有相同外部解析前置。本候选一起修正这两项前置，不把它们写成已失败。

## 精确改动

四个独立 fixture 的第一个 config 显式使用现有 allow_local_binding=true，仅让被测域名 pattern／名单更新语义独立于环境 DNS。所有原 host、port、deny、apex、计数、断言和超时都保留。原共享 helper 与生产默认 false 不改。

host_blocked_requires_allowlist_match 内独立 enabled/broker/default-config 循环逐字保留。localhost、private/scoped literals、deny 优先、受管 local-binding 限制、真实 .invalid 拒绝，以及四个注入 lookup 的 timeout/error/private/public 边界测试均逐字保留；没有全局启用 local binding。

FIXTURE-ORACLES.json 保存四份完整原函数与原断言、实际 r26 结果，以及同模块未改 guard 测试清单。repair-audit.json 分开列出原观察、源码推导与仍未知的具体 resolver 原因。

## 范围与交接

runtime.rs 是既有仓库文件，但此前不在相对 framework 的194路径清单中。若采用这个单叶候选，清单应变为195路径＝181 Rust＋14其他；source51原194行保持，26 owner／27 CI选择项不变，无依赖或锁变更。具体新 commit/tree 仍为 null，由 root 后续固定。

repair.patch、source-manifest.json、edit-operations.json 与 source-input-pins.json 可独立核原文、四处配置替换及整文件逆变换。当前只具备静态候选，原 r26 仍 FAIL；需新身份下原完整项目门和后续默认工作区门实际验证。
"""
    put("README.md", readme.encode())
    files = []
    for p in sorted(DEST.rglob("*")):
        if p.is_file() and p.name != "HANDOFF-MANIFEST.json":
            files.append({"path": str(p.relative_to(DEST)), **pin(p.read_bytes())})
    handoff = {"schema": "hepta.network-runtime-r26-handoff.v1", "status": "FROZEN_ISOLATED_CANDIDATE_NO_NATIVE_EXECUTION",
               "source_before_commit": SOURCE, "source_before_tree": TREE,
               "file_count": len(files), "total_bytes": sum(x["bytes"] for x in files), "files": files}
    put("HANDOFF-MANIFEST.json", jb(handoff))
    print(json.dumps({"candidate": pin(candidate), "patch": pin(diff), "audit": pin(jb(audit)),
                      "handoff": pin(jb(handoff)), "files": len(files), "changed_functions": changed,
                      "preserved_related_tests": len(preserved),
                      "assertion_tokens": dict(counts_before)}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
