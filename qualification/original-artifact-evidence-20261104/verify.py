#!/usr/bin/env python3
"""Read original Actions evidence without executing any archived code."""
import argparse
import ast
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

LIMIT = 512 * 1024 * 1024


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, token=None, redirect=False):
    parsed = urllib.parse.urlparse(url)
    require(parsed.scheme == "https", "HTTPS is required")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "immutable-evidence-verifier"}
    if token:
        require(parsed.netloc == "api.github.com", "credentials may only reach GitHub API")
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(urllib.request.Request(url, headers=headers), timeout=120)
    except urllib.error.HTTPError as error:
        if redirect and error.code in (301, 302, 303, 307, 308):
            location = error.headers.get("Location", "")
            require(urllib.parse.urlparse(location).scheme == "https", "invalid artifact redirect")
            return request(location)
        raise
    with response:
        raw = response.read(LIMIT + 1)
    require(len(raw) <= LIMIT, "response exceeds read budget")
    return raw


def fetch_artifact(spec):
    api = "https://api.github.com/repos/" + spec["repository"]
    token = os.environ["GITHUB_TOKEN"]
    metadata = json.loads(request(api + "/actions/artifacts/" + str(spec["artifact_id"]), token))
    require(metadata["id"] == spec["artifact_id"], "wrong artifact identity")
    require(not metadata["expired"], "original artifact expired")
    require(metadata["size_in_bytes"] == spec["bytes"], "artifact size metadata changed")
    require(metadata["digest"] == "sha256:" + spec["sha256"], "artifact digest metadata changed")
    require(metadata["workflow_run"]["id"] == spec["run_id"], "wrong original run")
    require(metadata["workflow_run"]["head_sha"] == spec["workflow_head"], "wrong original workflow head")
    raw = request(api + "/actions/artifacts/" + str(spec["artifact_id"]) + "/zip", token, redirect=True)
    require(len(raw) == spec["bytes"] and sha(raw) == spec["sha256"], "original ZIP bytes differ")
    members = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(sum(info.file_size for info in archive.infolist()) <= LIMIT, "expanded archive exceeds budget")
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in info.filename,
                    "unsafe archive member")
            require(((info.external_attr >> 16) & 0o170000) != 0o120000, "archive symlink rejected")
            require(not (info.flag_bits & 1), "encrypted member rejected")
            if info.is_dir():
                continue
            require(info.filename not in members, "duplicate member")
            # ZipFile.read checks each member CRC.
            members[info.filename] = archive.read(info)
    require(spec.get("receipt_path", "receipt.json") in members or spec["kind"] == "legacy-env",
            "original declared receipt missing")
    return metadata, raw, members


class GitBytes:
    def __init__(self, source, head):
        self.source = source
        self.head = head
        require(self.command("rev-parse", "HEAD").decode().strip() == head, "checkout is not exact source")
        self.tree = {}
        for row in self.command("ls-tree", "-r", "-z", head).split(b"\0"):
            if not row:
                continue
            prefix, name = row.split(b"\t", 1)
            mode, kind, oid = prefix.decode().split()
            self.tree[name.decode()] = (mode, kind, oid)
        self.process = subprocess.Popen(
            ["git", "--no-replace-objects", "cat-file", "--batch"], cwd=source,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.hashes = {}
        self.symlinks = []

    def command(self, *args):
        return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=self.source)

    def blob(self, oid):
        self.process.stdin.write((oid + "\n").encode())
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode().split()
        require(len(header) == 3 and header[0] == oid and header[1] == "blob", "Git object is unavailable")
        size = int(header[2])
        require(size <= LIMIT, "Git blob exceeds budget")
        raw = self.process.stdout.read(size)
        require(len(raw) == size and self.process.stdout.read(1) == b"\n", "truncated Git blob")
        require(hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() == oid,
                "Git blob content identity mismatch")
        return raw

    def read(self, name):
        require(name in self.tree and self.tree[name][1] == "blob", "input is not a Git blob: " + name)
        return self.blob(self.tree[name][2])

    def digest(self, name, follow, visited=()):
        require(name not in visited and len(visited) < 40, "symlink cycle or depth")
        mode, kind, oid = self.tree[name]
        require(kind == "blob", "input is not a blob")
        if oid not in self.hashes:
            raw = self.blob(oid)
            self.hashes[oid] = {"bytes": len(raw), "sha256": sha(raw)}
        result = self.hashes[oid]
        if mode == "120000" and follow:
            target = self.blob(oid).decode()
            require(not target.startswith("/") and "\\" not in target, "absolute symlink target")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            require(not resolved.startswith("../") and resolved in self.tree, "symlink escapes source")
            value = self.digest(resolved, True, (*visited, name))
            self.symlinks.append({"path": name, "git_blob": oid, "link_payload": result,
                                  "resolved_path": resolved, "resolved_sha256": value})
            return value
        return result["sha256"]

    def close(self):
        self.process.stdin.close()
        require(self.process.wait(timeout=60) == 0, "Git object reader failed")


def snapshot_scope(source_code):
    module = ast.parse(source_code)
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == "INPUTS" for x in node.targets):
            value = ast.literal_eval(node.value)
            require(isinstance(value, list) and all(isinstance(x, str) for x in value), "invalid input list")
            return value
    snapshot = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "snapshot")
    for node in ast.walk(snapshot):
        if not isinstance(node, ast.List):
            continue
        try:
            value = ast.literal_eval(node)
        except (ValueError, TypeError):
            continue
        if isinstance(value, list) and value[:4] == ["git", "ls-files", "-z", "--"]:
            return value[4:]
        if isinstance(value, list) and value[:5] == ["git", "--no-replace-objects", "ls-files", "-z", "--"]:
            return value[5:]
    raise RuntimeError("exact source reader has no supported static snapshot scope")


def verify_sources(spec, receipt, members, git):
    before = receipt.get("source_before")
    if before is None:
        before = json.loads(members["source-inputs.json"])
    after = receipt["source_after"]
    require(before and before == after, "bound source changed or empty")
    require(receipt.get("source_unchanged", receipt.get("source_inputs_unchanged")) is True,
            "original source-stability check failed")
    scope = snapshot_scope(git.read(spec["reader"]).decode())
    names = set(filter(None, git.command("ls-files", "-z", "--", *scope).decode().split("\0")))
    require(names == set(before), "snapshot is incomplete or contains unbound extra input")
    for name in sorted(names):
        require(re.fullmatch(r"[0-9a-f]{64}", before[name]) is not None, "invalid source digest")
        require(git.digest(name, spec["kind"] not in {"env", "generation"}) == before[name], "Git input differs: " + name)
    if spec["kind"] == "dylint":
        require(len(names) == 1664, "original Dylint input count changed")
    return {"count": len(names), "before_sha256": sha(canonical(before)),
            "after_sha256": sha(canonical(after)), "all_match_exact_git_bytes": True,
            "snapshot_scope": scope, "symlink_resolution": git.symlinks}


def verify_outputs(receipt, members):
    outputs = receipt.get("outputs", {})
    for name, evidence in outputs.items():
        require(name in members, "missing recorded output: " + name)
        raw = members[name]
        require(len(raw) == evidence["bytes"] and sha(raw) == evidence["sha256"],
                "recorded output differs: " + name)
    for evidence in receipt.get("retained", []):
        raw = members[evidence["file"]]
        require(len(raw) == evidence["bytes"] and sha(raw) == evidence["sha256"], "retained output differs")
    commands = receipt.get("commands", [])
    for command in commands:
        name = command.get("name")
        path = name + ".log" if name else "original-process-suites.log"
        require(sha(members[path]) == command["log_sha256"], "command log differs: " + path)
    return {"recorded_outputs": len(outputs), "retained_outputs": len(receipt.get("retained", [])),
            "command_logs": len(commands),
            "all_members": {name: {"bytes": len(raw), "sha256": sha(raw)} for name, raw in sorted(members.items())}}


def observations(raw):
    text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    return {"summaries": re.findall(
        r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", text),
        "failed_cases": re.findall(r"^test (\S+) \.\.\. FAILED", text, re.M),
        "ignored_cases": re.findall(r"^test (\S+) \.\.\. ignored", text, re.M),
        "panic_blocks": re.findall(r"---- [^\n]+ stdout ----\n.*?(?=\n---- |\nfailures:|\Z)", text, re.S)}


def inspect_state(spec, receipt, members, git):
    require(receipt["status"] == "passed", "original state qualification did not pass")
    require(all(row["exit_code"] == 0 for row in receipt["commands"]), "original command failed")
    by_name = {row["name"]: row for row in receipt["commands"]}
    require(len(by_name) == len(receipt["commands"]), "duplicate command record")
    if receipt["mode"] == "bazel":
        for name, argv in [
            ("committed-lock-first", ["just", "bazel-lock-check"]),
            ("original-lock-update", ["just", "bazel-lock-update"]),
            ("original-lock-check", ["just", "bazel-lock-check"]),
        ]:
            require(by_name[name]["argv"] == argv, "original lock command changed")
        lock = members["MODULE.bazel.lock"]
        require(lock == git.read("MODULE.bazel.lock"), "generated lock differs from committed source")
        require(receipt["generated_lock"] == {"bytes": len(lock), "sha256": sha(lock), "equals_committed": True},
                "lock receipt mismatch")
        labels = [
            "//codex-rs/utils/path-utils:path-utils-unit-tests",
            "//codex-rs/hepta-contracts:hepta-contracts-unit-tests",
            "//codex-rs/hepta-prompt-registry:hepta-prompt-registry-unit-tests",
            "//codex-rs/hepta-agentd:hepta-agentd-unit-tests",
        ]
        argv = by_name["original-private-state-targets"]["argv"]
        require(argv[2:] == ["test", "--nocache_test_results", "--test_output=all", *labels], "Bazel selection changed")
        return {"mode": "bazel", "generated_lock_sha256": sha(lock), "targets": labels,
                "original_command_exits": [row["exit_code"] for row in receipt["commands"]]}
    packages = ["codex-utils-path", "codex-hepta-contracts", "codex-hepta-prompt-registry", "codex-hepta-agentd"]
    require(set(receipt["tests"]) == set(packages), "missing complete library result")
    counts = {}
    for package in packages:
        raw = members[package + ".junit.xml"]
        root = ET.fromstring(raw)
        cases = root.findall(".//testcase")
        names = [case.attrib["name"] for case in cases]
        require(cases and len(set(names)) == len(names), "empty or duplicate JUnit cases")
        require(not any(case.find(tag) is not None for case in cases for tag in ["failure", "error", "skipped"]),
                "failed or skipped native case")
        actual = receipt["tests"][package]
        require(actual["count"] == len(cases) == int(root.attrib["tests"])
                and actual["names"] == sorted(names) and actual["sha256"] == sha(raw)
                and actual["failed_or_skipped"] == [] and actual["required_present"] is True,
                "JUnit differs from recorded case inventory")
        argv = ["just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail",
                "--retries", "0", "--success-output=final"]
        if package == "codex-hepta-agentd":
            argv += ["--test-threads", "1"]
        require(by_name[package]["argv"] == argv, "original complete-library command changed")
        require(b"skipping test:" not in members[package + ".log"].lower(), "early-return skip reported")
        counts[package] = len(cases)
    require(members["rustc-version.log"].startswith(b"rustc 1.96.0 "), "wrong Rust compiler")
    with gzip.GzipFile(fileobj=io.BytesIO(members["metadata.json.gz"])) as compressed:
        raw_metadata = compressed.read(LIMIT + 1)
    require(len(raw_metadata) <= LIMIT and sha(raw_metadata) == receipt["metadata"]["sha256"], "metadata differs")
    require(receipt["metadata"]["exit_code"] == 0 and
            len(json.loads(raw_metadata)["packages"]) == receipt["metadata"]["package_count"], "metadata package count differs")
    result = {"mode": "native", "counts": counts, "total_cases": sum(counts.values()), "skipped": 0,
              "metadata_packages": receipt["metadata"]["package_count"],
              "original_command_exits": [row["exit_code"] for row in receipt["commands"]]}
    if spec["key"] == "state-windows":
        attacks = json.loads(members["acquisition/manifest.json"])
        require(attacks["qualified"] is True and attacks["restored"] is True
                and attacks["source_head"] == spec["source"], "original acquisition controls failed")
        result["original_acquisition_manifest"] = attacks
    return result


def inspect_dylint(receipt, members, git):
    require(receipt["status"] == "passed" and receipt["committed_lock_required"] is True, "Dylint did not qualify committed lock")
    commands = [(row["name"], row["command"], row["exit"]) for row in receipt["steps"]]
    require(commands == [
        ("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
        ("original-lock-update", ["just", "bazel-lock-update"], 0),
        ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
    ], "original Dylint lock commands changed or failed")
    lock = members["MODULE.bazel.lock"]
    require(lock == members["committed-MODULE.bazel.lock"] == git.read("MODULE.bazel.lock"), "Dylint locks differ")
    require(receipt["committed_lock_matches"] is True
            and receipt["committed_lock_sha256"] == receipt["generated_lock_sha256"] == sha(lock)
            and receipt["generated_lock_bytes"] == len(lock), "Dylint lock receipt differs")
    require(len(receipt["outputs"]) == 9, "Dylint output set changed")
    return {"commands": commands, "lock_sha256": sha(lock), "lock_bytes": len(lock)}


def emit_raw(name, raw):
    token = secrets.token_hex(20)
    print("RAW_ORIGINAL_LOG_BEGIN " + name, flush=True)
    print("::stop-commands::" + token, flush=True)
    print(raw.decode("utf-8", errors="replace"), flush=True)
    print("::" + token + "::", flush=True)
    print("RAW_ORIGINAL_LOG_END " + name, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.manifest.read_bytes())
    matches = [item for item in entries if item["key"] == args.key]
    require(len(matches) == 1, "unknown or duplicate manifest key")
    spec = matches[0]
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, zip_raw, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(zip_raw)
    receipt = json.loads(members["receipt.json"])
    require(receipt.get("source_commit", receipt.get("commit")) == spec["source"], "receipt source differs")
    if spec["expected_original_status"] is not None:
        require(receipt["status"] == spec["expected_original_status"], "original status differs from expected evidence")
    git = GitBytes(args.source, spec["source"])
    try:
        source = verify_sources(spec, receipt, members, git)
        outputs = verify_outputs(receipt, members)
        if spec["kind"] == "state":
            result = inspect_state(spec, receipt, members, git)
        elif spec["kind"] == "dylint":
            result = inspect_dylint(receipt, members, git)
        elif spec["kind"] == "generation":
            require(receipt["status"] == "failed", "expected original generation failure")
            require(members["committed-Cargo.lock"] == git.read("codex-rs/Cargo.lock"),
                    "committed Cargo evidence differs from original source")
            require(members["committed-MODULE.bazel.lock"] == git.read("MODULE.bazel.lock"),
                    "committed Bazel evidence differs from original source")
            failed = [row for row in receipt["commands"] if row["exit_code"] != 0]
            require(failed, "original failure command missing")
            result = {"original_commands": receipt["commands"], "failed_command_logs": {}}
            for row in failed:
                name = row["name"] + ".log"
                raw = members[name]
                result["failed_command_logs"][name] = {"bytes": len(raw), "sha256": sha(raw)}
                emit_raw(name, raw)
        elif spec["kind"] == "robrix-lock":
            require(receipt["status"] == "passed" and receipt["committed_lock_required"] is True,
                    "Robrix original committed lock did not pass")
            commands = [(row["name"], row["command"], row["exit"]) for row in receipt["steps"]]
            require(commands == [
                ("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
                ("original-lock-update", ["just", "bazel-lock-update"], 0),
                ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
            ], "Robrix lock sequence differs")
            lock = members["MODULE.bazel.lock"]
            require(lock == members["committed-MODULE.bazel.lock"] == git.read("MODULE.bazel.lock"),
                    "Robrix generated/committed/Git lock mismatch")
            require(receipt["committed_lock_matches"] is True
                    and receipt["committed_lock_sha256"] == receipt["generated_lock_sha256"] == sha(lock)
                    and receipt["generated_lock_bytes"] == len(lock), "Robrix lock receipt mismatch")
            require([(row["stage"], row["command"], row["exit"]) for row in receipt["checkout_checks"]] == [
                ("before", ["git", "diff", "--exit-code", "HEAD", "--"], 0),
                ("after", ["git", "diff", "--exit-code", "HEAD", "--"], 0),
            ], "Robrix checkout checks differ")
            result = {"commands": commands, "lock_sha256": sha(lock), "lock_bytes": len(lock),
                      "checkout_checks": receipt["checkout_checks"]}

        else:
            result = {"original_tests": receipt.get("tests"), "original_steps": receipt.get("steps"),
                      "original_commands": receipt.get("commands"), "native_logs": {}}
            for name, raw in members.items():
                if name in {"memory.log", "robrix.log"} or (spec["kind"] == "env" and name.endswith("-test.log")):
                    result["native_logs"][name] = observations(raw)
                    emit_raw(name, raw)
            require(result["native_logs"], "original native logs are missing")
            if spec["kind"] == "robrix":
                for name in ["original-robrix-corpus-tests.stdout", "original-robrix-corpus-tests.stderr",
                             "robrix.xml", "original-testlog-location.stdout", "original-testlog-location.stderr"]:
                    require(name in members, "missing original Robrix output: " + name)
                    emit_raw(name, members[name])
                result["original_receipt"] = {
                    key: value for key, value in receipt.items() if key != "source_after"
                }
                if receipt["status"] == "passed":
                    text = members["robrix.log"].decode().replace("\r\n", "\n")
                    summaries = re.findall(
                        r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out",
                        text)
                    require(summaries == [("2", "0", "0", "0", "0")], "Robrix full target did not pass")
                    require(set(re.findall(r"^test (\S+) \.\.\. ok$", text, re.M)) == {
                        "robrix_control_v2_generated_projection_and_cross_parser_corpus",
                        "writer_reproduces_the_tracked_artifact_set_byte_for_byte",
                    }, "Robrix original case set differs")
                    require(all(row["exit"] == 0 for row in receipt["steps"]), "Robrix original command failed")

            if spec["kind"] == "env":
                require(receipt["pre_test_powershell_probe"] is False, "unexpected prewarming")
                bash = receipt["bash_launcher"]
                require(bash["version_exit"] == 0 and
                        bash["version_log_sha256"] == sha(members["git-bash-version.log"]), "Bash identity log differs")
                result["bash_launcher"] = bash
    finally:
        git.close()
    report = {
        "schema": 1, "key": spec["key"], "repository": spec["repository"], "source": spec["source"],
        "original_run": spec["run_id"], "artifact_id": spec["artifact_id"], "zip_bytes": len(zip_raw),
        "zip_sha256": sha(zip_raw), "crc_all_members": True, "source_verification": source,
        "original_qualification_status": receipt["status"], "result": result,
        "output_verification": outputs, "evidence_verification": "passed",
        "scope": "Read-only replay of retained evidence; no new product execution or whole-CI admission.",
    }
    (args.output / "VERIFIED.json").write_bytes(json.dumps(report, indent=2).encode() + b"\n")
    (args.output / "receipt.json").write_bytes(members["receipt.json"])
    (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
    compact = {key: value for key, value in report.items() if key != "output_verification"}
    compact["output_counts"] = {key: value for key, value in outputs.items() if key != "all_members"}
    compact["verified_report_sha256"] = sha((args.output / "VERIFIED.json").read_bytes())
    print("EVIDENCE_VERIFIED_JSON=" + json.dumps(compact, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
