"""Run the repository formatter and export only AST-equivalent V5 source edits."""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parents[1]


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def syntax_identity(path):
    normalized = ast.dump(ast.parse(path.read_bytes()), include_attributes=False)
    return hashlib.sha256(normalized.encode()).hexdigest()


def main():
    source = sorted(
        set(PROJECT.glob("*.py"))
        | set((PROJECT / "v5").glob("*.py"))
        | set((PROJECT / "tests").glob("*.py"))
        | set((PROJECT / "maintenance").glob("*.py"))
        | set((PROJECT / "validation").glob("*.py"))
    )
    protected = sorted(
        path
        for directory in ("held", "legacy_v3")
        for path in (PROJECT / directory).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if not source or any(path.is_symlink() for path in source + protected):
        raise ValueError("missing source or linked input")
    before = {path.relative_to(PROJECT).as_posix(): identity(path) for path in source}
    syntax = {path.relative_to(PROJECT).as_posix(): syntax_identity(path) for path in source}
    immutable = {path.relative_to(PROJECT).as_posix(): identity(path) for path in protected}
    commands = [
        (["just", "fmt", "--base", "9616e81ec3f66d734c9f430801ec2f4c4e908adb"], REPOSITORY / "codex-rs"),
        (["uv", "run", "--frozen", "--project", "scripts", "ruff", "format", *[path.relative_to(REPOSITORY).as_posix() for path in source]], REPOSITORY),
        (["uv", "run", "--frozen", "--project", "scripts", "ruff", "check", *[path.relative_to(REPOSITORY).as_posix() for path in source]], REPOSITORY),
    ]
    records = []
    for command, working_directory in commands:
        process = subprocess.run(command, cwd=working_directory, capture_output=True, text=True)
        records.append({"command": command, "cwd": str(working_directory), "exit_code": process.returncode,
                        "stdout": process.stdout, "stderr": process.stderr})
        if process.returncode:
            print(json.dumps(records, indent=2))
            raise RuntimeError("repository formatting or scoped lint failed")
    after = {path.relative_to(PROJECT).as_posix(): identity(path) for path in source}
    for path in source:
        relative = path.relative_to(PROJECT).as_posix()
        if syntax_identity(path) != syntax[relative]:
            raise ValueError("formatter changed the abstract syntax tree: " + relative)
    for path in protected:
        relative = path.relative_to(PROJECT).as_posix()
        if identity(path) != immutable[relative]:
            raise ValueError("formatter touched sealed or byte-identical inputs: " + relative)
    report = {"schema": "hepta.memory.v5.final-format.v1", "source_commit_before_format": os.environ["GITHUB_SHA"],
              "commands": records, "before": before, "after": after, "ast_sha256": syntax,
              "all_source_ast_equal": True, "protected_files": immutable, "protected_unchanged": True,
              "unit_tests_run_by_this_job": False,
              "formatter_inputs": {name: identity(REPOSITORY / name) for name in
                                   ("justfile", "scripts/format.py", "scripts/just-shell.py", "scripts/pyproject.toml", "scripts/uv.lock")}}
    output = REPOSITORY / "v5-format-output"
    output.mkdir(exist_ok=False)
    report_file = output / "FORMAT.json"
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    with tarfile.open(output / "formatted-source.tar.gz", "w:gz") as archive:
        for path in source:
            archive.add(path, arcname=path.relative_to(PROJECT).as_posix(), recursive=False)
    print(json.dumps({"source_files": len(source), "changed_files": sum(before[name] != after[name] for name in before),
                      "protected_files": len(protected), "ast_equal": True, "report": identity(report_file)}, sort_keys=True))


if __name__ == "__main__":
    main()
