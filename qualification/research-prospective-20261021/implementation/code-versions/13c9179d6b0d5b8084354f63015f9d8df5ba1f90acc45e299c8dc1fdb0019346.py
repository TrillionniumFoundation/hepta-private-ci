"""Capture preselected public Git object bytes, license bytes and read-only probes.

No repository-supplied code, hook, model output or shell text is executed. The
original Git SHA1 binds raw commit/tree/blob objects; SHA256 records each local
artifact. This attests byte integrity, not independent authorship or semantics.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def object_sha(kind, data):
    return hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).hexdigest()


def capture(entry, output):
    repo = entry["repo"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("precommitted repository identifier required")
    for name in ("previous_sha", "current_sha", "previous_tree", "current_tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", entry[name]):
            raise ValueError("exact SHA1 Git object identifier required")
    output.mkdir()
    bare = output / "objects.git"
    commands = []

    def git(args, *, payload=None, check=True):
        argv = ["git", "-c", "pack.threads=1", "-c", "core.hooksPath=/dev/null",
                "-c", "submodule.recurse=false", *args]
        started = time.perf_counter()
        result = subprocess.run(
            argv, input=payload, capture_output=True, timeout=90,
            env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
        )
        commands.append(dict(
            argv=argv, returncode=result.returncode,
            stdout_base64=base64.b64encode(result.stdout).decode(),
            stderr_base64=base64.b64encode(result.stderr).decode(),
            seconds=time.perf_counter()-started,
        ))
        if check and result.returncode:
            raise RuntimeError(f"Git read-only acquisition failed: {args[0]}")
        return result

    try:
        git(["init", "--bare", str(bare)])
        prefix = ["--git-dir", str(bare)]
        git([*prefix, "fetch", "--filter=blob:none", "--depth=2", "--no-tags",
             f"https://github.com/{repo}.git", entry["current_sha"]])
        records = []
        for label, kind, identifier in (
            ("previous-commit", "commit", entry["previous_sha"]),
            ("current-commit", "commit", entry["current_sha"]),
            ("previous-tree", "tree", entry["previous_tree"]),
            ("current-tree", "tree", entry["current_tree"]),
        ):
            raw = git([*prefix, "cat-file", kind, identifier]).stdout
            if object_sha(kind, raw) != identifier:
                raise ValueError("original Git object bytes differ from publisher SHA")
            filename = label + ".raw"
            (output / filename).write_bytes(raw)
            records.append(dict(label=label, kind=kind, git_sha1=identifier,
                                filename=filename, sha256=sha256(raw), bytes=len(raw)))
        current = (output / "current-commit.raw").read_bytes()
        parent_lines = [line[7:].decode() for line in current.split(b"\n\n", 1)[0].splitlines()
                        if line.startswith(b"parent ")]
        if not parent_lines or parent_lines[0] != entry["previous_sha"]:
            raise ValueError("first-parent relation not present in original commit bytes")
        for label, tree in (("previous", entry["previous_tree"]), ("current", entry["current_tree"])):
            raw = (output / f"{label}-commit.raw").read_bytes()
            if not raw.startswith(f"tree {tree}\n".encode()):
                raise ValueError("declared tree differs from original commit bytes")

        listing = git([*prefix, "ls-tree", "-z", entry["current_sha"]]).stdout
        licenses = []
        for item in listing.split(b"\0"):
            if not item:
                continue
            header, name_bytes = item.split(b"\t", 1)
            mode, kind, identifier = header.decode().split()
            name = name_bytes.decode("utf-8", "strict")
            if kind != "blob" or mode not in ("100644", "100755"):
                continue
            if not re.fullmatch(r"(?i)(license|copying)(\.[a-z0-9_-]+)?", name):
                continue
            raw = git([*prefix, "cat-file", "blob", identifier]).stdout
            if len(raw) > 2*1024*1024 or object_sha("blob", raw) != identifier:
                raise ValueError("license object bytes fail bound/hash")
            filename = "license-" + name + ".raw"
            (output / filename).write_bytes(raw)
            licenses.append(dict(path=name, filename=filename, git_sha1=identifier,
                                 sha256=sha256(raw), bytes=len(raw)))
        if not licenses:
            raise ValueError("root license bytes unavailable; source remains ineligible")

        correct = git([*prefix, "cat-file", "-t", entry["current_tree"]])
        wrong = git([*prefix, "cat-file", "-t", entry["current_sha"]])
        if correct.returncode != 0 or correct.stdout != b"tree\n" or wrong.stdout != b"commit\n":
            raise ValueError("actual bounded Git object-type probe differs")
        result = dict(
            schema="hepta.external-git-event-source.v1", entry=entry,
            captured_at=utc(), status="original_bytes_and_probe_verified",
            original_objects=records, root_license_objects=licenses,
            actual_readonly_procedure=dict(
                expected_object_type="tree",
                correct_git_object=entry["current_tree"],
                correct_exit_code=correct.returncode,
                correct_stdout=correct.stdout.decode(),
                wrong_git_object=entry["current_sha"],
                wrong_exit_code=wrong.returncode,
                wrong_stdout=wrong.stdout.decode(),
                correct_predicate=True, wrong_predicate=False,
                process_success_distinct_from_predicate_success=True,
            ),
            independent_publisher_attestation=False,
            license_text_captured_not_legal_advice=True,
            independent_semantic_review=False, authority="DENY_ALL",
            production_accepted=False,
        )
        write(output / "source-receipt.json", result)
        return result
    finally:
        write(output / "commands.json", commands)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    entries = json.loads(args.pairs.read_text())["entries"]
    args.output.mkdir()
    outcomes = []
    for entry in entries:
        if entry.get("status") != "metadata_pair_selected_bytes_pending":
            outcomes.append(dict(repo=entry.get("repo"), status="metadata_ineligible"))
            continue
        try:
            result = capture(entry, args.output / entry["repo"].replace("/", "__"))
            row = dict(repo=entry["repo"], status=result["status"],
                       source_receipt_sha256=sha256((args.output / entry["repo"].replace("/", "__") / "source-receipt.json").read_bytes()))
        except Exception as error:
            row = dict(repo=entry["repo"], status="failed", error_type=type(error).__name__,
                       error=str(error)[:1024])
        outcomes.append(row)
        print(json.dumps(row), flush=True)
    write(args.output / "capture-summary.json", dict(
        source_pairs_sha256=sha256(args.pairs.read_bytes()),
        captured_at=utc(), outcomes=outcomes, new_model_calls=0,
        production_accepted=False,
    ))


if __name__ == "__main__":
    main()
