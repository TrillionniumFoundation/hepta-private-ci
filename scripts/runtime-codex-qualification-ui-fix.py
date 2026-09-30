#!/usr/bin/env python3
"""Make runtime.codex qualification failures explicit in GitHub UI and receipts.

The command wrapper intentionally continues after a failed command so one run
can retain the complete matrix. This fix preserves that behavior while emitting
an error annotation for every failed command, appending a compact command table
to the job summary, and publishing explicit test/lint/format/source-closure
booleans in the signed receipt.

This construction helper is removed from the immutable ordinary-source
candidate after applying its changes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/runtime-codex-qualification.py"


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one source block")
        return text.replace(old, new, 1)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy and migrated blocks are absent")


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    old = '''def atomic_append_jsonl(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_bytes(value) + b"\\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def run_command(args: argparse.Namespace) -> int:
'''
    new = '''def atomic_append_jsonl(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_bytes(value) + b"\\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def github_command_escape(value: object) -> str:
    return (
        str(value)
        .replace("%", "%25")
        .replace("\\r", "%0D")
        .replace("\\n", "%0A")
    )


def append_job_summary(lines: list[str]) -> None:
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destination:
        return
    path = pathlib.Path(destination)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\\n".join(lines) + "\\n")
        handle.flush()
        os.fsync(handle.fileno())


def command_passed(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("outcome") == "passed"
        and record.get("sourceStable") is True
    )


def run_command(args: argparse.Namespace) -> int:
'''
    text = replace_once(text, old, new, "def github_command_escape")

    old = '''    atomic_append_jsonl(results, record)
    print(json.dumps(record, indent=2, sort_keys=True))
    # Continue the matrix so the receipt records every failure. `gate` decides.
    return 0
'''
    new = '''    atomic_append_jsonl(results, record)
    print(json.dumps(record, indent=2, sort_keys=True))
    if process.returncode != 0:
        print(
            "::error title=runtime.codex qualification::"
            f"{github_command_escape(args.name)} failed with exit code "
            f"{process.returncode}; retained log: {github_command_escape(log_path)}"
        )
    append_job_summary(
        [
            "### runtime.codex command result",
            "",
            "| Command | Required | Outcome | Exit | Source stable | Duration | Log |",
            "|---|---:|---|---:|---:|---:|---|",
            "| "
            f"`{args.name}` | {'yes' if not args.optional else 'no'} | "
            f"**{record['outcome']}** | {process.returncode} | "
            f"{'yes' if record['sourceStable'] else 'no'} | "
            f"{record['durationMs']} ms | `{log_path}` |",
        ]
    )
    # Continue the matrix so the receipt records every failure. `gate` decides.
    return 0
'''
    text = replace_once(text, old, new, "### runtime.codex command result")

    old = '''    required = [command for command in commands if command.get("required")]
    required_pass = bool(required) and all(
        command.get("outcome") == "passed" for command in required
    )

    head = git("rev-parse", "HEAD")
'''
    new = '''    required = [command for command in commands if command.get("required")]
    required_pass = bool(required) and all(command_passed(command) for command in required)
    commands_by_name = {
        str(command.get("name")): command
        for command in commands
        if command.get("name") is not None
    }
    format_pass = command_passed(commands_by_name.get("format"))
    lint_pass = command_passed(commands_by_name.get("strict-lint"))
    test_names = sorted(
        name
        for name in commands_by_name
        if name
        not in {
            "lane-b-truth",
            "receipt-helper",
            "format",
            "compile",
            "strict-lint",
        }
    )
    tests_pass = bool(test_names) and all(
        command_passed(commands_by_name[name]) for name in test_names
    )

    head = git("rev-parse", "HEAD")
'''
    text = replace_once(text, old, new, "commands_by_name =")

    old = '''        "qualification": {
            "qualified": qualified,
            "failureReasons": failures,
        },
        "candidate": candidate,
'''
    new = '''        "qualification": {
            "qualified": qualified,
            "testsPassed": tests_pass,
            "lintPassed": lint_pass,
            "formatPassed": format_pass,
            "sourceClosurePassed": source_closure_eligible,
            "failureReasons": failures,
        },
        "candidate": candidate,
'''
    text = replace_once(text, old, new, '"testsPassed": tests_pass')

    old = '''    receipt_path = output_dir / "runtime-codex-qualification-receipt.json"
    receipt_path.write_bytes(canonical_bytes(payload))
'''
    new = '''    append_job_summary(
        [
            "### runtime.codex qualification status",
            "",
            "| Gate | Result |",
            "|---|---:|",
            f"| testsPassed | **{str(tests_pass).lower()}** |",
            f"| lintPassed | **{str(lint_pass).lower()}** |",
            f"| formatPassed | **{str(format_pass).lower()}** |",
            f"| sourceClosurePassed | **{str(source_closure_eligible).lower()}** |",
            f"| qualified | **{str(qualified).lower()}** |",
            "",
            "Failure reasons: "
            + (", ".join(failures) if failures else "none"),
        ]
    )
    receipt_path = output_dir / "runtime-codex-qualification-receipt.json"
    receipt_path.write_bytes(canonical_bytes(payload))
'''
    text = replace_once(text, old, new, "### runtime.codex qualification status")

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
