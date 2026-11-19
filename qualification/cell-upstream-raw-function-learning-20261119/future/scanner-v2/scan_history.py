"""Acquire an ordered original history only after two real weights are frozen.

This does not evaluate a model or qualify a task. Every static rejection is
retained. An eligible-looking source change still requires original before/after
tests, exact transport, license, context and sandbox checks before selection.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import urllib.request


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def read_bound(path, expected):
    raw = Path(path).read_bytes()
    if sha(raw) != expected:
        raise ValueError("input binding changed: " + str(path))
    return json.loads(raw)


class Commands:
    def __init__(self, output):
        self.output = output
        self.index = 0

    def run(self, args, timeout=180):
        folder = self.output / "commands" / f"{self.index:04d}"
        self.index += 1
        folder.mkdir(parents=True)
        started = time.perf_counter()
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        save(
            folder / "INTENT.json",
            {
                "args": args,
                "started_at_ns": str(time.time_ns()),
                "timeout_seconds": timeout,
            },
        )
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
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
        save(folder / "STDOUT", stdout)
        save(folder / "STDERR", stderr)
        save(
            folder / "EXIT.json",
            {
                "exit_code": code,
                "timed_out": timed_out,
                "wall_seconds": time.perf_counter() - started,
                "completed_child_cpu_seconds": after.ru_utime
                + after.ru_stime
                - usage.ru_utime
                - usage.ru_stime,
                "stdout_sha256": sha(stdout),
                "stderr_sha256": sha(stderr),
            },
        )
        if code != 0 or timed_out:
            raise RuntimeError("acquisition command failed; retained " + str(folder))
        return stdout


def is_test(path):
    pieces = path.lower().split("/")
    name = pieces[-1]
    return (
        any(
            piece in {"test", "tests", "testing", "test_suite"} for piece in pieces[:-1]
        )
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def signature(node):
    value = ast.FunctionDef(
        name=node.name,
        args=node.args,
        body=[],
        decorator_list=node.decorator_list,
        returns=node.returns,
        type_comment=node.type_comment,
        type_params=getattr(node, "type_params", []),
    )
    return ast.dump(value, include_attributes=False)


def span(text, node):
    lines = text.splitlines(keepends=True)
    first = (
        min(
            [
                node.lineno,
                *[item.lineno for item in getattr(node, "decorator_list", [])],
            ]
        )
        - 1
    )
    return len("".join(lines[:first])), len("".join(lines[: node.end_lineno]))


def constant_name(node):
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    return None


def bounded_literal(node):
    value = node.value
    if isinstance(value, ast.Constant):
        return (
            isinstance(value.value, (str, bytes, int, float, bool))
            and len(repr(value.value)) <= 256
        )
    return bool(
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "re"
        and value.func.attr == "compile"
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
        and len(value.args[0].value) <= 256
    )


def inspect_change(before_raw, after_raw):
    before, after = before_raw.decode("utf-8"), after_raw.decode("utf-8")
    trees = [ast.parse(value) for value in (before, after)]
    functions = []
    for tree in trees:
        grouped = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                grouped.setdefault(node.name, []).append(node)
        functions.append(grouped)
    changed = [
        name
        for name in functions[0].keys() & functions[1].keys()
        if [ast.dump(node, include_attributes=False) for node in functions[0][name]]
        != [ast.dump(node, include_attributes=False) for node in functions[1][name]]
    ]
    if len(changed) != 1:
        return {
            "status": "REJECT",
            "reason": "not exactly one changed existing top-level function",
            "changed_existing_functions": sorted(changed),
        }
    name = changed[0]
    if any(len(rows[name]) != 1 for rows in functions):
        return {
            "status": "REJECT",
            "reason": "changed permitted function name is not unique",
            "function": name,
        }
    old, new = [rows[name][0] for rows in functions]
    if signature(old) != signature(new):
        return {
            "status": "REJECT",
            "reason": "function signature or decorators changed",
            "function": name,
        }
    outside = [
        [
            node
            for node in tree.body
            if not (isinstance(node, ast.FunctionDef) and node.name == name)
        ]
        for tree in trees
    ]
    extras = []
    all_names = {constant_name(node) for rows in outside for node in rows} - {None}
    for key in sorted(all_names):
        rows = [
            [node for node in nodes if constant_name(node) == key] for nodes in outside
        ]
        dumps = [
            [ast.dump(node, include_attributes=False) for node in nodes]
            for nodes in rows
        ]
        if dumps[0] != dumps[1]:
            if len(rows[0]) > 1 or len(rows[1]) != 1 or not bounded_literal(rows[1][0]):
                return {
                    "status": "REJECT",
                    "reason": "outside-function constant is not a single bounded literal",
                    "function": name,
                }
            extras.append((key, rows[0][0] if rows[0] else None, rows[1][0]))
    if len(extras) > 1:
        return {
            "status": "REJECT",
            "reason": "more than one module constant changed",
            "function": name,
        }
    extra_name = extras[0][0] if extras else None
    fixed = [
        [
            ast.dump(node, include_attributes=False)
            for node in rows
            if not (extra_name and constant_name(node) == extra_name)
        ]
        for rows in outside
    ]
    if fixed[0] != fixed[1]:
        return {
            "status": "REJECT",
            "reason": "other executable module AST changed",
            "function": name,
        }
    start, end = span(before, old)
    new_start, new_end = span(after, new)
    edits = [(start, end, after[new_start:new_end])]
    extra = None
    if extras:
        key, old_node, new_node = extras[0]
        left, right = span(after, new_node)
        replacement = after[left:right]
        if old_node is not None:
            a, b = span(before, old_node)
            edits.append((a, b, replacement))
            extra = {
                "name": key,
                "existing": True,
                "old_span": [a, b],
                "new_text_sha256": sha(replacement.encode()),
            }
        else:
            # New constants need a unique original next-node anchor. Never infer
            # a replacement from a model answer or choose an arbitrary offset.
            index = trees[1].body.index(new_node)
            if index + 1 >= len(trees[1].body):
                return {
                    "status": "REJECT",
                    "reason": "new constant lacks an original following anchor",
                    "function": name,
                }
            anchor = trees[1].body[index + 1]
            anchor_dump = ast.dump(anchor, include_attributes=False)
            matches = [
                node
                for node in trees[0].body
                if ast.dump(node, include_attributes=False) == anchor_dump
            ]
            if len(matches) != 1:
                return {
                    "status": "REJECT",
                    "reason": "new constant anchor is not unchanged and unique",
                    "function": name,
                }
            a, b = span(before, matches[0])
            edits.append((a, b, replacement + before[a:b]))
            extra = {
                "name": key,
                "existing": False,
                "anchor_span": [a, b],
                "anchor_sha256": sha(before[a:b].encode()),
                "new_text_sha256": sha(replacement.encode()),
            }
    edits.sort()
    if any(left[1] > right[0] for left, right in zip(edits, edits[1:])):
        return {
            "status": "REJECT",
            "reason": "reference spans overlap",
            "function": name,
        }
    rebuilt = before
    for a, b, replacement in reversed(edits):
        if before.count(before[a:b]) != 1:
            return {
                "status": "REJECT",
                "reason": "reference original span is not unique",
                "function": name,
            }
        rebuilt = rebuilt[:a] + replacement + rebuilt[b:]
    if rebuilt != after:
        return {
            "status": "REJECT",
            "reason": "complete permitted function/constant does not reconstruct exact AFTER bytes",
            "function": name,
        }
    return {
        "status": "REQUIRES_QUALIFICATION",
        "function": name,
        "before_sha256": sha(before_raw),
        "after_sha256": sha(after_raw),
        "normalized_before_function_ast_sha256": sha(
            ast.dump(old, include_attributes=False).encode()
        ),
        "normalized_after_function_ast_sha256": sha(
            ast.dump(new, include_attributes=False).encode()
        ),
        "function_before_span": [start, end],
        "function_after_span": [new_start, new_end],
        "optional_constant": extra,
        "exact_reference_reconstruction": True,
        "native_before_after_qualification": False,
        "model_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--repository-index", type=int, required=True)
    parser.add_argument("--repository-metadata")
    parser.add_argument("--repository-metadata-sha256")
    args = parser.parse_args()
    selection = read_bound(args.selection, args.selection_sha256)
    inventory = read_bound(args.inventory, args.inventory_sha256)
    weights = read_bound(args.weights, args.weights_sha256)
    if weights["status"] != "MATCHED_AND_WEIGHTS_FROZEN" or len(weights["arms"]) != 2:
        raise ValueError("both original actual weights must be frozen")
    project = selection["candidate_repositories_in_order"][args.repository_index]
    output = (
        Path(args.root) / f"{args.repository_index:02d}-{project.replace('/', '--')}"
    )
    output.mkdir(parents=True, exist_ok=False)
    save(
        output / "INTENT.json",
        {
            "repository": project,
            "observed_at_ns": str(time.time_ns()),
            "selection_sha256": args.selection_sha256,
            "dedup_inventory_sha256": args.inventory_sha256,
            "weights_frozen_sha256": args.weights_sha256,
            "weights_frozen_at_ns": weights["created_at_ns"],
            "new_model_calls": 0,
            "source_sha256": sha(Path(__file__).read_bytes()),
        },
    )
    old = {row["canonical_repository"].lower() for row in inventory["repositories"]}
    if project.lower() in old:
        save(
            output / "RESULT.json",
            {
                "status": "EXCLUDED_OLD_PANEL_REPOSITORY",
                "repository": project,
                "candidate_content_read": False,
                "model_calls": 0,
            },
        )
        print(
            json.dumps(
                {"status": "EXCLUDED_OLD_PANEL_REPOSITORY", "output": str(output)}
            ),
            flush=True,
        )
        return
    if args.repository_metadata:
        read_bound(args.repository_metadata, args.repository_metadata_sha256)
        metadata_raw = Path(args.repository_metadata).read_bytes()
        save(
            output / "REPOSITORY_HTTP.json",
            {
                "provider": "normal GitHub connector GET repository",
                "url": "https://api.github.com/repos/" + project,
                "retained_path": args.repository_metadata,
                "observed_at_ns": str(time.time_ns()),
                "response_sha256": sha(metadata_raw),
            },
        )
    else:
        request = urllib.request.Request(
            "https://api.github.com/repos/" + project,
            headers={
                "User-Agent": "hepta-frozen-upstream-research",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            metadata_raw = response.read(1024 * 1024)
            save(
                output / "REPOSITORY_HTTP.json",
                {
                    "url": response.url,
                    "status": response.status,
                    "observed_at_ns": str(time.time_ns()),
                    "response_sha256": sha(metadata_raw),
                },
            )
    save(output / "REPOSITORY.json", metadata_raw)
    metadata = json.loads(metadata_raw)
    canonical_name = metadata["full_name"]
    if canonical_name.lower() in old:
        save(
            output / "RESULT.json",
            {
                "status": "EXCLUDED_CANONICAL_OLD_PANEL_REPOSITORY",
                "requested": project,
                "canonical_repository": canonical_name,
                "source_content_read": False,
                "model_calls": 0,
            },
        )
        print(
            json.dumps(
                {
                    "status": "EXCLUDED_CANONICAL_OLD_PANEL_REPOSITORY",
                    "output": str(output),
                }
            ),
            flush=True,
        )
        return
    url = "https://github.com/" + canonical_name + ".git"
    if metadata["clone_url"] != url:
        raise ValueError("unexpected canonical clone URL")
    commands = Commands(output)
    git = output / "upstream.git"
    commands.run(
        ["git", "clone", "--bare", "--filter=blob:none", url, str(git)], timeout=600
    )
    prefix = ["git", "--git-dir", str(git)]
    head = commands.run(prefix + ["rev-parse", "HEAD"]).decode().strip()
    save(
        output / "HEAD_FROZEN.json",
        {
            "requested_repository": project,
            "canonical_repository": canonical_name,
            "repository_id": metadata["id"],
            "maintenance_identity": metadata["owner"]["login"],
            "HEAD": head,
            "observed_at_ns": str(time.time_ns()),
            "authenticated_controller": False,
        },
    )
    commits = (
        commands.run(prefix + ["rev-list", "--no-merges", "--max-count=50", head])
        .decode()
        .splitlines()
    )
    save(
        output / "COMMITS.json",
        {
            "command": ["git", "rev-list", "--no-merges", "--max-count=50", head],
            "commits": commits,
        },
    )
    summaries = []
    for index, commit in enumerate(commits):
        folder = output / "candidates" / f"{index:02d}-{commit}"
        folder.mkdir(parents=True)
        parents = (
            commands.run(prefix + ["rev-list", "--parents", "-n", "1", commit])
            .decode()
            .split()
        )
        commit_raw = commands.run(prefix + ["cat-file", "commit", commit])
        save(folder / "COMMIT", commit_raw)
        if len(parents) != 2:
            result = {
                "commit": commit,
                "status": "REJECT",
                "reason": "not exactly one original parent",
            }
            save(folder / "STATIC.json", result)
            summaries.append(result)
            continue
        parent = parents[1]
        diff = commands.run(
            prefix + ["diff-tree", "--no-commit-id", "--name-status", "-r", commit]
        ).decode()
        save(folder / "CHANGED_PATHS.txt", diff.encode())
        paths = sorted(
            line.split("\t")[-1]
            for line in diff.splitlines()
            if line.split("\t")[-1].endswith(".py")
        )
        tests = [path for path in paths if is_test(path)]
        source_paths = [path for path in paths if not is_test(path)]
        result = {
            "commit": commit,
            "parent": parent,
            "original_changed_test_paths": tests,
            "source_candidates": [],
        }
        for candidate_index, path in enumerate(source_paths):
            candidate = folder / f"source-{candidate_index:02d}"
            candidate.mkdir()
            try:
                old_blob = (
                    commands.run(prefix + ["rev-parse", parent + ":" + path])
                    .decode()
                    .strip()
                )
                new_blob = (
                    commands.run(prefix + ["rev-parse", commit + ":" + path])
                    .decode()
                    .strip()
                )
                before = commands.run(prefix + ["cat-file", "blob", old_blob])
                after = commands.run(prefix + ["cat-file", "blob", new_blob])
                save(candidate / "BEFORE.py", before)
                save(candidate / "AFTER.py", after)
                review = inspect_change(before, after)
                review.update(
                    path=path, before_git_blob=old_blob, after_git_blob=new_blob
                )
            except (RuntimeError, SyntaxError, UnicodeError, ValueError) as error:
                review = {
                    "path": path,
                    "status": "REJECT",
                    "reason": str(error),
                    "error_type": type(error).__name__,
                }
            save(candidate / "STATIC.json", review)
            result["source_candidates"].append(review)
        result["status"] = (
            "POTENTIALS_REQUIRE_ORDERED_QUALIFICATION"
            if any(
                row["status"] == "REQUIRES_QUALIFICATION"
                for row in result["source_candidates"]
            )
            else "STATIC_REJECT"
        )
        save(folder / "STATIC.json", result)
        summaries.append(result)
    save(
        output / "RESULT.json",
        {
            "status": "HISTORY_STATIC_REVIEW_COMPLETE",
            "HEAD": head,
            "canonical_repository": canonical_name,
            "commits": summaries,
            "qualified_tasks": 0,
            "new_model_calls": 0,
            "new_native_children": 0,
            "all_potentials_require_license_original_tests_context_sandbox_and_dedup_qualification": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "HISTORY_STATIC_REVIEW_COMPLETE",
                "output": str(output),
                "potential_count": sum(
                    row["status"] == "POTENTIALS_REQUIRE_ORDERED_QUALIFICATION"
                    for row in summaries
                ),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
