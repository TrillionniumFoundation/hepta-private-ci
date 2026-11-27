#!/usr/bin/env python3
"""Compare the complete default and native template crates, without copying a parser."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--harness", type=Path)
    args = parser.parse_args()
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError("a real Rust oracle compiler is required")
    root = Path(__file__).resolve().parents[2]
    source = root / "codex-rs/utils/template/src/lib.rs"
    adapter = source.with_name("hia_native_parse.rs")
    hia = root / "hia/template_parse.hepta"
    harness = args.harness.resolve() if args.harness else Path(__file__).with_name("native_template_parser.rs")
    archive = args.library_dir.resolve() / "libcodex_hia_template_parse.a"
    report = {
        "status": "running", "source_sha256": digest(source),
        "adapter_sha256": digest(adapter), "hia_sha256": digest(hia),
        "archive_sha256": digest(archive), "harness_sha256": digest(harness),
        "render_archive_sha256": digest(archive.with_name("libcodex_hia_template_render.a")),
        "render_hia_sha256": digest(root / "hia/template_render.hepta"),
        "render_adapter_sha256": digest(source.with_name("hia_native_render.rs")),
        "render_contract_sha256": digest(root / "hia/template_render_buffer_contract.json"),
        "parse_contract_sha256": digest(root / "hia/template_parse_buffer_contract.json"),
        "index_archive_sha256": digest(archive.with_name("libcodex_hia_template_index.a")),
        "index_hia_sha256": digest(root / "hia/template_index.hepta"),
        "index_adapter_sha256": digest(source.with_name("hia_native_index.rs")),
        "owner_sources_sha256": {
            path.name: digest(path) for path in sorted(source.parent.glob("*.rs"))
        },
        "oracle": "complete production lib.rs, default feature; no copied parser",
        "commands": [],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="codex-template-oracle-") as temporary:
            work = Path(temporary)
            commands = [
                [rustc, "--edition=2024", "--crate-type=rlib", "--crate-name=template_reference",
                 "-C", "opt-level=1", str(source), "-o", str(work / "libreference.rlib")],
                [rustc, "--edition=2024", "--crate-type=rlib", "--crate-name=template_native",
                 "-C", "opt-level=1", "--cfg", 'feature="hia-native"', str(source),
                 "-L", f"native={archive.parent}", "-l", "static=codex_hia_template_parse",
                 "-l", "static=codex_hia_template_render",
                 "-l", "static=codex_hia_template_index",
                 "-o", str(work / "libnative.rlib")],
                [rustc, "--edition=2024", "--test", "-C", "opt-level=1", str(harness),
                 "--extern", f"template_reference={work / 'libreference.rlib'}",
                 "--extern", f"template_native={work / 'libnative.rlib'}",
                 "-L", f"native={archive.parent}", "-o", str(work / "comparison")],
                [str(work / "comparison"), "--nocapture", "--test-threads=1"],
            ]
            for command in commands:
                result = subprocess.run(command, capture_output=True, text=True, timeout=300)
                report["commands"].append({"argv": command, "exit_code": result.returncode,
                                           "stdout": result.stdout, "stderr": result.stderr})
                if result.returncode:
                    raise RuntimeError(f"template differential command failed: {result.stderr}")
            symbols = subprocess.run(["nm", "--defined-only", str(work / "comparison")],
                                     capture_output=True, text=True, check=True, timeout=30).stdout
            for symbol in ("codex_hia_template_parse", "codex_hia_template_render",
                           "codex_hia_template_index"):
                if not re.search(r"\bT " + symbol + "$", symbols, re.MULTILINE):
                    raise RuntimeError(f"test executable lacks native symbol: {symbol}")
            output = report["commands"][-1]["stdout"]
            report["parse_cases"] = sum(map(int, re.findall(r"parse_cases=(\d+)", output)))
            report["render_cases"] = sum(map(int, re.findall(r"render_cases=(\d+)", output)))
            report["placeholder_cases"] = sum(map(int, re.findall(r"placeholder_cases=(\d+)", output)))
            report["test_binary_sha256"] = digest(work / "comparison")
            report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "parse_cases", "render_cases", "placeholder_cases")}))


if __name__ == "__main__":
    main()
