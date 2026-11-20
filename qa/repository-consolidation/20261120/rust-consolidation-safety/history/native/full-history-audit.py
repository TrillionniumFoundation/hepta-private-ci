import collections
import datetime
import hashlib
import json
import os
import pathlib
import re
import resource
import shutil
import subprocess
import sys
import time
import types

AUDIT_ROOT = pathlib.Path("/home/qian-qi/hepta-rust-protection-20261120-0cee")
HISTORY = AUDIT_ROOT / "history.git"
EVIDENCE = AUDIT_ROOT / "history-audit-evidence"
GIT = "/usr/bin/git"
REPOSITORY_URL = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
SOURCE = AUDIT_ROOT / "candidate/tools/branch-consolidation/hepta_branch_consolidation.py"
MANIFEST = AUDIT_ROOT / "candidate/tools/branch-consolidation/protected-branches.json"
EXPECTED_SOURCE = "d5d4047be9282be9760af63a9a0aa1e3e33e4cd85775025fbdf18b91e0aad5f7"
EXPECTED_MANIFEST = "262d189d478d0a072e5b2c6ae278b2fe084ca0cedba92df7960cc0d05546791f"
HISTORY_BYTE_LIMIT = 1024**3
SINGLE_FILE_BYTE_LIMIT = 512 * 1024**2
START = time.monotonic()
DEADLINE = START + 540
result = {
    "schema": "hepta.full-commit-ancestry-audit.v1",
    "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "repository": "TrillionniumFoundation/hepta-private-ci",
    "history_path": str(HISTORY),
    "source_sha256": EXPECTED_SOURCE,
    "manifest_sha256": EXPECTED_MANIFEST,
    "resource_limits": {"history_bytes": HISTORY_BYTE_LIMIT, "single_file_bytes": SINGLE_FILE_BYTE_LIMIT, "inner_seconds": 540},
    "git_fetch_filter": "tree:0",
    "remote_ref_mutations": False,
    "source_files_modified": False,
    "plan_or_apply_invoked": False,
    "classification_executed": False,
    "completed": False,
}
os.environ["GIT_TERMINAL_PROMPT"] = "0"
os.environ["GIT_NO_LAZY_FETCH"] = "1"
os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
sys.dont_write_bytecode = True
resource.setrlimit(resource.RLIMIT_FSIZE, (SINGLE_FILE_BYTE_LIMIT, SINGLE_FILE_BYTE_LIMIT))

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def write_bytes(name, raw):
    path = EVIDENCE / name
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "bytes": len(raw), "sha256": digest(raw)}

def write_json(name, value):
    return write_bytes(name, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())

def budget(maximum):
    remaining = DEADLINE - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("Audit wall-clock budget exhausted")
    return max(1, min(maximum, remaining))

def git(args, cwd=None, timeout=45, env=None, check=True, input_text=None):
    proc = subprocess.run(
        [GIT, "--no-replace-objects", "-C", str(cwd or HISTORY), *args],
        input=input_text, text=True, encoding="utf-8",
        errors="surrogateescape", capture_output=True,
        timeout=budget(timeout), env=env,
    )
    if check and proc.returncode:
        raise RuntimeError("Git command failed: " + args[0] + "\n" + proc.stderr[-3000:])
    return proc

def refs_from_advertisement(raw):
    refs = {}
    for line in raw.splitlines():
        sha, ref = line.split("\t", 1)
        if not re.fullmatch("[0-9a-f]{40}", sha) or not ref.startswith("refs/heads/"):
            raise RuntimeError("Unexpected reference advertisement")
        name = ref.removeprefix("refs/heads/")
        if name in refs:
            raise RuntimeError("Duplicate advertised name")
        refs[name] = sha
    if "main" not in refs:
        raise RuntimeError("Main absent from advertisement")
    return refs

def delta(old, new):
    return {
        "added": {n: s for n, s in new.items() if n not in old},
        "removed": {n: s for n, s in old.items() if n not in new},
        "changed": {n: {"before": old[n], "after": s} for n, s in new.items() if n in old and old[n] != s},
    }

def history_size():
    total = 0
    for parent, directories, files in os.walk(HISTORY):
        for name in directories + files:
            path = pathlib.Path(parent) / name
            if path.is_symlink():
                raise RuntimeError("Unexpected symlink in owned bare repository")
            if path.is_file():
                total += path.stat().st_size
    return total

try:
    if AUDIT_ROOT.resolve() != AUDIT_ROOT or not EVIDENCE.is_dir() or EVIDENCE.is_symlink():
        raise RuntimeError("Isolated audit paths invalid")
    if os.path.lexists(HISTORY):
        raise RuntimeError("Refuse an existing history repository")
    if digest(pathlib.Path(__file__).read_bytes()) != os.environ["HEPTA_HISTORY_AUDIT_SCRIPT_SHA256"]:
        raise RuntimeError("Audit script changed before execution")
    source_bytes, manifest_bytes = SOURCE.read_bytes(), MANIFEST.read_bytes()
    if digest(source_bytes) != EXPECTED_SOURCE or digest(manifest_bytes) != EXPECTED_MANIFEST:
        raise RuntimeError("Reviewed inputs changed")
    manifest = json.loads(manifest_bytes)
    preflight = json.loads((EVIDENCE / "preflight.json").read_text())
    help_text = (EVIDENCE / "git-fetch-help.txt").read_text()
    if not re.search(r"--(?:\[no-\])?filter\b", help_text):
        raise RuntimeError("Installed Git help does not advertise filtering")
    if shutil.disk_usage(AUDIT_ROOT).free < 4 * 1024**3:
        raise RuntimeError("Disk headroom below preflight floor")
    result["preflight_job"] = "1a1f6b01690-ffbe-152d"
    result["git_version"] = preflight["git_version"]
    result["script_sha256"] = os.environ["HEPTA_HISTORY_AUDIT_SCRIPT_SHA256"]
    HISTORY.mkdir(mode=0o700)
    initialized = git(["init", "--bare", "--initial-branch=main", str(HISTORY)], cwd=AUDIT_ROOT)
    write_bytes("git-init.stdout.txt", initialized.stdout.encode())
    write_bytes("git-init.stderr.txt", initialized.stderr.encode())
    git(["remote", "add", "origin", REPOSITORY_URL])
    git(["config", "--local", "gc.auto", "0"])
    git(["config", "--local", "maintenance.auto", "false"])
    git(["config", "--local", "protocol.version", "2"])

    packet_path = EVIDENCE / "server-capabilities.packet.txt"
    env = {**os.environ, "GIT_TRACE_PACKET": str(packet_path)}
    advertised = git(["-c", "protocol.version=2", "ls-remote", "--heads", "origin"], env=env)
    write_bytes("refs-before-fetch.stdout.txt", advertised.stdout.encode())
    write_bytes("refs-before-fetch.stderr.txt", advertised.stderr.encode())
    packet_text = packet_path.read_text()
    if not re.search(r"\bfetch=[^\r\n]*\bfilter\b", packet_text):
        raise RuntimeError("Server did not advertise protocol-v2 fetch filtering; no fetch attempted")
    before = refs_from_advertisement(advertised.stdout)
    result["server_filter_capability_verified"] = True
    result["server_filter_capability_lines"] = [line for line in packet_text.splitlines() if "fetch=" in line]
    result["before_fetch_ref_count"] = len(before)
    write_json("refs-before-fetch.json", before)
    print(json.dumps({"phase": "server_filter_verified", "refs": len(before)}), flush=True)

    fetch_args = ["fetch", "--filter=tree:0", "--no-tags", "--no-auto-maintenance", "--no-write-commit-graph", "origin", "+refs/heads/*:refs/remotes/origin/*"]
    write_json("fetch-request.json", {"git": GIT, "cwd": str(HISTORY), "args": fetch_args, "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "no_unfiltered_fallback": True})
    fetch_deadline = time.monotonic() + budget(440)
    with (EVIDENCE / "fetch.stdout.txt").open("x") as stdout, (EVIDENCE / "fetch.stderr.txt").open("x") as stderr:
        proc = subprocess.Popen([GIT, "--no-replace-objects", "-C", str(HISTORY), *fetch_args], stdout=stdout, stderr=stderr, env=os.environ.copy())
        failure = None
        try:
            while proc.poll() is None:
                if time.monotonic() > fetch_deadline:
                    failure = "Commit-only fetch exceeded time budget"
                    break
                if history_size() > HISTORY_BYTE_LIMIT:
                    failure = "Commit-only fetch exceeded owned repository byte limit"
                    break
                time.sleep(1)
            if failure:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                raise RuntimeError(failure)
            fetch_exit = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
    result["fetch_exit_code"] = fetch_exit
    result["history_bytes_after_fetch"] = history_size()
    if fetch_exit:
        raise RuntimeError("Filtered fetch failed; no fallback attempted")
    fetch_error = (EVIDENCE / "fetch.stderr.txt").read_text()
    if "filtering not recognized" in fetch_error.lower() or "does not support filter" in fetch_error.lower():
        raise RuntimeError("Filter was ignored; refuse classification")
    if git(["rev-parse", "--is-shallow-repository"]).stdout.strip() != "false":
        raise RuntimeError("Filtered fetch left shallow history")
    local = {}
    local_ref_output = git(["for-each-ref", "--format=%(refname)\t%(objectname)\t%(objecttype)\t%(symref)", "refs/remotes/origin/"]).stdout
    write_bytes("local-fetched-refs.stdout.txt", local_ref_output.encode())
    for line in local_ref_output.splitlines():
        ref, sha, kind, symref = line.split("\t")
        if not ref.startswith("refs/remotes/origin/") or kind != "commit" or symref:
            raise RuntimeError("Unexpected fetched ref identity")
        name = ref.removeprefix("refs/remotes/origin/")
        if name in local:
            raise RuntimeError("Duplicate fetched name")
        local[name] = sha
    heads = local
    if "main" not in heads:
        raise RuntimeError("Fetched main absent")
    result["captured_ref_count"] = len(heads)
    result["before_fetch_to_captured_delta"] = delta(before, heads)
    result["captured_refs_artifact"] = write_json("captured-refs.json", heads)
    types_output = git(["cat-file", "--batch-all-objects", "--batch-check=%(objecttype)"], timeout=60).stdout
    counts = dict(collections.Counter(types_output.splitlines()))
    result["local_object_types"] = counts
    if set(counts) != {"commit"}:
        raise RuntimeError("Filtered object inventory is not commit-only")
    write_json("local-object-types.json", counts)
    print(json.dumps({"phase": "filtered_history_fetched", "refs": len(heads), "object_types": counts, "history_bytes": result["history_bytes_after_fetch"]}), flush=True)

    module = types.ModuleType("hepta_branch_consolidation_verified")
    module.__file__ = str(SOURCE)
    exec(compile(source_bytes, str(SOURCE), "exec"), module.__dict__)
    classification_trace = EVIDENCE / "classification.packet.txt"
    os.environ["GIT_TRACE_PACKET"] = str(classification_trace)
    result["classification_no_lazy_fetch"] = os.environ["GIT_NO_LAZY_FETCH"]
    protected = module.protected_branches(HISTORY, heads, manifest)
    observed_manifest = module.freeze_protection(heads, manifest, protected)
    pins = set(manifest["historicalProtectedCommits"]) | set(manifest["hiaRootCommits"]) | set(manifest["protectedHeads"].values()) | set(manifest["protectedBaseHeads"].values())
    protected_tips = {heads[name] for name in protected}
    graph_text = git(["rev-list", "--parents", "--topo-order", "--reverse", "--stdin"], timeout=90, input_text="\n".join(sorted(set(heads.values()) | pins)) + "\n").stdout
    graph = {}
    ordered = []
    for line in graph_text.splitlines():
        sha, *parents = line.split()
        if sha in graph or any(parent not in graph for parent in parents):
            raise RuntimeError("Independent graph closure/order validation failed")
        graph[sha] = parents
        ordered.append(sha)
    if (set(heads.values()) | pins) - graph.keys():
        raise RuntimeError("Independent graph omitted captured head or pin")
    result["commit_parent_graph_artifact"] = write_bytes("complete-parent-graph.tsv", graph_text.encode())
    result["parent_graph_nodes"] = len(graph)
    result["missing_parent_count"] = 0
    result["protected_name_count"] = len(protected)
    result["protected_pin_count_input"] = len(pins)
    result["observed_pin_count"] = len(observed_manifest["historicalProtectedCommits"])
    result["protected_classification_artifact"] = write_json("protected-classification.json", protected)
    result["observed_protection_artifact"] = write_json("observed-protection.json", observed_manifest)
    original_names = set(manifest["protectedHeads"]) | set(manifest["protectedBaseHeads"])
    result["new_protected_names"] = sorted(set(protected) - original_names)
    result["missing_protected_names"] = sorted(original_names - heads.keys())
    result["captured_protected_tip_changes"] = {name: {"before": (manifest["protectedHeads"] | manifest["protectedBaseHeads"])[name], "after": heads[name]} for name in original_names & heads.keys() if (manifest["protectedHeads"] | manifest["protectedBaseHeads"])[name] != heads[name]}

    ordinary = {name: sha for name, sha in heads.items() if name != "main" and name not in protected}
    result["ordinary_name_count"] = len(ordinary)
    result["ordinary_distinct_head_count"] = len(set(ordinary.values()))
    targets = {
        "main": heads["main"],
        "integration_0cee": "0cee57ca617e0324e2df8e9447a2c075a6c76952",
        "repair_4a5de714": "4a5de714ce95889fca83abd3da33cbd74aaac748",
        "live_integration": heads["integration/hepta-single-main-20261113-ab5b"],
    }
    coverage = {}
    for label, target in targets.items():
        if target not in graph:
            raise RuntimeError("Requested target absent from captured complete history: " + label)
        ancestors, stack = set(), [target]
        while stack:
            node = stack.pop()
            if node in ancestors:
                continue
            ancestors.add(node)
            stack.extend(graph[node])
        included = {name: sha for name, sha in ordinary.items() if sha in ancestors}
        pending = {name: sha for name, sha in ordinary.items() if sha not in ancestors}
        pending_tips = set(pending.values())
        strict_ancestors_of_pending = set()
        for node in reversed(ordered):
            if node in pending_tips or node in strict_ancestors_of_pending:
                strict_ancestors_of_pending.update(graph[node])
        maximal = pending_tips - strict_ancestors_of_pending
        frontier_names = {name: sha for name, sha in pending.items() if sha in maximal}
        coverage[label] = {
            "sha": target,
            "ancestor_commits": len(ancestors),
            "protected_pin_intersection": sorted(pins & ancestors),
            "current_protected_tip_intersection": sorted(protected_tips & ancestors),
            "ordinary_names_covered": len(included),
            "ordinary_names_pending": len(pending),
            "pending_distinct_tips": len(pending_tips),
            "pending_maximal_tips": len(maximal),
            "pending_frontier_names": len(frontier_names),
            "covered_artifact": write_json(label + "-covered-ordinary.json", included),
            "pending_artifact": write_json(label + "-pending-ordinary.json", pending),
            "frontier_artifact": write_json(label + "-frontier.json", frontier_names),
        }
    result["coverage"] = coverage
    if classification_trace.exists() and classification_trace.stat().st_size:
        raise RuntimeError("Unexpected protocol traffic during no-lazy-fetch classification")
    result["classification_packet_bytes"] = classification_trace.stat().st_size if classification_trace.exists() else 0
    result["classification_executed"] = True
    os.environ.pop("GIT_TRACE_PACKET", None)
    fresh_raw = git(["ls-remote", "--heads", "origin"], timeout=45).stdout
    fresh = refs_from_advertisement(fresh_raw)
    result["fresh_refs_artifact"] = write_json("fresh-remote-refs.json", fresh)
    result["fresh_ref_count"] = len(fresh)
    result["captured_to_fresh_delta"] = delta(heads, fresh)
    result["fresh_matches_captured"] = heads == fresh
    result["inputs_unchanged_after_classification"] = digest(SOURCE.read_bytes()) == EXPECTED_SOURCE and digest(MANIFEST.read_bytes()) == EXPECTED_MANIFEST
    result["history_bytes_final"] = history_size()
    result["disk_free_bytes_final"] = shutil.disk_usage(AUDIT_ROOT).free
    result["completed"] = True
    result["no_protected_intersection_all_targets"] = all(not entry["protected_pin_intersection"] and not entry["current_protected_tip_intersection"] for entry in coverage.values())
    result["outcome"] = "PASS_CAPTURED_FULL_DAG" if result["fresh_matches_captured"] and result["no_protected_intersection_all_targets"] and result["inputs_unchanged_after_classification"] else "HOLD_REVIEW_CAPTURE_OR_PROTECTION_DELTA"
except BaseException as error:
    result["error_type"] = type(error).__name__
    result["error"] = str(error)
    result["outcome"] = "HOLD_NO_FULL_DAG_QUALIFICATION"
    raise
finally:
    result["elapsed_seconds"] = time.monotonic() - START
    result["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_json("full-history-result.json", result)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
