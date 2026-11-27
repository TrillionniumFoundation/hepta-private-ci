import collections
import datetime
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import types

ROOT = pathlib.Path("/home/qian-qi/hepta-rust-protection-20261120-0cee")
EVIDENCE = ROOT / "history-audit-evidence"
REFRESH = EVIDENCE / "refresh-565"
HISTORY = ROOT / "history.git"
EXPORT = REFRESH / "export"
GIT = "/usr/bin/git"
NAME = "codex/hia-chrono-time-network-proxy-20261119-a11"
OLD = "c32019b1e1ef566419a7b6d28a34d24270cf3d27"
NEW = "5653790ac0f64783c28926dcfca2fa7a48a40e77"
SOURCE_SHA = "d5d4047be9282be9760af63a9a0aa1e3e33e4cd85775025fbdf18b91e0aad5f7"
POLICY_SHA = "262d189d478d0a072e5b2c6ae278b2fe084ca0cedba92df7960cc0d05546791f"
BASE_EXPORT_SHA = "35408e04e4516d5e976632d3a6f4da15efd3f442389604f7af7cdfbf02e1cfd2"
BASE_RESULT_SHA = "1a94c299150ebad0feb080d7aa666c8624d16fcd1325c0f9c5b6cb2f3c7fd8ca"
KEY = "hepta-rust-protection-0cee-hia565-refresh-20261120-v1"
START = time.monotonic()
AUDIT_SOURCE = globals().get("AUDIT_SOURCE") or pathlib.Path(__file__).read_text()
os.umask(0o077)
os.environ.update(GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
sys.dont_write_bytecode = True
inputs = {}
result = {
    "schema": "hepta.single-protected-tip-refresh.v1",
    "repository": "TrillionniumFoundation/hepta-private-ci",
    "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "process_key": KEY,
    "base_audit_result_sha256": BASE_RESULT_SHA,
    "base_export_manifest_sha256": BASE_EXPORT_SHA,
    "production_source_sha256": SOURCE_SHA,
    "production_manifest_sha256": POLICY_SHA,
    "tip_change": {"name": NAME, "before": OLD, "after": NEW},
    "completed": False,
    "remote_mutations": False,
    "prior_evidence_modified": False,
    "production_inputs_modified": False,
}
def require(ok, why):
    if not ok:
        raise RuntimeError(why)
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
def serialized(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
def meta(raw):
    return {"bytes": len(raw), "sha256": sha(raw), "git_blob_sha1": blob(raw)}
def read_input(path, expected=None):
    path = pathlib.Path(path)
    require(path.resolve() == path and path.is_file() and path.stat().st_nlink == 1, "Unexpected input identity: " + str(path))
    raw = path.read_bytes()
    if expected:
        require(sha(raw) == expected, "Input hash changed: " + str(path))
    inputs[str(path)] = sha(raw)
    return raw
def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), **meta(raw)}
def write_json(path, value):
    return write(path, serialized(value))
def git(args, input_text=None, env=None, check=True, timeout=60):
    proc = subprocess.run([GIT, "--no-replace-objects", "-C", str(HISTORY), *args],
        input=input_text, text=True, encoding="utf-8", errors="surrogateescape",
        capture_output=True, env=env, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError("Git failed: " + args[0] + "\n" + proc.stderr[-2000:])
    return proc
def advertised(raw):
    heads = {}
    for line in raw.splitlines():
        tip, ref = line.split("\t", 1)
        require(re.fullmatch("[0-9a-f]{40}", tip) and ref.startswith("refs/heads/"), "Unexpected advertised ref")
        name = ref.removeprefix("refs/heads/")
        require(name not in heads, "Duplicate advertised name")
        heads[name] = tip
    require("main" in heads, "No main in advertisement")
    return heads
def delta(before, after):
    return {
        "added": {n: s for n, s in after.items() if n not in before},
        "removed": {n: s for n, s in before.items() if n not in after},
        "changed": {n: {"before": before[n], "after": s} for n, s in after.items() if n in before and before[n] != s},
    }
def parse_graph(raw):
    graph, order = {}, []
    for row in raw.splitlines():
        tip, *parents = row.split()
        require(re.fullmatch("[0-9a-f]{40}", tip) and all(re.fullmatch("[0-9a-f]{40}", p) for p in parents), "Invalid parent row")
        require(tip not in graph and all(p in graph for p in parents), "Incomplete or unordered parent graph")
        graph[tip] = parents
        order.append(tip)
    return graph, order
def fixed_file_digest(path):
    return sha(path.read_bytes()) if path.is_file() else None
def compress(raw):
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=9, mtime=0) as zipped:
        zipped.write(raw)
    return stream.getvalue()

try:
    require(ROOT.resolve() == ROOT and EVIDENCE.resolve() == EVIDENCE and HISTORY.resolve() == HISTORY, "Audit paths changed")
    require(not os.path.lexists(REFRESH), "Refuse an existing refresh namespace")
    base_raw = read_input(EVIDENCE / "full-history-result.json", BASE_RESULT_SHA)
    base = json.loads(base_raw)
    read_input(EVIDENCE / "export/export-manifest.json", BASE_EXPORT_SHA)
    old_refs_raw = read_input(base["captured_refs_artifact"]["path"], base["captured_refs_artifact"]["sha256"])
    old_heads = json.loads(old_refs_raw)
    old_graph_raw = read_input(base["commit_parent_graph_artifact"]["path"], base["commit_parent_graph_artifact"]["sha256"])
    old_protected_raw = read_input(base["protected_classification_artifact"]["path"], base["protected_classification_artifact"]["sha256"])
    old_protected = json.loads(old_protected_raw)
    source_path = ROOT / "candidate/tools/branch-consolidation/hepta_branch_consolidation.py"
    policy_path = ROOT / "candidate/tools/branch-consolidation/protected-branches.json"
    source_bytes = read_input(source_path, SOURCE_SHA)
    policy_raw = read_input(policy_path, POLICY_SHA)
    policy = json.loads(policy_raw)
    require(old_heads[NAME] == OLD, "Base captured head is not expected old pin")
    require(git(["rev-parse", "--is-shallow-repository"]).stdout.strip() == "false", "History became shallow")
    local_refs_before = git(["for-each-ref", "--format=%(refname)\t%(objectname)\t%(symref)"]).stdout.encode()
    fetch_head_before = fixed_file_digest(HISTORY / "FETCH_HEAD")
    REFRESH.mkdir(mode=0o700)
    write(REFRESH / "refresh-audit.py", AUDIT_SOURCE.encode())
    write_json(REFRESH / "invocation.json", {
        "host": "rog", "idempotency_key": KEY, "executable": "/usr/bin/python3",
        "args": ["-"], "cwd": str(ROOT), "cpu_quota_percent": 100,
        "memory_max_bytes": 1073741824, "nice": 10, "timeout_seconds": 180,
        "stdin_construction": "AUDIT_SOURCE = json.dumps(refresh-audit.py UTF-8 text) + newline; exec(compile(AUDIT_SOURCE, '<hia565-refresh>', 'exec'))",
        "source_sha256": sha(AUDIT_SOURCE.encode()),
    })
    remote = git(["-c", "protocol.version=2", "ls-remote", "--heads", "origin"],
        env={**os.environ, "GIT_TRACE_PACKET": "2"})
    cap_lines = [line for line in remote.stderr.splitlines() if re.search(r"\bfetch=[^\r\n]*\bfilter\b", line)]
    require(cap_lines, "Server does not advertise filtering; no fetch attempted")
    write(REFRESH / "server-filter-capabilities.txt", ("\n".join(cap_lines) + "\n").encode())
    heads = advertised(remote.stdout)
    captured_raw = serialized(heads)
    result["captured_refs"] = write(REFRESH / "captured-refs.json", captured_raw)
    result["captured_ref_count"] = len(heads)
    expected_delta = {"added": {}, "removed": {}, "changed": {NAME: {"before": OLD, "after": NEW}}}
    captured_delta = delta(old_heads, heads)
    result["captured_delta_from_base"] = captured_delta
    require(captured_delta == expected_delta, "Unexpected initial ref drift; no chase or fetch attempted")
    refs_delta = {
        "schema": "hepta.exact-ref-snapshot-delta.v1",
        "base_captured_refs": meta(old_refs_raw),
        "captured_refs": meta(captured_raw),
        "base_export_manifest_sha256": BASE_EXPORT_SHA,
        **captured_delta,
    }
    rebuilt = dict(old_heads)
    rebuilt[NAME] = NEW
    require(serialized(rebuilt) == captured_raw, "Reference delta does not reconstruct exact snapshot")
    refs_delta_raw = serialized(refs_delta)
    write(REFRESH / "refs-delta.json", refs_delta_raw)
    print(json.dumps({"phase": "captured_expected_hia_delta", "refs": len(heads), "new_tip": NEW}), flush=True)

    fetch_args = ["fetch", "--filter=tree:0", "--no-tags", "--no-auto-maintenance",
        "--no-write-commit-graph", "--no-write-fetch-head", "origin", NEW]
    write_json(REFRESH / "fetch-request.json", {"cwd": str(HISTORY), "args": fetch_args, "no_unfiltered_fallback": True})
    fetched = git(fetch_args, check=False, timeout=60)
    write(REFRESH / "fetch.stdout.txt", fetched.stdout.encode())
    write(REFRESH / "fetch.stderr.txt", fetched.stderr.encode())
    require(fetched.returncode == 0, "Explicit filtered tip fetch failed; no fallback")
    require("filtering not recognized" not in fetched.stderr.lower() and "does not support filter" not in fetched.stderr.lower(), "Server ignored requested filter")
    require(local_refs_before == git(["for-each-ref", "--format=%(refname)\t%(objectname)\t%(symref)"]).stdout.encode(), "Local refs changed unexpectedly")
    require(fetch_head_before == fixed_file_digest(HISTORY / "FETCH_HEAD"), "FETCH_HEAD changed unexpectedly")
    result["local_refs_unchanged"] = True
    result["fetch_head_unchanged"] = True
    result["fetch_head_sha256"] = fetch_head_before
    result["local_refs_sha256"] = sha(local_refs_before)
    raw_commit_proc = subprocess.run([GIT, "--no-replace-objects", "-C", str(HISTORY), "cat-file", "commit", NEW],
        capture_output=True, check=True, timeout=30)
    commit_raw = raw_commit_proc.stdout
    commit_id = hashlib.sha1(b"commit " + str(len(commit_raw)).encode() + b"\0" + commit_raw).hexdigest()
    parents = [row[7:].decode("ascii") for row in commit_raw.split(b"\n\n", 1)[0].splitlines() if row.startswith(b"parent ")]
    require(commit_id == NEW and parents == [OLD], "Fetched actual commit identity or sole parent differs")
    result["actual_new_commit"] = {**write(REFRESH / "new-commit.raw", commit_raw), "git_commit_sha1": commit_id, "parents": parents}
    object_types = dict(collections.Counter(git(["cat-file", "--batch-all-objects", "--batch-check=%(objecttype)"]).stdout.splitlines()))
    require(object_types == {"commit": base["parent_graph_nodes"] + 1}, "Unexpected object inventory after single commit fetch")
    result["local_object_types"] = object_types

    trace = REFRESH / "classification.packet.txt"
    os.environ["GIT_TRACE_PACKET"] = str(trace)
    module = types.ModuleType("hepta_branch_consolidation_refresh_verified")
    module.__file__ = str(source_path)
    exec(compile(source_bytes, str(source_path), "exec"), module.__dict__)
    protected = module.protected_branches(HISTORY, heads, policy)
    frozen = module.freeze_protection(heads, policy, protected)
    protected_raw = serialized(protected)
    require(protected_raw == old_protected_raw, "Protected-name classification changed beyond the recorded tip advance")
    old_pins = set(policy["historicalProtectedCommits"])
    new_pins = set(frozen["historicalProtectedCommits"])
    require(len(old_pins) == 504 and new_pins == old_pins | {NEW} and len(new_pins) == 505, "Frozen policy did not retain exact old pins plus new tip")
    require(OLD in new_pins and frozen["protectedHeads"][NAME] == NEW, "Old and new HIA tip not both preserved")
    require(len(protected) == 483, "Protected name count changed")
    frozen_raw = serialized(frozen)
    result["observed_protection"] = write(REFRESH / "observed-protection-505.json", frozen_raw)
    result["protected_name_count"] = len(protected)
    result["production_pin_count"] = len(old_pins)
    result["observed_pin_count"] = len(new_pins)
    result["protected_classification_alias_sha256"] = sha(protected_raw)
    result["new_tip_protection_reasons"] = protected[NAME]

    old_graph, old_order = parse_graph(old_graph_raw.decode("ascii"))
    all_seeds = old_pins | set(policy["hiaRootCommits"]) | set(policy["protectedHeads"].values()) | set(policy["protectedBaseHeads"].values())
    graph_output = git(["rev-list", "--parents", "--topo-order", "--reverse", "--stdin"],
        input_text="\n".join(sorted(set(heads.values()) | all_seeds)) + "\n").stdout
    graph, order = parse_graph(graph_output)
    require(set(graph) - set(old_graph) == {NEW} and not set(old_graph) - set(graph), "Unexpected full graph vertex delta")
    require(all(graph[node] == old_graph[node] for node in old_graph) and graph[NEW] == [OLD], "Pre-existing parent edges changed")
    require((set(heads.values()) | all_seeds) <= set(graph), "Captured head or protected pin missing from complete graph")
    appended_row = NEW + " " + OLD + "\n"
    canonical_graph_raw = old_graph_raw + appended_row.encode()
    graph_delta = {
        "schema": "hepta.complete-parent-graph-delta.v1",
        "base_parent_graph": meta(old_graph_raw),
        "canonical_new_parent_graph": {**meta(canonical_graph_raw), "ordering": "unchanged original rows plus the new child row"},
        "base_graph_nodes": len(old_graph), "new_graph_nodes": len(graph),
        "new_parent_rows": [appended_row],
        "new_commit_object": {**meta(commit_raw), "git_commit_sha1": NEW, "parents": parents},
        "removed_nodes": [], "changed_existing_parent_lists": [],
        "all_actual_git_parent_rows_match_base_plus_delta": True,
        "missing_parents": 0,
    }
    graph_delta_raw = serialized(graph_delta)
    write(REFRESH / "graph-delta.json", graph_delta_raw)
    result["graph_delta"] = {**meta(graph_delta_raw), "base_nodes": len(old_graph), "current_nodes": len(graph), "missing_parents": 0}
    ordinary = {name: tip for name, tip in heads.items() if name != "main" and name not in protected}
    old_ordinary = {name: tip for name, tip in old_heads.items() if name != "main" and name not in old_protected}
    require(ordinary == old_ordinary, "Ordinary name/SHA map changed")
    coverage = {}
    protected_tips = {heads[name] for name in protected}
    for label, old_entry in base["coverage"].items():
        target = old_entry["sha"]
        ancestors, stack = set(), [target]
        while stack:
            node = stack.pop()
            if node not in ancestors:
                ancestors.add(node)
                stack.extend(graph[node])
        included = {name: tip for name, tip in ordinary.items() if tip in ancestors}
        pending = {name: tip for name, tip in ordinary.items() if tip not in ancestors}
        pending_tips = set(pending.values())
        below = set()
        for node in reversed(order):
            if node in pending_tips or node in below:
                below.update(graph[node])
        maximal = pending_tips - below
        frontier = {name: tip for name, tip in pending.items() if tip in maximal}
        maps = {"covered": included, "pending": pending, "frontier": frontier}
        for kind, value in maps.items():
            raw = serialized(value)
            require(sha(raw) == old_entry[kind + "_artifact"]["sha256"] and len(raw) == old_entry[kind + "_artifact"]["bytes"], "Coverage map changed for " + label + ":" + kind)
        require(not new_pins & ancestors and not protected_tips & ancestors, "HIA ancestry intersects audited target")
        coverage[label] = {
            "sha": target, "ancestor_commits": len(ancestors),
            "ordinary_names_covered": len(included), "ordinary_names_pending": len(pending),
            "pending_distinct_tips": len(pending_tips), "pending_maximal_tips": len(maximal),
            "pending_frontier_names": len(frontier),
            "all_original_coverage_map_hashes_unchanged": True,
            "protected_pin_intersection": [], "current_protected_tip_intersection": [],
        }
    require(not trace.exists() or trace.stat().st_size == 0, "Unexpected classification protocol traffic")
    os.environ.pop("GIT_TRACE_PACKET", None)
    result["classification_no_lazy_fetch"] = "1"
    result["classification_packet_bytes"] = 0
    result["ordinary_heads_unchanged"] = True
    result["ordinary_name_count"] = len(ordinary)
    result["coverage"] = coverage
    fresh = advertised(git(["ls-remote", "--heads", "origin"]).stdout)
    fresh_raw = serialized(fresh)
    result["fresh_ref_count"] = len(fresh)
    result["fresh_refs"] = meta(fresh_raw)
    result["captured_to_fresh_delta"] = delta(heads, fresh)
    result["fresh_matches_captured"] = heads == fresh
    if heads != fresh:
        write(REFRESH / "fresh-remote-refs.json", fresh_raw)
    for path, expected in inputs.items():
        require(sha(pathlib.Path(path).read_bytes()) == expected, "Original input changed during refresh")
    result["all_recorded_original_inputs_unchanged"] = True
    result["completed"] = True
    result["outcome"] = "PASS_SINGLE_HIA_TIP_REFRESH" if heads == fresh else "PASS_CAPTURED_REFRESH_WITH_LATER_REF_DRIFT"
    result["elapsed_seconds"] = time.monotonic() - START
    result["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result_raw = serialized(result)
    write(REFRESH / "refresh-result.json", result_raw)

    EXPORT.mkdir(mode=0o700)
    payloads = []
    def export_text(name, raw, role):
        entry = write(EXPORT / name, raw)
        entry["path"] = name
        entry["role"] = role
        payloads.append(entry)
        return entry
    compressed = []
    for filename, raw, role in [
        ("refs-delta.json.gz", refs_delta_raw, "exact lossless ref delta against original captured refs"),
        ("graph-delta.json.gz", graph_delta_raw, "complete actual Git graph delta and appended canonical parent row"),
        ("new-commit.raw.gz", commit_raw, "exact newly fetched commit object bytes"),
        ("observed-protection-505.json.gz", frozen_raw, "monotone observed protection policy; production policy remains unchanged"),
    ]:
        packed = compress(raw)
        require(len(packed) <= 65536 and packed == compress(raw) and gzip.decompress(packed) == raw, "Compressed delta artifact roundtrip failed")
        entry = export_text(filename, packed, role)
        compressed.append({
            **entry, "raw_bytes": len(raw), "raw_sha256": sha(raw),
            "raw_git_blob_sha1": blob(raw), "raw_start_offset": 0, "raw_end_offset": len(raw),
            "independently_decompressible": True, "roundtrip_bytes_equal_original": True,
        })
    export_text("refresh-result.json", result_raw, "exact native refresh result")
    export_text("refresh-audit.py", AUDIT_SOURCE.encode(), "exact native refresh source")
    export_text("invocation.json", (REFRESH / "invocation.json").read_bytes(), "runtime invocation identity")
    readme = """# One protected HIA tip refresh

This append-only refresh extends the previously published full-history export.
It records exactly one captured ref advance: codex/hia-chrono-time-network-proxy-20261119-a11
from c32019b1e1ef566419a7b6d28a34d24270cf3d27 to 5653790ac0f64783c28926dcfca2fa7a48a40e77.

The actual new commit object was fetched with tree:0 filtering, --no-write-fetch-head,
and an explicit SHA only. Native Git verified its object identity and sole parent.
No local tracking ref, FETCH_HEAD, remote ref, original audit/export, production
manifest or reviewed source was changed.

Each .gz file is an independent deterministic gzip stream, with mtime zero, no filename,
level 9, and size at most 65,536 bytes. refresh-manifest.json records SHA256, Git blob SHA1,
uncompressed hashes and successful byte roundtrips.

refs-delta.json.gz plus the exact original captured-refs payload reconstructs the new
captured snapshot. Verify the before SHA, replace that one name, and serialize with
json.dumps(value, indent=2, sort_keys=True) plus newline. The manifest records both hashes.
graph-delta.json.gz appends its new_parent_rows to the original full parent graph.
The native job checked every actual Git parent row against the original graph plus that
single new row, found zero missing parents and rechecked every original coverage-map hash.

observed-protection-505.json.gz preserves all 504 production pins, adds the exact new
commit, and advances the recorded protected name. This is a new observation artifact;
it does not alter the 504-pin production manifest. Current protected names remain 483.
Coverage and HIA intersections were rechecked using complete local commit history,
with implicit fetch disabled. Any later remote movement is separately recorded in
refresh-result.json and was not chased.

The original full-history export is identified by its manifest SHA256 in the delta
manifest. The refresh contains no duplicated full graph or full ref payload.
"""
    export_text("README.md", readme.encode(), "delta reconstruction and scope instructions")
    manifest = {
        "schema": "hepta.single-protected-tip-refresh-export.v1",
        "base_export_manifest_sha256": BASE_EXPORT_SHA,
        "base_audit_result_sha256": BASE_RESULT_SHA,
        "tip_change": {"name": NAME, "before": OLD, "after": NEW},
        "native_process_key": KEY,
        "result_sha256": sha(result_raw),
        "captured_refs_reconstructed_byte_exactly": True,
        "complete_graph_delta_verified": True,
        "ordinary_coverage_hashes_unchanged": True,
        "production_inputs_unchanged": True,
        "all_payload_roundtrips_passed": True,
        "captured_ref_count": len(heads), "graph_nodes": len(graph),
        "protected_names": len(protected), "production_pins": 504, "observed_pins": 505,
        "gzip": {"mtime": 0, "filename": "", "compression_level": 9, "maximum_compressed_bytes": 65536},
        "compressed_artifacts": compressed,
        "exported_files": payloads,
        "exported_files_excluding_manifest_bytes": sum(item["bytes"] for item in payloads),
    }
    manifest_raw = serialized(manifest)
    manifest_meta = write(EXPORT / "refresh-manifest.json", manifest_raw)
    summary = {
        "outcome": result["outcome"], "native_result": str(REFRESH / "refresh-result.json"),
        "export_directory": str(EXPORT), "manifest": manifest_meta,
        "exported_file_count": len(payloads) + 1,
        "exported_total_bytes": sum(item["bytes"] for item in payloads) + len(manifest_raw),
        "gzip_artifact_count": len(compressed),
        "largest_gzip_bytes": max(item["bytes"] for item in compressed),
        "frozen_observation": result["observed_protection"],
        "captured_ref_count": len(heads), "complete_graph_nodes": len(graph),
        "protected_names": len(protected), "pins": len(new_pins),
        "fresh_matches_captured": heads == fresh,
        "local_refs_unchanged": True, "fetch_head_unchanged": True,
        "ordinary_coverage_unchanged": True,
        "old_export_unchanged": True, "elapsed_seconds": time.monotonic() - START,
    }
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
except BaseException as error:
    if REFRESH.is_dir():
        result["failure_type"] = type(error).__name__
        result["failure"] = str(error)
        result["outcome"] = "HOLD_REFRESH_FAILURE"
        result["elapsed_seconds"] = time.monotonic() - START
        path = REFRESH / "refresh-result.json"
        if path.exists():
            path = REFRESH / "export-failure.json"
        if not path.exists():
            write_json(path, result)
    raise
