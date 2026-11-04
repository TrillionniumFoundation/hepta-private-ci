#!/usr/bin/env python3
"""Compile a bounded include-placement control; this is not a CLI build."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rustc = args.rustc.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(
        [str(rustc), "--version", "--verbose"],
        capture_output=True, text=True, check=True,
    ).stdout
    records = []
    outputs = {}
    with tempfile.TemporaryDirectory(prefix="cli-entrypoint-placement-") as temp:
        root = Path(temp)
        body = (
            'mod sibling;\n'
            'fn main() { sibling::check(); }\n'
            '#[cfg(test)] mod tests {\n'
            '    #[test] fn shared_module_is_visible() { super::sibling::check(); }\n'
            '}\n'
        )
        sources = {
            "sibling.rs": "pub fn check() {}\n",
            "bad_main.rs": '#![recursion_limit = "256"]\n\n' + body,
            "bad_hepta.rs": '#![recursion_limit = "256"]\n\ninclude!("bad_main.rs");\n',
            "main_shared.rs": body,
            "main.rs": '#![recursion_limit = "256"]\n\ninclude!("main_shared.rs");\n',
            "hepta.rs": '#![recursion_limit = "256"]\n\ninclude!("main_shared.rs");\n',
        }
        for name, content in sources.items():
            (root / name).write_text(content)
        cases = [("bad_hepta", False)] + [
            (name, test) for name in ("main", "hepta") for test in (False, True)
        ]
        for name, test in cases:
            label = name + ("-test" if test else "-bin")
            argv = [
                str(rustc), "--edition=2024", "--emit=metadata", "--crate-name", name,
                str(root / f"{name}.rs"), "-o", str(root / f"{label}.rmeta"),
            ]
            if test:
                argv.append("--test")
            result = subprocess.run(argv, cwd=root, capture_output=True, timeout=30)
            outputs[label] = {
                stream: getattr(result, stream).decode("utf-8")
                for stream in ("stdout", "stderr")
            }
            expected_failure = name == "bad_hepta"
            matched = (
                result.returncode != 0
                and b"an inner attribute is not permitted in this context" in result.stderr
            ) if expected_failure else result.returncode == 0
            records.append({
                "label": label, "argv": argv, "cwd": str(root),
                "exit_code": result.returncode,
                "expected_failure": expected_failure, "matched_expectation": matched,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            })
        receipt = {
            "schema": "cli-crate-entrypoint-placement-probe-v1",
            "scope": "Rust include-placement and sibling-module resolution only; no CLI dependency graph or business tests executed.",
            "rustc": {"path": str(rustc), "version": version,
                      "sha256": hashlib.sha256(rustc.read_bytes()).hexdigest()},
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "generated_sources": {
                name: {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
                for name, text in sources.items()
            },
            "cases": records,
            "all_expectations_met": all(record["matched_expectation"] for record in records),
            "full_cli_qualified": False,
        }
        (args.output / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (args.output / "OUTPUTS.json").write_text(json.dumps(outputs, indent=2) + "\n")
        if not receipt["all_expectations_met"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
