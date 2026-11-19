"""Retain exact Git material and qualify one ordered upstream reference.

No upstream code or tests execute outside future_native's real bwrap child.
The declared test scope is every changed original test file, or the full original
test tree when no test file changed; no individual failure is filtered out.
"""

import argparse
import ast
import configparser
import hashlib
import io
import json
from pathlib import Path
import resource
import shlex
import subprocess
import tarfile
import time

import future_native as native


def git(root, output, args):
    count = (
        len(list((output / "commands").iterdir()))
        if (output / "commands").exists()
        else 0
    )
    folder = output / "commands" / str(count)
    folder.mkdir(parents=True)
    argv = ["git", "--git-dir=" + str(root / "upstream.git"), *args]
    native.write(
        folder / "INTENT.json",
        {"argv": argv, "started_at_ns": str(time.time_ns()), "timeout_seconds": 600},
    )
    start, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
        code, stdout, stderr, timed_out = (
            proc.returncode,
            proc.stdout,
            proc.stderr,
            False,
        )
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr, timed_out = (
            None,
            error.stdout or b"",
            error.stderr or b"",
            True,
        )
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    native.write(folder / "STDOUT", stdout)
    native.write(folder / "STDERR", stderr)
    native.write(
        folder / "EXIT.json",
        {
            "exit_code": code,
            "timed_out": timed_out,
            "wall_seconds": time.perf_counter() - start,
            "completed_child_cpu_seconds": after.ru_utime
            + after.ru_stime
            - usage.ru_utime
            - usage.ru_stime,
            "stdout_sha256": native.sha(stdout),
            "stderr_sha256": native.sha(stderr),
        },
    )
    if code != 0 or timed_out:
        raise RuntimeError("retained acquisition command failed: " + str(folder))
    return stdout


def materialize(root, output, revision, section, only_prefix=None):
    listing = git(root, output, ["ls-tree", "-rz", revision])
    expected = {}
    for row in listing.split(b"\x00"):
        if not row:
            continue
        meta, name = row.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        expected[name.decode()] = (mode, kind, blob)
    archive = git(
        root,
        output,
        ["archive", "--format=tar", revision, *([only_prefix] if only_prefix else [])],
    )
    target = output / section
    target.mkdir()
    retained = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream.getmembers():
            rel = Path(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("unsafe original archive path")
            if member.isdir():
                (target / rel).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(
                    "non-regular original archive member is not materialized"
                )
            raw = stream.extractfile(member).read()
            git_sha = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\x00" + raw
            ).hexdigest()
            mode, kind, blob = expected[member.name]
            if kind != "blob" or mode not in ("100644", "100755") or git_sha != blob:
                raise ValueError("archive member is not exact original Git blob")
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            native.write(path, raw)
            retained.append(
                {
                    "path": str(Path(section) / rel),
                    "bytes": len(raw),
                    "sha256": native.sha(raw),
                    "original_revision": revision,
                    "original_git_path": member.name,
                    "original_git_blob": blob,
                }
            )
    return retained


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--commit-index", type=int, required=True)
    parser.add_argument("--source-index", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dependency-bundle")
    parser.add_argument("--dependency-sha256")
    args = parser.parse_args()
    root, output = Path(args.repository_root), Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    scanned = json.loads((root / "RESULT.json").read_bytes())
    commit = scanned["commits"][args.commit_index]
    source = commit["source_candidates"][args.source_index]
    if source["status"] != "REQUIRES_QUALIFICATION":
        raise ValueError("not an ordered static potential")
    project = scanned["canonical_repository"]
    native.write(
        output / "INTENT.json",
        {
            "repository": project,
            "commit_index": args.commit_index,
            "source_index": args.source_index,
            "commit": commit["commit"],
            "parent": commit["parent"],
            "source": source,
            "started_at_ns": str(time.time_ns()),
            "scanner_RESULT_sha256": native.sha((root / "RESULT.json").read_bytes()),
            "source_sha256": native.sha(Path(__file__).read_bytes()),
            "native_source_sha256": native.sha(Path(native.__file__).read_bytes()),
            "new_model_calls": 0,
            "new_training_updates": 0,
            "test_scope": "whole changed original test files; otherwise all test files under the original tests tree",
        },
    )
    files = materialize(root, output, commit["parent"], "before")
    top_level = (
        git(root, output, ["ls-tree", "--name-only", commit["commit"]])
        .decode()
        .splitlines()
    )
    roots = [
        name for name in ("tests", "test", "testing", "test_suite") if name in top_level
    ]
    if len(roots) != 1:
        raise ValueError(
            "exactly one original supported test root is required: " + repr(roots)
        )
    test_root = roots[0]
    files += materialize(root, output, commit["commit"], "after-tests", test_root)
    root_test_files = []
    original_pytest_ini = False
    if "conftest.py" in top_level:
        for name in ("conftest.py", "pytest.ini"):
            if name not in top_level:
                continue
            raw = git(root, output, ["show", commit["commit"] + ":" + name])
            entry = (
                git(root, output, ["ls-tree", commit["commit"], "--", name])
                .decode()
                .strip()
            )
            meta, original_path = entry.split("\t")
            mode, kind, blob = meta.split()
            assert (
                original_path == name
                and mode in ("100644", "100755")
                and kind == "blob"
            )
            assert (
                hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\x00" + raw
                ).hexdigest()
                == blob
            )
            path = output / "after-root" / name
            path.parent.mkdir(exist_ok=True)
            native.write(path, raw)
            files.append(
                {
                    "path": str(path.relative_to(output)),
                    "bytes": len(raw),
                    "sha256": native.sha(raw),
                    "original_revision": commit["commit"],
                    "original_git_path": name,
                    "original_git_blob": blob,
                }
            )
            root_test_files.append({"path": name, "sha256": native.sha(raw)})
            if name == "pytest.ini":
                config = configparser.ConfigParser(interpolation=None)
                config.read_string(raw.decode())
                if config.sections() != ["pytest"] or set(config["pytest"]) - {
                    "addopts",
                    "testpaths",
                    "norecursedirs",
                    "usefixtures",
                    "filterwarnings",
                }:
                    raise ValueError(
                        "unsupported original pytest configuration; no config is silently dropped"
                    )
                if shlex.split(config["pytest"].get("addopts", "")) not in (
                    [],
                    ["--doctest-modules"],
                ):
                    raise ValueError(
                        "original pytest options outside frozen original-file scope"
                    )
                if any(
                    not name.isidentifier()
                    for name in config["pytest"].get("usefixtures", "").split()
                ):
                    raise ValueError("unsupported original fixture identifier")
                if any(
                    line.strip() != "error"
                    for line in config["pytest"].get("filterwarnings", "").splitlines()
                    if line.strip()
                ):
                    raise ValueError(
                        "original warning filtering needs separate explicit review"
                    )
                original_pytest_ini = True
    raw = git(root, output, ["show", commit["commit"] + ":" + source["path"]])
    if native.sha(raw) != source["after_sha256"]:
        raise ValueError("reference source differs from original scan")
    oracle = output / "oracle" / source["path"]
    oracle.parent.mkdir(parents=True)
    native.write(oracle, raw)
    files.append(
        {
            "path": str(oracle.relative_to(output)),
            "bytes": len(raw),
            "sha256": native.sha(raw),
            "original_revision": commit["commit"],
            "original_git_path": source["path"],
            "original_git_blob": source["after_git_blob"],
        }
    )
    tests = [
        path
        for path in commit["original_changed_test_paths"]
        if (output / "after-tests" / path).is_file()
        and Path(path).name.startswith("test")
    ]
    if not tests:
        tests = sorted(
            str(path.relative_to(output / "after-tests"))
            for path in (output / "after-tests" / test_root).rglob("test*.py")
        )
    if not tests or any(not path.startswith(test_root + "/") for path in tests):
        raise ValueError("no original case files in the supported tests root")
    test_prefix = "after-tests/" + test_root + "/"
    test_files = [
        {"path": row["path"][len(test_prefix) :], "sha256": row["sha256"]}
        for row in files
        if row["path"].startswith(test_prefix)
    ]
    test_ast = [
        {
            "path": path,
            "normalized_ast_sha256": native.sha(
                ast.dump(
                    ast.parse((output / "after-tests" / path).read_bytes()),
                    include_attributes=False,
                ).encode()
            ),
        }
        for path in tests
    ]
    # The package is the parent source tree, never the whole repaired commit.
    parts = Path(source["path"]).parts
    import_root = "src" if parts[0] == "src" else "."
    package = parts[1] if import_root == "src" else parts[0]
    if package.endswith(".py"):
        package = package[:-3]
    extra = source.get("optional_constant")
    spec = {
        "schema": "hepta.future-original-native-task.v1",
        "project_id": project,
        "original_parent": commit["parent"],
        "original_commit": commit["commit"],
        "source_path": source["path"],
        "function": source["function"],
        "optional_constant": extra["name"] if extra else None,
        "before_sha256": source["before_sha256"],
        "after_sha256": source["after_sha256"],
        "package_import_root": import_root,
        "package_names": [package],
        "test_root": test_root,
        "test_selectors": [path[len(test_root + "/") :] for path in tests],
        "test_files": test_files,
        "test_ast": test_ast,
        "files": files,
        "original_gate_sha256": native.ANCESTOR_SHA,
        "original_parser_sha256": native.CODEC_SHA,
        "new_model_calls": 0,
    }
    spec.update(
        root_test_files=root_test_files, original_pytest_ini=original_pytest_ini
    )
    if bool(args.dependency_bundle) != bool(args.dependency_sha256):
        raise ValueError("both exact dependency manifest path and SHA are required")
    if args.dependency_bundle:
        spec["dependency_bundle"] = {
            "path": args.dependency_bundle,
            "sha256": args.dependency_sha256,
        }
    if extra and not extra["existing"]:
        # A frozen original anchor name is derived from BEFORE, never model text.
        text = (output / "before" / source["path"]).read_text()
        tree = ast.parse(text)
        codec = native.load_module(
            "future_anchor_parser", native.CODEC, native.CODEC_SHA
        )
        gate = native.load_module(
            "future_anchor_gate", native.ANCESTOR, native.ANCESTOR_SHA
        )
        anchors = [
            node
            for node in tree.body
            if list(codec.node_span(text, node)[:2]) == extra["anchor_span"]
        ]
        if len(anchors) != 1 or not gate.constant_name(anchors[0]):
            raise ValueError("new constant lacks an original named constant anchor")
        spec["constant_insert_before_original_name"] = gate.constant_name(anchors[0])
    native.write(output / "TASK_SPEC.json", spec)
    admitted = native.bound(output / "TASK_SPEC.json")
    before, after = native.before_oracle(admitted)
    gate = native.load_module(
        "future_reference_original_gate", native.ANCESTOR, native.ANCESTOR_SHA
    )
    gate.TARGETS[project] = (
        spec["source_path"],
        spec["function"],
        spec["optional_constant"],
    )
    native.write(
        output / "REFERENCE_ADMISSION.json",
        gate.check_ast(project, before, after, after),
    )
    first = native.run_native(admitted, output / "before-run", label="original_parent")
    second = native.run_native(
        admitted, output / "after-run", after, label="exact_reference_function"
    )

    def identities(result):
        return [(row["classname"], row["name"]) for row in result.get("cases", [])]

    qualified = bool(
        first["actual_wait_returncode"] == 1
        and first.get("failures", 0) > 0
        and first.get("errors") == first.get("skipped") == 0
        and not first["timed_out"]
        and first["sandbox_attestation_sha256"]
        and second["success"]
        and identities(first) == identities(second)
    )
    result = {
        "status": "ORIGINAL_NATIVE_PAIR_PASSED"
        if qualified
        else "ORIGINAL_NATIVE_PAIR_REJECTED",
        "repository": project,
        "commit_index": args.commit_index,
        "source_index": args.source_index,
        "commit": commit["commit"],
        "parent": commit["parent"],
        "function": source["function"],
        "source_path": source["path"],
        "task_spec_sha256": native.sha((output / "TASK_SPEC.json").read_bytes()),
        "same_original_case_set": identities(first) == identities(second),
        "expected_cases": identities(second),
        "before": first,
        "after": second,
        "native_children": 2,
        "model_calls": 0,
        "training_updates": 0,
        "wall_seconds": time.perf_counter() - started,
        "remaining_qualification": [
            "license/notices",
            "exact shared codec/reference output",
            "complete context budget",
            "all old source/test deduplication",
        ],
        "candidate_selected": False,
    }
    native.write(output / "RESULT.json", result)
    print(
        json.dumps(
            {
                "path": str(output / "RESULT.json"),
                "sha256": native.sha((output / "RESULT.json").read_bytes()),
                "status": result["status"],
                "before": {
                    key: first.get(key)
                    for key in (
                        "actual_wait_returncode",
                        "tests",
                        "failures",
                        "errors",
                        "skipped",
                        "timed_out",
                    )
                },
                "after": {
                    key: second.get(key)
                    for key in (
                        "actual_wait_returncode",
                        "tests",
                        "failures",
                        "errors",
                        "skipped",
                        "timed_out",
                    )
                },
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
