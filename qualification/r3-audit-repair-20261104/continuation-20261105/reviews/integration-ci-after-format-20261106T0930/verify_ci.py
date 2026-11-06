#!/usr/bin/env python3
"""Verify bounded original CI observations; never dispatch any external command."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import re


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def unpack(path):
    raw = json.loads(path.read_bytes())
    if "raw" in raw:
        raw = raw["raw"]
    assert not raw.get("isError")
    return json.loads(raw["structuredContent"]["content"])


def hashes(leaves):
    root = {}
    for path, entry in leaves.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (entry["mode"].lstrip("0"), entry["sha"])
    result = {}
    def visit(node, prefix):
        raw = b""
        for name, value in sorted(node.items(), key=lambda x: (x[0] + ("/" if isinstance(x[1], dict) else "")).encode()):
            mode, sha = ("40000", visit(value, prefix + name + "/")) if isinstance(value, dict) else value
            raw += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        result[prefix.rstrip("/")] = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        return result[prefix.rstrip("/")]
    visit(root, "")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    r = p.parse_args().root.resolve()
    manifest = json.loads((r / "ORIGINALS-MANIFEST.json").read_bytes())
    assert len(manifest["files"]) == len({x["path"] for x in manifest["files"]}) == 22
    for item in manifest["files"]:
        assert identity((r / item["path"]).read_bytes()) == {k: item[k] for k in ("bytes", "git_blob", "sha256")}
    publications = {}
    expected = {
        "ac18": ("ac18b623c7a6cb953b4660979e9b620fe7176bb2", "c3e9ddc1799f470ac7c80e117ee953a7232847e0", "2d1137b1ba39fab0e6a28bac8decc114dfa0138c", "c9baaf38b95da145fb4f9d371b8d134169d313cc"),
        "aaf": ("aaf86881da0b3a7651b4a6a56be49515b9aa9f2e", "66552bda88637403f4f1d72a5be8592e07a8a308", "ac18b623c7a6cb953b4660979e9b620fe7176bb2", "8ca7a5b30bf6abfaf3ad7bb538d00f505d0847f8"),
    }
    base = "63652be658ebed8d3052eb789b951793384fd5e4"
    for key, (head_sha, tree_sha, parent_sha, merge_sha) in expected.items():
        d = r / "publication" / key
        commit = unpack(d / "commit.actual.original.json")
        merge = unpack(d / "merge.actual.original.json")
        pr = unpack(d / "pr.final.original.json")
        ref = unpack(d / "ref.after.original.json")
        assert commit["sha"] == ref["object"]["sha"] == pr["head"]["sha"] == head_sha
        assert [e["sha"] for e in commit["parents"]] == [parent_sha]
        assert commit["tree"]["sha"] == merge["tree"]["sha"] == tree_sha
        assert pr["merge_commit_sha"] == merge["sha"] == merge_sha
        assert [e["sha"] for e in merge["parents"]] == [base, head_sha]
        assert pr["number"] == 4936 and pr["base"]["sha"] == base and pr["draft"]
        publications[key] = {"head": head_sha, "tree": tree_sha, "parent": parent_sha, "merge": merge_sha, "PR_changed_paths": pr["changed_files"]}
    tree = json.loads((r / "source/ac18-full-tree.json").read_bytes())
    assert not tree["truncated"]
    leaves = {x["path"]: x for x in tree["tree"] if x["type"] != "tree"}
    merkle = hashes(leaves)
    assert len(leaves) == 10802 and merkle[""] == tree["sha"] == expected["ac18"][1]
    assert all(merkle[x["path"]] == x["sha"] for x in tree["tree"] if x["type"] == "tree")
    for path in (".github/workflows/blocking-ci.yml", ".github/workflows/rust-ci.yml"):
        assert identity((r / "source" / path).read_bytes())["git_blob"] == leaves[path]["sha"]
    cuts = []
    for word in ("sixth", "seventh", "eighth"):
        jobs = unpack(r / "original" / f"blocking-42186354218-jobs-{word}.original.json")
        assert len(jobs["jobs"]) == jobs["total_count"] == len({j["id"] for j in jobs["jobs"]})
        assert all(j["run_id"] == 42186354218 and j["head_sha"] == expected["ac18"][0] for j in jobs["jobs"])
        cuts.append({"source": word, "count": jobs["total_count"], "status": dict(sorted(Counter(j["conclusion"] if j["status"] == "completed" else j["status"] for j in jobs["jobs"]).items()))})
    latest = {j["id"]: j for j in jobs["jobs"]}
    assert cuts[-1]["status"] == {"in_progress": 4, "queued": 16, "skipped": 3, "success": 6}
    log_checks = []
    logs = {}
    for job_id, checkout in ((127802986289, expected["ac18"][0]), (127809329291, expected["ac18"][3])):
        raw = json.loads((r / "original" / f"job-{job_id}-tool-return.original.json").read_bytes())
        assert not raw.get("isError")
        text = raw["structuredContent"]["content"]
        log = (r / "original" / f"job-{job_id}.original.log").read_bytes()
        assert text.encode() == log
        lines = text.splitlines()
        outputs = [lines[i + 1].split(" ", 1)[1] for i, line in enumerate(lines[:-1]) if line.endswith("[command]/usr/bin/git log -1 --format=%H")]
        assert outputs[-1] == checkout
        assert latest[job_id]["status"] == "completed" and latest[job_id]["conclusion"] == "success"
        logs[job_id] = text
        log_checks.append({"job_id": job_id, "checkout": checkout, "complete_original": identity(log), "git_log_checkouts": outputs})
    scope_line = next(line.split(" ", 1)[1] for line in logs[127802986289].splitlines() if line.split(" ", 1)[1].startswith('{"base":'))
    scope = json.loads(scope_line)
    assert scope["base"] == base and scope["source_head"] == expected["ac18"][0]
    assert len(scope["paths"]) == len(set(scope["paths"])) == 1561
    assert scope["scope"]["full_repo"] is True and scope["scope"]["native"] is True
    assert latest[127809332118]["name"] == "Hepta scoped native checks" and latest[127809332118]["conclusion"] == "skipped"
    fmt = latest[127809329291]
    for name in ("Check formatting (run `just fmt` to fix)", "Prettier (run `pnpm run format:fix` to fix)", "Check for a clean worktree"):
        step = next(s for s in fmt["steps"] if s["name"] == name)
        assert step["conclusion"] == "success"
    assert "##[group]Run just fmt-check" in logs[127809329291]
    assert "All matched files use Prettier code style!" in logs[127809329291]
    assert "##[end-action id=__self_2.__run;outcome=success;conclusion=success;duration_ms=50]" in logs[127809329291]
    denial = latest[127809329246]
    assert denial["conclusion"] == "success" and all(next(s for s in denial["steps"] if s["name"] == name)["conclusion"] == "success" for name in ("Run cargo-deny", "Check for a clean worktree"))
    error = json.loads((r / "original/cargo-deny-127809329246-log-transport-error.original.json").read_bytes())
    assert error["isError"] and "Transport closed" in json.dumps(error)
    runs = unpack(r / "original/aaf86881-head-runs-first.original.json")
    assert runs["total_count"] == len(runs["workflow_runs"]) == len({v["id"] for v in runs["workflow_runs"]}) == 18
    assert all(v["head_sha"] == expected["aaf"][0] and v["run_attempt"] == 1 and v["event"] == "pull_request" for v in runs["workflow_runs"])
    run_status = dict(sorted(Counter(v["conclusion"] if v["status"] == "completed" else v["status"] for v in runs["workflow_runs"]).items()))
    assert run_status == {"pending": 4, "queued": 12, "skipped": 2}
    assert next(v for v in runs["workflow_runs"] if v["name"] == "blocking-ci")["id"] == 42195225682
    print(json.dumps({"schema": "hepta.integration-ci-0930.verified.v1", "originals_verified": len(manifest["files"]), "publications": publications, "ac18_full_tree_leaves": len(leaves), "ac18_blocking_cuts": cuts, "complete_log_checks": log_checks, "ac18_scope": {"base": base, "source_head": scope["source_head"], "paths": len(scope["paths"]), "scope": scope["scope"]}, "ac18_formatter": {"job_id": fmt["id"], "run_id": 42186354218, "conclusion": "success", "started": fmt["started_at"], "completed": fmt["completed_at"], "qualification": "Original just fmt-check, Prettier and clean-worktree succeeded at c9ba/ac18 only; not product tests or successor aaf qualification."}, "ac18_cargo_deny": {"job_id": denial["id"], "API_conclusion": "success", "full_log_captured": False, "tool_capture_error": "Transport closed; no retry, no native failure inferred."}, "aaf_initial_run_list": {"count": 18, "status": run_status, "blocking_run_id": 42195225682, "native_results": None}, "scope_limit": "Full-repo selects fast rust-ci.yml; scoped skipped. This packet does not certify full Cargo nextest, uncached execution, other jobs, or any blocker closure. Earlier failed/cancelled evidence remains unchanged."}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
