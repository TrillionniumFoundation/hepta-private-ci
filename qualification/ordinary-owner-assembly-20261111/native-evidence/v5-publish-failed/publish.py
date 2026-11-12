import datetime
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import traceback
from pathlib import Path, PurePosixPath

if not __debug__:
    raise RuntimeError("Evidence publication requires enabled Python assertions")
C = json.loads(sys.argv[1])
ROOT = Path(C["root"])
WORK = Path(C["work"])
SOURCE = Path(C["source"])
REPO = WORK / "repo"
RECORDS = WORK / "records"
REF = "refs/heads/codex/ordinary-native-evidence-v5-20261112-af52"
REMOTE = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
BASE = "715a5726f5031e50ad963812d2a1270e8d0cf769"
TREE = "1122b8a0f3342b0944313a895b6f8838918fcddd"
assert C["branch_ref"] == REF and C["remote"] == REMOTE
assert C["head"] == BASE and C["tree"] == TREE
assert ROOT == Path("/home/qq/af52-learning-local-decision-20261111")
assert WORK == ROOT / "ordinary-native-evidence-v5-publish-20261112-af52"
assert SOURCE == ROOT / "ordinary-715a572-root17-diagnostic-v2/source"
assert Path.cwd() == ROOT and not WORK.exists()
assert not any(os.environ.get(k) for k in (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
)), "Do not redirect Git ownership through inherited repository variables"
WORK.mkdir(mode=0o700)
RECORDS.mkdir(mode=0o700)
ENV = dict(os.environ)
ENV.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
R = {
    "schema": "hepta.original-native-evidence.git-publication.v1",
    "status": "preparing",
    "base": BASE,
    "base_tree": TREE,
    "branch_ref": REF,
    "remote": REMOTE,
    "steps": [],
    "push_attempted": False,
    "native_or_cargo_executed": False,
    "authorityGranted": False,
    "ordinary_complete_chains": 0,
    "positive_adoption_chains": 0,
    "ordinary_no_update_rollback_chains": 0,
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()

def write_new(path, data):
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

def run(label, args, cwd=ROOT, data=None, allowed=(0,), extra_env=None, budget=180):
    entry = {"name": label, "argv": args, "cwd": str(cwd), "status": "running"}
    R["steps"].append(entry)
    print(json.dumps({"step": label, "status": "running"}), flush=True)
    env = ENV if extra_env is None else dict(ENV, **extra_env)
    try:
        p = subprocess.run(
            args, cwd=cwd, env=env, input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=budget, check=False,
        )
        out, err = p.stdout, p.stderr
        entry.update(status="completed", exit=p.returncode)
    except subprocess.TimeoutExpired as error:
        out, err = error.stdout or b"", error.stderr or b""
        entry.update(status="transport-command-timeout", exit=None, error=repr(error))
        p = None
    for suffix, raw in (("stdout", out), ("stderr", err)):
        path = RECORDS / (label + "." + suffix)
        write_new(path, raw)
        entry[suffix] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    print(json.dumps({"step": label, "status": entry["status"], "exit": entry.get("exit")}), flush=True)
    if p is None:
        raise RuntimeError(label + ": command outcome unknown; original output retained")
    if p.returncode not in allowed:
        raise RuntimeError(label + ": original Git exit " + str(p.returncode))
    return p

def git(label, *args, cwd=REPO, data=None, allowed=(0,), extra_env=None, budget=180):
    return run(label, ["git", "-C", str(cwd), *args], cwd=ROOT,
               data=data, allowed=allowed, extra_env=extra_env, budget=budget)

def identity(label):
    head = git(label + "-head", "rev-parse", "HEAD", cwd=SOURCE).stdout.decode().strip()
    tree = git(label + "-tree", "rev-parse", "HEAD^{tree}", cwd=SOURCE).stdout.decode().strip()
    status = git(label + "-status", "status", "--porcelain=v1", "--untracked-files=all", cwd=SOURCE).stdout.decode()
    refs = git(label + "-refs", "for-each-ref", "--format=%(refname)%00%(objectname)", cwd=SOURCE).stdout
    return {"head": head, "tree": tree, "status": status, "refs_sha256": sha(refs)}

def read_stable(path, limit):
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit, str(path)
    raw = path.read_bytes()
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    witness = {k: getattr(before, k) for k in fields}
    assert witness == {k: getattr(after, k) for k in fields}
    assert len(raw) == before.st_size
    return raw, witness

def remote_ref(label):
    p = git(label, "ls-remote", "--exit-code", "--refs", REMOTE, REF, allowed=(0, 2), budget=180)
    lines = p.stdout.decode().splitlines()
    if p.returncode == 2:
        assert not lines
        return None
    assert len(lines) == 1
    value, actual_ref = lines[0].split("\t")
    assert actual_ref == REF and len(value) == 40
    return value

before = None
archive_bytes = None
export_bytes = None
archive_witness = None
export_witness = None
commit = None
try:
    before = identity("source-before")
    assert before["head"] == BASE and before["tree"] == TREE and before["status"] == ""
    R["source_before"] = before
    original_request = "".join(sys.argv[2:]).encode()
    assert len(original_request) == 199062
    assert sha(original_request) == "71478a60b9f41529044a9c066e7177df8ab9be9c19bb5a833daf8b78ea7d97b5"
    assert blob(original_request) == "8e16a604428568c346fdba3cb1b961d5f626b523"
    old_request = json.loads(original_request)
    old_config = json.loads("".join(old_request["args"][3:]))
    assert old_config["source"] == str(SOURCE)
    assert old_config["head"] == BASE and old_config["tree"] == TREE

    export_dir = Path(old_config["work"])
    assert export_dir == ROOT / "ordinary-715-and-caller-original-records-export-v5-20261112"
    archive_path = export_dir / "original-records.tar.xz"
    export_path = export_dir / "export.json"
    archive_bytes, archive_witness = read_stable(archive_path, 2 * 1024 * 1024)
    export_bytes, export_witness = read_stable(export_path, 128 * 1024)
    assert len(archive_bytes) == 1894408
    assert sha(archive_bytes) == "b887df69055e182cae12aa6c588c91313c50c1761fb9c4323ed8621a5472e0e9"
    assert blob(archive_bytes) == "891109a74a5484451195bdaed03629de505dc131"

    payloads = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:xz") as tf:
        members = tf.getmembers()
        assert len(members) == 182
        for item in members:
            path = PurePosixPath(item.name)
            assert item.isfile() and not path.is_absolute() and ".." not in path.parts
            assert str(path) == item.name and item.name not in payloads
            assert "\\" not in item.name and "\0" not in item.name and "\n" not in item.name
            assert 0 <= item.size <= 32 * 1024 * 1024
            stream = tf.extractfile(item)
            assert stream is not None
            raw = stream.read()
            assert len(raw) == item.size
            payloads[item.name] = raw
        assert sum(map(len, payloads.values())) <= 128 * 1024 * 1024
    manifest_raw = payloads["MANIFEST.json"]
    manifest = json.loads(manifest_raw)
    assert manifest["status"] == "verified-original-record-export"
    assert manifest["business_acceptance"] is False
    assert manifest["anchor_source"] == BASE and manifest["anchor_tree"] == TREE
    anchor = {"head": BASE, "tree": TREE, "status": ""}
    assert manifest["source_before"] == anchor and manifest["source_after"] == anchor
    rows = manifest["files"]
    assert len(rows) == 181 and len({row["path"] for row in rows}) == 181
    assert set(payloads) == {"MANIFEST.json", *(row["path"] for row in rows)}
    verified_members = []
    for row in rows:
        raw = payloads[row["path"]]
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"] and blob(raw) == row["git_blob"]
        verified_members.append({k: row[k] for k in ("path", "bytes", "sha256", "git_blob")})
    assert len(old_config["sources"]) == 7
    for source in old_config["sources"]:
        raw = payloads[source["name"] + "/" + source["terminal"]]
        terminal = json.loads(raw)
        if source["sha256"] is not None:
            assert sha(raw) == source["sha256"]
        for key, expected in source["expected"].items():
            assert terminal[key] == expected
        assert terminal.get("status") != "running"

    encoded_size = 4 * ((len(archive_bytes) + 2) // 3)
    expected_export = {
        "schema": manifest["schema"],
        "status": manifest["status"],
        "archive": str(archive_path),
        "bytes": len(archive_bytes),
        "sha256": sha(archive_bytes),
        "git_blob": blob(archive_bytes),
        "members": 182,
        "payload_files": 181,
        "excluded": manifest["excluded"],
        "base64_parts": [
            str(export_dir / ("part-%03d.txt" % i))
            for i in range((encoded_size + 47999) // 48000)
        ],
        "manifest_sha256": sha(manifest_raw),
        "source_before": anchor,
        "source_after": anchor,
    }
    assert json.loads(export_bytes) == expected_export

    actual_args = sys.orig_argv
    assert actual_args[:3] == ["/usr/bin/python3", "-B", "-c"]
    assert actual_args[4:] == sys.argv[1:]
    transport = C["transport"]
    request = {
        "host": transport["host"],
        "executable": "/usr/bin/python3",
        "args": actual_args[1:],
        "cwd": str(ROOT),
        "idempotency_key": transport["idempotency_key"],
        "rows": transport["rows"],
        "cols": transport["cols"],
    }
    request_raw = json_bytes(request)
    assert request["host"] == "ai395"
    assert request["idempotency_key"] == "hepta-native-evidence-v5-git-publication-20261112-af52"
    assert (request["rows"], request["cols"]) == (24, 160)

    git("clone-independent", "clone", "--shared", "--no-checkout", "--no-tags", str(SOURCE), str(REPO), cwd=ROOT)
    assert git("independent-root", "rev-parse", "--show-toplevel").stdout.decode().strip() == str(REPO)
    assert git("independent-git-dir", "rev-parse", "--absolute-git-dir").stdout.decode().strip() == str(REPO / ".git")
    assert git("parent-tree", "rev-parse", BASE + "^{tree}").stdout.decode().strip() == TREE
    assert remote_ref("remote-ref-before") is None, "The evidence branch already exists; do not overwrite it"
    git("load-parent-index", "read-tree", BASE)
    prefix = C["evidence_prefix"]
    assert prefix == "qualification/ordinary-owner-assembly-20261111/native-evidence/v5"
    files = {
        prefix + "/original-records.tar.xz": archive_bytes,
        prefix + "/export.json": export_bytes,
        prefix + "/exact-export-request.json": original_request,
    }
    original_paths = git("parent-paths", "ls-tree", "-r", "--name-only", BASE, "--", prefix).stdout
    assert not original_paths, "Only new evidence paths are allowed"
    allowlist_path = ".github/blob-size-allowlist.txt"
    allowlist_mode = git("parent-allowlist-mode", "ls-tree", BASE, "--", allowlist_path).stdout
    assert allowlist_mode == ("100644 blob " + C["allowlist"]["before_blob"] + "\t" + allowlist_path + "\n").encode()
    allowlist = git("parent-allowlist", "show", BASE + ":" + allowlist_path).stdout
    assert blob(allowlist) == C["allowlist"]["before_blob"]
    assert sha(allowlist) == C["allowlist"]["before_sha256"]
    assert allowlist.endswith(b"\n")
    line = C["allowlist"]["append_line"].encode()
    assert line == ("sha256:" + sha(archive_bytes) + " " + prefix + "/original-records.tar.xz\n").encode()
    assert line not in allowlist and (prefix + "/original-records.tar.xz").encode() not in allowlist
    after_allowlist = allowlist + line
    assert blob(after_allowlist) == C["allowlist"]["after_blob"]
    assert sha(after_allowlist) == C["allowlist"]["after_sha256"]

    after_validation = identity("source-after-validation")
    assert after_validation == before
    verification = {
        "schema": R["schema"],
        "status": "verified-local-evidence-before-single-push",
        "base": BASE,
        "base_tree": TREE,
        "remote": REMOTE,
        "branch_ref": REF,
        "expected_remote_ref_before_push": None,
        "source_before": before,
        "source_after_validation": after_validation,
        "archive": expected_export,
        "archive_manifest_sha256": sha(manifest_raw),
        "verified_members": verified_members,
        "original_export_request": {
            "bytes": len(original_request), "sha256": sha(original_request), "git_blob": blob(original_request),
            "origin": "Byte-identical retained operator request 8e16a604428568c346fdba3cb1b961d5f626b523",
        },
        "publication_invocation": {
            "origin": "Reconstructed from actual sys.orig_argv and declared h transport fields; not an MCP response receipt",
            "raw_utf8": request_raw.decode(),
            "bytes": len(request_raw), "sha256": sha(request_raw), "git_blob": blob(request_raw),
            "operator_request_comparison": "Compare this digest with the separately persisted exact h_pty_start request before interpreting the invocation.",
        },
        "export_preparation_review": C["export_preparation_review"],
        "allowlist": dict(C["allowlist"], path=allowlist_path, original_bytes_preserved=True, global_limit_unchanged=512000),
        "payloads_before_publication_metadata": [
            {"path": path, "bytes": len(raw), "sha256": sha(raw), "git_blob": blob(raw)}
            for path, raw in sorted(files.items())
        ],
        "qualification": {
            "native_or_tests_executed_by_this_request": False,
            "prior_failures_preserved": True,
            "new_qualification_claimed": False,
            "authorityGranted": False,
            "ordinary_complete_chains": 0,
            "positive_adoption_chains": 0,
            "ordinary_no_update_rollback_chains": 0,
        },
        "publication_result": "Not included in this pre-push commit; original stdout/stderr, exit and final read-only reference verification remain in the independent records/RESULT.json.",
    }
    files[prefix + "/PUBLICATION.json"] = json_bytes(verification)
    assert len(files) == 4
    assert all(len(raw) <= 512000 for path, raw in files.items() if not path.endswith(".tar.xz"))
    files[allowlist_path] = after_allowlist
    entries = []
    for index, (path, raw) in enumerate(sorted(files.items())):
        actual = git("write-object-%02d" % index, "hash-object", "-w", "--stdin", data=raw).stdout.decode().strip()
        assert actual == blob(raw)
        git("index-object-%02d" % index, "update-index", "--add", "--cacheinfo", "100644", actual, path)
        entries.append({"path": path, "mode": "100644", "git_blob": actual, "bytes": len(raw), "sha256": sha(raw)})
    evidence_tree = git("write-evidence-tree", "write-tree").stdout.decode().strip()
    delta = git("verify-exact-tree-delta", "diff-tree", "--no-commit-id", "--no-renames", "--name-status", "-r", BASE, evidence_tree).stdout.decode().splitlines()
    expected_delta = sorted(("M\t" if path == allowlist_path else "A\t") + path for path in files)
    assert sorted(delta) == expected_delta and len(delta) == 5
    R.update(evidence_tree=evidence_tree, files=entries, exact_tree_delta=delta)
    message = (
        "qualification: retain original native and caller records v5\n\n"
        "Preserve the verified original archive, exact export request and original export metadata.\n"
        "The parent is the fixed 715 source; the only changes are four evidence files and one exact archive-size exception.\n"
        "Retain failed attempts and diagnostic scope; this transport adds no native or ordinary-business qualification.\n"
    )
    author_date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    author = {
        "GIT_AUTHOR_NAME": "Hepta qualification evidence",
        "GIT_AUTHOR_EMAIL": "qualification@local.invalid",
        "GIT_COMMITTER_NAME": "Hepta qualification evidence",
        "GIT_COMMITTER_EMAIL": "qualification@local.invalid",
        "GIT_AUTHOR_DATE": author_date,
        "GIT_COMMITTER_DATE": author_date,
    }
    commit = git("create-evidence-commit", "-c", "user.name=Hepta qualification evidence",
                 "-c", "user.email=qualification@local.invalid", "commit-tree",
                 evidence_tree, "-p", BASE, data=message.encode(), extra_env=author).stdout.decode().strip()
    assert git("verify-parent", "rev-list", "--parents", "-n", "1", commit).stdout.decode().strip() == commit + " " + BASE
    assert git("verify-commit-tree", "rev-parse", commit + "^{tree}").stdout.decode().strip() == evidence_tree
    assert git("verify-archive-object", "rev-parse", commit + ":" + prefix + "/original-records.tar.xz").stdout.decode().strip() == "891109a74a5484451195bdaed03629de505dc131"
    git("retain-local-evidence-ref", "update-ref", REF, commit, "0" * 40)
    R["commit"] = commit
    R["source_before_push"] = identity("source-before-push")
    assert R["source_before_push"] == before
    again, witness = read_stable(archive_path, 2 * 1024 * 1024)
    assert again == archive_bytes and witness == archive_witness
    again, witness = read_stable(export_path, 128 * 1024)
    assert again == export_bytes and witness == export_witness
    R["status"] = "single-push-starting"
    R["push_attempted"] = True
    git("push-only-new-evidence-ref", "push", "--porcelain", "--no-follow-tags",
        "--recurse-submodules=no", "--force-with-lease=" + REF + ":",
        REMOTE, REF + ":" + REF, budget=300)
    R["remote_after"] = remote_ref("remote-ref-after")
    assert R["remote_after"] == commit
    R["status"] = "published-and-reference-verified"
except BaseException as error:
    R.update(status="failed-or-uncertain", failure=repr(error), traceback=traceback.format_exc())
    if R["push_attempted"]:
        try:
            R["remote_after_failed_push"] = remote_ref("remote-ref-after-failure")
            R["failed_push_commit_observed"] = commit is not None and R["remote_after_failed_push"] == commit
        except BaseException as read_error:
            R["remote_readback_error"] = repr(read_error)
finally:
    try:
        R["source_after"] = identity("source-final")
        R["source_unchanged"] = before is not None and R["source_after"] == before
        assert R["source_unchanged"]
        if archive_bytes is not None:
            raw, witness = read_stable(archive_path, 2 * 1024 * 1024)
            assert raw == archive_bytes and witness == archive_witness
        if export_bytes is not None:
            raw, witness = read_stable(export_path, 128 * 1024)
            assert raw == export_bytes and witness == export_witness
    except BaseException as final_error:
        R["final_integrity_error"] = repr(final_error)
        R["status"] = "failed-or-uncertain"
    raw = json_bytes(R)
    write_new(RECORDS / "RESULT.json", raw)
    print(json.dumps({
        "status": R["status"], "commit": R.get("commit"), "tree": R.get("evidence_tree"),
        "branch_ref": REF, "source_unchanged": R.get("source_unchanged"),
        "result_path": str(RECORDS / "RESULT.json"), "bytes": len(raw), "sha256": sha(raw),
        "push_attempts": int(R["push_attempted"]),
    }), flush=True)
raise SystemExit(0 if R["status"] == "published-and-reference-verified" else 1)
