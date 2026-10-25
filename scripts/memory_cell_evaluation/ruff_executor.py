"""One exposed Ruff incident: source-only contract and candidate-file executor."""

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tokenize

from bounded_process import digest, run, save

HERE = Path(__file__).resolve().parent
CONTRACT_SHA256 = "df2507680813e86d08b94877e6985476927b2bb76d5ec4bdb083ad5b3e86a8dc"


def contract():
    raw = (HERE / "ruff_contract.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONTRACT_SHA256:
        raise ValueError("contract hash drift")
    return json.loads(raw)


def inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"not a regular fixture directory: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"fixture symlink or escape: {path}")
        if path.is_file():
            result[str(path.relative_to(root))] = digest(path)
        elif not path.is_dir():
            raise ValueError(f"nonregular fixture entry: {path}")
    return result


def unique_object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON keys")
    return value


def candidate_content(raw, spec, original):
    request = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    if (
        set(request) != {"schema", "files"}
        or request["schema"] != "hepta.memory-cell.implementation-candidate.v1"
    ):
        raise ValueError("candidate schema")
    files = request["files"]
    if (
        not isinstance(files, list)
        or len(files) != 1
        or set(files[0]) != {"path", "content"}
    ):
        raise ValueError("exactly one implementation replacement required")
    row = files[0]
    if row["path"] != spec["target"] or not isinstance(row["content"], str):
        raise ValueError("out-of-scope candidate path/content")
    content = row["content"].encode("utf-8")
    if len(content) > spec["limits"]["content_bytes"] or b"\0" in content:
        raise ValueError("candidate content limit")

    def suppressions(data):
        return Counter(
            t.string
            for t in tokenize.generate_tokens(io.StringIO(data.decode()).readline)
            if t.type == tokenize.COMMENT
            and re.search(r"noqa\b|ruff\s*:", t.string, re.I)
        )

    if suppressions(content) - suppressions(original):
        raise ValueError("new lint suppression comment")
    return content


def semantic_pass(report, required):
    expected = Counter(required)
    return (
        report.get("tests_run") == len(required)
        and report.get("unittest_success") is True
        and all(
            Counter(report.get(key, [])) == expected
            for key in ("discovered", "started", "completed")
        )
        and Counter(row["id"] for row in report.get("outcomes", [])) == expected
        and all(row.get("status") == "success" for row in report.get("outcomes", []))
    )


def evaluate(fixture, candidate, output, ruff, python):
    """All successful admission is local engineering evidence, not attestation."""
    fixture, candidate, output = map(Path, (fixture, candidate, output))
    fixture, candidate = fixture.absolute(), candidate.absolute()
    output = output.absolute()
    if output.resolve().is_relative_to(
        fixture.resolve()
    ) or fixture.resolve().is_relative_to(output.resolve()):
        raise ValueError("output overlaps original fixture")
    output.mkdir(exist_ok=False)
    result = {
        "schema": "hepta.memory-cell.ruff-evaluation.v1",
        "accepted": False,
        "status": "rejected",
        "processes": [],
        "scope": "exposed historical development; trusted candidate",
    }
    expected = {}
    try:
        spec = contract()
        expected[HERE] = inventory(HERE)
        save(
            output / "request.json",
            {
                "fixture": str(fixture),
                "candidate": str(candidate),
                "contract_sha256": CONTRACT_SHA256,
                "executor_sources": expected[HERE],
            },
        )
        if sys.platform != "linux":
            raise ValueError("Linux-only executor")
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("candidate must be regular file")
        with candidate.open("rb") as stream:
            raw = stream.read(spec["limits"]["candidate_bytes"] + 1)
        (output / "candidate.raw").write_bytes(raw)
        if len(raw) > spec["limits"]["candidate_bytes"]:
            raise ValueError("candidate request limit; retained bounded prefix")
        original = inventory(fixture)
        save(output / "original-before.json", original)
        if original != spec["files"]:
            raise ValueError("original 17-file inventory drift")
        expected[fixture] = original
        source = {name: (fixture / name).read_bytes() for name in spec["files"]}
        if any(
            {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            != original[name]
            for name, data in source.items()
        ):
            raise ValueError("source changed while reading")
        content = candidate_content(raw, spec, source[spec["target"]])
        tool_paths = {
            "ruff": str(Path(ruff).resolve()),
            "python": str(Path(python).resolve()),
        }
        if any(digest(tool_paths[name]) != spec["tools"][name] for name in tool_paths):
            raise ValueError("executable pin mismatch")
        baseline, workspace, judge = (
            output / name for name in ("baseline", "workspace", "judge")
        )
        for destination in (baseline, workspace):
            for name, data in source.items():
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    content
                    if destination == workspace and name == spec["target"]
                    else data
                )
            expected[destination] = inventory(destination)
        judge.mkdir()
        for name, data in source.items():
            if Path(name).name.startswith("test_"):
                (judge / Path(name).name).write_bytes(data)
        expected[judge] = inventory(judge)
        save(
            output / "expected-inventories.json",
            {str(p): v for p, v in expected.items()},
        )
        argv = [tool_paths["ruff"], *spec["lint_args"], spec["target"]]
        first = run(argv, baseline, output / "baseline-lint", spec["limits"])
        result["processes"].append(first)
        diagnostics = json.loads((output / "baseline-lint/stdout").read_text())
        result["baseline_codes"] = sorted(row["code"] for row in diagnostics)
        if (
            first["returncode"] != 1
            or first["timeout"]
            or result["baseline_codes"] != spec["baseline_codes"]
        ):
            raise ValueError("baseline did not reproduce exactly F401/E731")
        lint = run(argv, workspace, output / "candidate-lint", spec["limits"])
        result["processes"].append(lint)
        if (
            lint["returncode"] != 0
            or lint["timeout"]
            or json.loads((output / "candidate-lint/stdout").read_text()) != []
        ):
            result["status"] = (
                "lint_failed" if lint["returncode"] == 1 else "execution_failed"
            )
        else:
            semantic = run(
                [
                    tool_paths["python"],
                    "-I",
                    "-B",
                    str(HERE / "ruff_judge.py"),
                    str(workspace / Path(spec["target"]).parent),
                    str(judge),
                    str(output / "semantic.json"),
                ],
                workspace,
                output / "semantic-process",
                spec["limits"],
            )
            result["processes"].append(semantic)
            report = json.loads((output / "semantic.json").read_text())
            result["semantic"] = report
            result["accepted"] = (
                semantic["returncode"] == 0
                and not semantic["timeout"]
                and semantic_pass(report, spec["test_ids"])
            )
            result["status"] = "passed" if result["accepted"] else "semantic_failed"
    except Exception as error:
        result.update(
            accepted=False, status="rejected", error=f"{type(error).__name__}: {error}"
        )
    finally:
        observed = {}
        for path, wanted in expected.items():
            try:
                observed[str(path)] = inventory(path)
                if observed[str(path)] != wanted:
                    raise ValueError("post-execution inventory drift")
            except Exception as error:
                result.update(
                    accepted=False, status="inventory_failed", error=f"{path}: {error}"
                )
        save(output / "observed-inventories.json", observed)
        try:
            result["retained_files"] = inventory(output)
        except Exception as error:
            result.update(
                accepted=False,
                status="inventory_failed",
                retained_inventory_error=str(error),
            )
        save(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe")
    execute = commands.add_parser("evaluate")
    for name in ("fixture", "candidate", "output", "ruff", "python"):
        execute.add_argument(f"--{name}", required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "describe":
        print(json.dumps(contract(), indent=2, sort_keys=True))
        return 0
    result = evaluate(**args)
    print(json.dumps({key: result[key] for key in ("accepted", "status")}))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
