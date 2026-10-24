"""Publish existing fixed-graph evidence only; never rerun inference or old audits.

prepare makes new archives and a new repository directory. publish makes one
commit/push attempt. confirm only reads the remote ref after an uncertain push.
Every stage uses an exclusive outside-repository journal. Failures are retained;
there is no reset, overwrite, force push, automatic retry or experiment execution.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import resource
import stat
import subprocess
import tarfile
import time
from urllib.parse import urlsplit


MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 4096
MAX_ARCHIVE = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def safe_relative(value):
    name = PurePosixPath(value)
    require(value and not name.is_absolute() and ".." not in name.parts and str(name) == value,
            "normalized relative artifact path required")
    return name


def no_symlink(path):
    for part in (path, *path.parents):
        require(not part.is_symlink(), "symlink path rejected")


def regular(path, maximum=MAX_FILE):
    no_symlink(path)
    metadata = path.stat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= maximum, "bounded regular file required: " + str(path))
    data = path.read_bytes()
    after = path.stat()
    stable = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    require(len(data) == metadata.st_size and stable(after) == stable(metadata), "file changed during read")
    return data


def exclusive(path, data):
    no_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def snapshot(root, maximum=MAX_FILE):
    no_symlink(root)
    require(root.is_dir(), "artifact root must exist")
    rows = []
    total = 0
    for folder, directories, filenames in os.walk(root, followlinks=False):
        for name in sorted(directories + filenames):
            path = Path(folder) / name
            no_symlink(path)
            require(path.is_dir() or path.is_file(), "special artifact rejected")
        for name in sorted(filenames):
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            safe_relative(relative)
            data = regular(path, maximum)
            total += len(data)
            rows.append({"path": relative, "bytes": len(data), "sha256": sha(data)})
            require(total <= MAX_TOTAL and len(rows) <= MAX_FILES, "task-owned archive bound exceeded")
    return sorted(rows, key=lambda row: row["path"])


def verify_snapshot(root, rows, maximum=MAX_FILE):
    require(snapshot(root, maximum) == rows, "artifact census or bytes changed; preserve this failed attempt")


def make_archive(root, rows, output):
    no_symlink(output)
    require(not output.resolve().is_relative_to(root.resolve()), "archive cannot be inside its input tree")
    with output.open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(mode="w", fileobj=compressed, format=tarfile.PAX_FORMAT) as archive:
                for row in rows:
                    data = regular(root / row["path"])
                    require(len(data) == row["bytes"] and sha(data) == row["sha256"], "archive input changed")
                    item = tarfile.TarInfo(row["path"])
                    item.size, item.mode, item.mtime = len(data), 0o600, 0
                    archive.addfile(item, io.BytesIO(data))
        stream.flush()
        os.fsync(stream.fileno())
    data = regular(output, MAX_ARCHIVE)
    verify_archive(output, rows)
    return {"bytes": len(data), "sha256": sha(data)}


def verify_archive(path, rows):
    expected = {row["path"]: row for row in rows}
    require(len(expected) == len(rows), "duplicate manifest artifact")
    found = set()
    with tarfile.open(path) as archive:
        for member in archive:
            safe_relative(member.name)
            require(member.isfile() and member.name not in found and member.name in expected,
                    "archive has missing, duplicate or unsafe member")
            row = expected[member.name]
            require(member.size == row["bytes"] <= MAX_FILE, "archive member byte bound differs")
            data = archive.extractfile(member).read()
            require(len(data) == row["bytes"] and sha(data) == row["sha256"], "archive member hash differs")
            found.add(member.name)
    require(found == set(expected), "archive census incomplete")


def bundle_file(bundle, relative):
    safe_relative(relative)
    with tarfile.open(bundle) as archive:
        member = archive.getmember(relative)
        require(member.isfile() and member.size <= MAX_FILE, "bounded bundle file required")
        return archive.extractfile(member).read()


def command(state, name, argv, cwd, timeout=120, intent_binding=None):
    require(name.isidentifier(), "fixed command journal key required")
    intent = {"argv": argv, "cwd": str(cwd), "started_unix_ns": time.time_ns(), "timeout_seconds": timeout}
    if intent_binding is not None:
        require(not (set(intent) & set(intent_binding)), "command binding cannot replace intent fields")
        intent.update(intent_binding)
    exclusive(state / (name + "-intent.json"), canonical(intent))
    started = time.perf_counter_ns()
    try:
        result = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        stdout, stderr = result.stdout, result.stderr
        receipt = {"returncode": result.returncode, "timed_out": False}
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        receipt = {"returncode": None, "timed_out": True, "effect_outcome": "unknown; no automatic retry"}
    for stream, data in (("stdout", stdout), ("stderr", stderr)):
        exclusive(state / (name + "-" + stream + ".bin"), data[:MAX_FILE])
        receipt[stream] = {"seen_bytes": len(data), "sha256": sha(data), "stored_bytes": min(len(data), MAX_FILE), "truncated": len(data) > MAX_FILE}
    receipt.update(finished_unix_ns=time.time_ns(), observed_wall_ns=time.perf_counter_ns() - started)
    exclusive(state / (name + "-result.json"), canonical(receipt))
    require(len(stdout) <= MAX_FILE and len(stderr) <= MAX_FILE, "command output exceeded bound; failure evidence retained")
    return receipt, stdout


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], timeout=30).decode().strip()


def check_git(root, spec, expected_head, clean):
    no_symlink(root)
    require(root.resolve() == Path(spec["worktree"]), "exact worktree binding required")
    require(git(root, "rev-parse", "--show-toplevel") == str(root), "exact git worktree root required")
    require(git(root, "branch", "--show-current") == spec["branch"], "branch changed")
    require(git(root, "rev-parse", "HEAD") == expected_head, "HEAD changed")
    if clean:
        require(not git(root, "status", "--porcelain=v1", "--untracked-files=all"), "clean worktree required")
    for relative, expected in spec["protected_source_pins"].items():
        safe_relative(relative)
        require(sha(regular(root / relative)) == expected, "frozen original source changed: " + relative)


def check_origin(root):
    """Check target identity without printing or archiving any URL credentials."""
    value = git(root, "remote", "get-url", "--push", "origin")
    if value.startswith("git@github.com:"):
        path = value[len("git@github.com:"):]
    else:
        parsed = urlsplit(value)
        require(parsed.scheme in ("https", "ssh") and parsed.hostname == "github.com", "expected GitHub origin required")
        path = parsed.path.lstrip("/")
    require(path.removesuffix(".git") == "TrillionniumFoundation/hepta-private-ci", "unexpected origin repository")


def validate_evidence(root, rows, spec):
    files = {row["path"]: row for row in rows}
    for relative, expected in spec["artifact_pins"].items():
        require(files.get(relative, {}).get("sha256") == expected, "required artifact absent or changed: " + relative)
    for expected in spec["required_content_hashes"]:
        require(any(row["sha256"] == expected for row in rows), "frozen exported input content missing")
    for relative in spec["must_remain_absent"]:
        require(relative not in files and not (root / relative).exists(), "original absent evidence was replaced: " + relative)
    raw_dir = spec["raw_directory"] + "/"
    require({name for name in files if name.startswith(raw_dir)} == {name for name in spec["artifact_pins"] if name.startswith(raw_dir)},
            "original raw-prefix file census changed")
    report = json.loads(regular(root / spec["report_path"]))
    audit = json.loads(regular(root / spec["partial_audit_path"]))
    dispatch = json.loads(regular(root / "requests-v1/dispatch.json"))
    require(audit["primary_independent_tensor_and_scalar_pass"] is True
            and audit["original_recovery_integrity"]["passed"] is True and audit["issues"] == []
            and audit["complete_original_cost_audit_pass"] is False
            and audit["retained_prefix"]["full_ledger_sha256_verified"] is False,
            "actual partial-audit scope or qualification differs")
    require(audit["retained_prefix"]["retained_complete_records"] == 45
            and audit["retained_prefix"]["declared_snapshot_records"] == 383
            and audit["retained_prefix"]["present_chunks"] == 4
            and audit["retained_prefix"]["declared_chunks"] == 34, "original loss counts differ")
    require(len(report["rows"]) == len(audit["primary_rows"]) == len(dispatch["graphs"]) == 18,
            "complete eighteen-graph census required")
    graph_ids = {f"b{block}-{arm}" for block in range(6) for arm in "ABC"}
    require({g["graph_id"] for g in dispatch["graphs"]} == graph_ids, "unexpected graph identity")
    require({name.split('/')[1] for name in files if name.startswith("graphs/") and name.endswith("/owner.json")} == graph_ids,
            "exact persisted eighteen-owner census required")
    worker_count = 0
    for graph, reported in zip(dispatch["graphs"], report["rows"], strict=True):
        name = graph["graph_id"]
        require(reported["graph_id"] == name and reported["status"] == "completed", "original failed/changed graph cannot be promoted")
        folder = root / "graphs" / name
        owner_bytes = regular(folder / "owner.json")
        receipt_bytes = regular(folder / "reduction/receipt.json")
        collection_bytes = regular(folder / "collection.json")
        owner, receipt, collection = map(json.loads, (owner_bytes, receipt_bytes, collection_bytes))
        require(sha(owner_bytes) == reported["owner_sha256"] and sha(receipt_bytes) == reported["reduction_sha256"]
                and owner["reduction"]["receipt_sha256"] == sha(receipt_bytes)
                and receipt["collection_sha256"] == sha(collection_bytes)
                and receipt["predictions_sha256"] == sha(regular(folder / "reduction/predictions.npz")),
                "original graph artifact hash chain differs")
        require(owner["status"] == receipt["status"] == "completed", "original graph completion changed")
        require(len(graph["requests"]) == len(collection["workers"]), "worker census differs")
        for request, worker in zip(graph["requests"], collection["workers"], strict=True):
            safe_relative(request["request_file"])
            require(sha(regular(root / "requests-v1" / request["request_file"])) == request["request_sha256"], "original request changed")
            data = base64.b64decode(worker["stdout_base64"], validate=True)
            require(sha(data) == worker["stdout_sha256"] and len(data) == worker["stdout_bytes"], "old worker stdout changed")
            worker_count += 1
    require(worker_count == audit["retained_worker_output_count"] == 30, "complete thirty-worker census required")
    return {"primary_graphs": 18, "retained_worker_outputs": 30, "original_recovery": ["failed", "absent", "absent"],
            "original_raw_chunks": [4, 34], "original_complete_raw_records": [45, 383],
            "full_original_ledger_sha256_verified": False, "complete_original_cost_audit": False,
            "unknown_costs_are_not_zero": True, "original_experiments_rerun": False}


def load_inputs(args):
    spec_bytes = regular(args.spec)
    require(sha(spec_bytes) == args.spec_sha256, "publication spec bytes differ")
    spec = json.loads(spec_bytes)
    require(spec["schema"] == "hepta.fixed-cell-graph.publication-spec.v1", "publication schema differs")
    require(sha(regular(args.bundle, MAX_ARCHIVE)) == spec["local_bundle"]["sha256"], "local custody bundle differs")
    verify_archive(args.bundle, spec["local_bundle"]["files"])
    recovery = json.loads(bundle_file(args.bundle, spec["recovery_audit_bundle_path"]))
    require(recovery["all_three_original_job_byte_reuses_qualified"] is True and recovery["issues"] == []
            and recovery["native_call_count"] == 25 and recovery["file_checkpoint_count"] == 59
            and recovery["original_full_ledger_recovered"] is False
            and recovery["original_whole_run_cost_complete"] is False
            and [(row["request_id"], row["status"]) for row in recovery["cases"]]
            == [(f"b0-{arm}-s0", "completed") for arm in "ABC"], "separate full recovery audit must remain qualified and scoped")
    custody = json.loads(bundle_file(args.bundle, spec["custody_audit_bundle_path"]))
    require(custody["all_three_archive_bytes_manifests_and_actual_write_acks_match"] is True
            and custody["all_59_final_checkpoint_files_present_and_exact"] is True
            and custody["all_25_native_intent_result_pairs_present"] is True,
            "actual three-archive custody closure required")
    worktree, evidence = Path(spec["worktree"]), Path(spec["evidence_root"])
    require(args.state.is_absolute(), "absolute outside-repository state directory required")
    for path in (args.state, args.spec, args.bundle):
        no_symlink(path)
    require(not args.state.resolve().is_relative_to(worktree) and not args.state.resolve().is_relative_to(evidence), "state must be outside repository/evidence")
    destination = worktree / str(safe_relative(spec["destination"]))
    require(spec["destination"].startswith("qa/stem-bakeoff/evidence/"), "new evidence destination required")
    return spec, spec_bytes, worktree, evidence, destination


def prepare(args):
    spec, spec_bytes, root, evidence, destination = load_inputs(args)
    require(not args.state.exists() and not destination.exists(), "new state and repository destination required")
    args.state.mkdir(parents=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    exclusive(args.state / "prepare-intent.json", canonical({"spec_sha256": args.spec_sha256, "started_unix_ns": time.time_ns(), "action": "archive retained evidence only"}))
    check_git(root, spec, spec["base_head"], clean=True)
    rows = snapshot(evidence)
    census = validate_evidence(evidence, rows, spec)
    staged = args.state / "repository-files"
    staged.mkdir()
    archive = make_archive(evidence, rows, staged / "remote-evidence.tar.gz")
    verify_snapshot(evidence, rows)
    exclusive(staged / "REMOTE_MANIFEST.json", canonical({"files": rows, "census": census, "source_root": str(evidence)}))
    bundle_bytes = regular(args.bundle, MAX_ARCHIVE)
    require(sha(bundle_bytes) == spec["local_bundle"]["sha256"], "custody bundle changed during preparation")
    exclusive(staged / "local-source-and-receipts.tar.gz", bundle_bytes)
    exclusive(staged / "LOCAL_MANIFEST.json", canonical(spec["local_bundle"]))
    for target, source in spec["readable_local_files"].items():
        safe_relative(target)
        exclusive(staged / target, bundle_file(staged / "local-source-and-receipts.tar.gz", source))
    exclusive(staged / "original-report.json", regular(evidence / spec["report_path"]))
    exclusive(staged / "partial-audit.json", regular(evidence / spec["partial_audit_path"]))
    exclusive(staged / "publication-spec.json", spec_bytes)
    exclusive(staged / "PUBLICATION.json", canonical({"schema": "hepta.fixed-cell-graph.precommit-publication.v1",
        "base_head": spec["base_head"], "branch": spec["branch"], "remote_archive": archive,
        "local_bundle_sha256": spec["local_bundle"]["sha256"], "census": census,
        "publication_body_wall_ns_before_receipt_and_git_install": time.perf_counter_ns() - started,
        "publication_body_cpu_ns_before_receipt_and_git_install": time.process_time_ns() - cpu,
        "publication_process_peak_rss_bytes_before_receipt_and_git_install": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cost_scope": "Observed publication body only. Excludes later receipt/install/commit/push. Original missing costs stay unknown; nested phases are not added."}))
    staged_rows = snapshot(staged, MAX_ARCHIVE)
    require(all(row["bytes"] <= MAX_ARCHIVE for row in staged_rows), "git artifact bound exceeded")
    exclusive(staged / "FILE_MANIFEST.json", canonical({"schema": "hepta.fixed-cell-graph.repository-file-manifest.v1", "files": staged_rows}))
    installed_rows = snapshot(staged, MAX_ARCHIVE)
    check_git(root, spec, spec["base_head"], clean=True)
    verify_snapshot(evidence, rows)
    no_symlink(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for row in installed_rows:
        exclusive(destination / row["path"], regular(staged / row["path"], MAX_ARCHIVE))
    verify_snapshot(destination, installed_rows, MAX_ARCHIVE)
    exclusive(args.state / "PREPARED.json", canonical({"spec_sha256": args.spec_sha256, "base_head": spec["base_head"],
        "destination": str(destination), "files": installed_rows, "census": census, "archive": archive,
        "prepare_outer_wall_ns_before_ack": time.perf_counter_ns() - started, "committed": False, "pushed": False}))
    print(json.dumps({"status": "prepared", "files": len(installed_rows), "archive": archive, "state": str(args.state)}))


def expected_paths(spec, prepared):
    return {spec["destination"] + "/" + row["path"] for row in prepared["files"]}


def verify_artifact_tree(root, spec, prepared, tree):
    changed = git(root, "diff", "--name-status", spec["base_head"], tree).splitlines()
    require(all(line.startswith("A\t") for line in changed), "publication may only add files")
    require({line[2:] for line in changed} == expected_paths(spec, prepared), "commit artifact census differs")
    for row in prepared["files"]:
        relative = spec["destination"] + "/" + row["path"]
        data = subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", tree + ":" + relative], timeout=30)
        require(len(data) == row["bytes"] and sha(data) == row["sha256"], "immutable tree blob differs from prepared bytes")


def staged_tree(root, spec, prepared):
    index = subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage", "-z", "--", spec["destination"]], timeout=30)
    entries = {}
    for item in index.split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        mode, object_id, stage = metadata.decode().split()
        require(mode == "100644" and stage == "0", "ordinary prepared file in index stage zero required")
        require(name.decode() not in entries, "duplicate index path")
        entries[name.decode()] = object_id
    require(set(entries) == expected_paths(spec, prepared), "complete staged blob census required")
    for row in prepared["files"]:
        relative = spec["destination"] + "/" + row["path"]
        data = subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", entries[relative]], timeout=30)
        require(len(data) == row["bytes"] and sha(data) == row["sha256"], "staged blob differs from prepared bytes")
    tree = git(root, "write-tree")
    # The index could change between blob checks and write-tree. Verify the
    # resulting immutable tree too; later hooks must produce this exact tree.
    verify_artifact_tree(root, spec, prepared, tree)
    return tree


def verify_commit(root, spec, prepared, head, expected_tree):
    parents = git(root, "rev-list", "--parents", "-n", "1", head).split()
    require(parents == [head, spec["base_head"]], "publication requires exactly the original single parent")
    require(git(root, "rev-parse", head + "^{tree}") == expected_tree, "commit tree differs from exclusive pre-commit intent")
    verify_artifact_tree(root, spec, prepared, expected_tree)
    check_git(root, spec, head, clean=True)
    verify_snapshot(Path(prepared["destination"]), prepared["files"], MAX_ARCHIVE)


def remote_ref(state, root, spec, name):
    ref = "refs/heads/" + spec["branch"]
    receipt, output = command(state, name, ["git", "ls-remote", "--exit-code", "origin", ref], root, 60)
    require(receipt["returncode"] == 0 and not receipt["timed_out"], "remote ref observation unavailable; no publication claim")
    lines = output.decode().splitlines()
    require(len(lines) == 1 and lines[0].split()[1] == ref, "exact remote branch acknowledgement required")
    return lines[0].split()[0]


def publish(args):
    spec, _, root, _, destination = load_inputs(args)
    prepared = json.loads(regular(args.state / "PREPARED.json"))
    require(prepared["spec_sha256"] == args.spec_sha256 and prepared["destination"] == str(destination), "prepared binding differs")
    exclusive(args.state / "publish-intent.json", canonical({"started_unix_ns": time.time_ns(), "base_head": spec["base_head"], "one_commit_one_push_attempt": True}))
    check_git(root, spec, spec["base_head"], clean=False)
    check_origin(root)
    verify_snapshot(destination, prepared["files"], MAX_ARCHIVE)
    require(not git(root, "diff", "--name-only") and not git(root, "diff", "--cached", "--name-only"), "unrelated tracked/index changes rejected")
    untracked = set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    require(untracked <= expected_paths(spec, prepared), "unrelated untracked work rejected")
    require(remote_ref(args.state, root, spec, "remote_before") == spec["base_head"], "remote branch moved; no implicit merge or force push")
    receipt, _ = command(args.state, "stage", ["git", "add", "--force", "--", spec["destination"]], root)
    require(receipt["returncode"] == 0, "staging did not complete")
    require(set(git(root, "diff", "--cached", "--name-only").splitlines()) == expected_paths(spec, prepared), "staged artifact census differs")
    receipt, _ = command(args.state, "diff_check", ["git", "diff", "--cached", "--check"], root)
    require(receipt["returncode"] == 0, "publication diff check failed")
    expected_tree = staged_tree(root, spec, prepared)
    prepared_sha = sha(regular(args.state / "PREPARED.json"))
    receipt, _ = command(args.state, "commit", ["git", "commit", "-m", "Publish fixed-graph placement evidence and separate recovery validation"], root,
                         intent_binding={"expected_parent": spec["base_head"], "expected_tree": expected_tree,
                                         "prepared_sha256": prepared_sha, "spec_sha256": args.spec_sha256})
    require(receipt["returncode"] == 0 and not receipt["timed_out"], "commit outcome not confirmed; preserve worktree and inspect, no auto-retry")
    head = git(root, "rev-parse", "HEAD")
    verify_commit(root, spec, prepared, head, expected_tree)
    exclusive(args.state / "COMMITTED.json", canonical({"head": head, "parent": spec["base_head"], "expected_tree": expected_tree,
        "prepared_sha256": prepared_sha, "commit_intent_sha256": sha(regular(args.state / "commit-intent.json")), "spec_sha256": args.spec_sha256}))
    push, _ = command(args.state, "push", ["git", "push", "origin", head + ":refs/heads/" + spec["branch"]], root, 120)
    observed = remote_ref(args.state, root, spec, "remote_after")
    result = {"head": head, "observed_remote_head": observed, "push_returncode": push["returncode"],
              "push_timed_out": push["timed_out"], "remote_commit_confirmed": observed == head,
              "final_ack_outside_its_own_commit": True, "complete_original_cost_audit": False}
    exclusive(args.state / "PUSH_OBSERVATION.json", canonical(result))
    require(observed == head, "push not confirmed at exact remote branch; retain failure, no implicit retry")
    print(json.dumps(result))


def confirm(args):
    spec, _, root, _, _ = load_inputs(args)
    prepared = json.loads(regular(args.state / "PREPARED.json"))
    committed = json.loads(regular(args.state / "COMMITTED.json"))
    require(prepared["spec_sha256"] == committed["spec_sha256"] == args.spec_sha256, "existing publication binding differs")
    intent_bytes = regular(args.state / "commit-intent.json")
    intent = json.loads(intent_bytes)
    require(sha(intent_bytes) == committed["commit_intent_sha256"]
            and sha(regular(args.state / "PREPARED.json")) == committed["prepared_sha256"] == intent["prepared_sha256"]
            and intent["expected_tree"] == committed["expected_tree"]
            and intent["expected_parent"] == committed["parent"] == spec["base_head"], "original commit-intent/tree binding differs")
    check_origin(root)
    verify_commit(root, spec, prepared, committed["head"], committed["expected_tree"])
    name = "confirm_" + str(time.time_ns())
    observed = remote_ref(args.state, root, spec, name)
    result = {"head": committed["head"], "observed_remote_head": observed, "remote_commit_confirmed": observed == committed["head"], "no_commit_or_push_attempted": True}
    exclusive(args.state / (name + "-ack.json"), canonical(result))
    require(result["remote_commit_confirmed"], "remote does not acknowledge the publication commit")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "publish", "confirm"))
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        {"prepare": prepare, "publish": publish, "confirm": confirm}[args.action](args)
    except BaseException as error:
        if args.state.is_dir() and not args.state.is_symlink():
            try:
                exclusive(args.state / ("failure-" + str(time.time_ns()) + ".json"), canonical({"action": args.action, "error_type": type(error).__name__, "message": str(error), "no_cleanup_or_retry": True}))
            except Exception:
                pass
        raise
