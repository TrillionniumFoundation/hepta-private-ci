#!/usr/bin/env python3
"""Run the real exec prompt decoder with native and default stream-parser code.

This focused consumer gate uses the production Rust modules and fully admitted
HIA archives. Full installed CLI and workspace qualification remain separate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
STREAM = ROOT / "codex-rs/utils/stream-parser/src"
PROMPT = ROOT / "codex-rs/exec/src/prompt_decode.rs"
MODULES = ("citation_stream_parser", "proposed_plan_parser", "utf8_stream", "inline_hidden_tag")


def run(command, report):
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    report["commands"].append({
        "command": command, "returncode": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout if command[0] != "nm" else {
            "sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            "bytes": len(result.stdout.encode()),
            "utf8_symbol_present": "codex_hia_utf8_stream" in result.stdout,
        }, "stderr": result.stderr,
    })
    if result.returncode:
        raise RuntimeError(f"command failed: {command[0]}: {result.stderr}")
    return result.stdout


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError("a real Rust compiler is required")
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / "network_host.so", ROOT / "hia/network_host.hepta",
                  args.build_profile, report)
    verified = {"full-native37": "full37_manifest_verified",
                "full-native38": "full38_manifest_verified"}[args.build_profile]
    if report["native_build"].get(verified) is not True:
        raise RuntimeError("the complete pinned native build was not admitted")
    for path in [*STREAM.glob("*.rs"), PROMPT, PROMPT.with_name("prompt_decode_tests.rs"),
                 Path(__file__).resolve()]:
        report["inputs"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    report["rustc"] = run([rustc, "--version", "--verbose"], report)
    with tempfile.TemporaryDirectory(prefix="codex-hia-prompt-caller-") as temporary:
        temporary = Path(temporary)
        source = temporary / "prompt_caller.rs"
        source.write_text(
            f"#[path = {json.dumps(str(PROMPT))}]\nmod prompt_decode;\n"
            "fn main() {\n"
            "    let mut bytes = Vec::new();\n"
            "    std::io::Read::read_to_end(&mut std::io::stdin(), &mut bytes).unwrap();\n"
            "    match prompt_decode::decode_prompt_bytes(&bytes) {\n"
            "        Ok(text) => std::io::Write::write_all(&mut std::io::stdout(), text.as_bytes()).unwrap(),\n"
            "        Err(error) => { eprintln!(\"{error}\"); std::process::exit(1); }\n"
            "    }\n}\n"
        )
        binaries = {}
        for variant in ("reference", "native"):
            library = temporary / f"libstream_{variant}.rlib"
            feature = ["--cfg", 'feature="hia-native"'] if variant == "native" else []
            run([rustc, "--edition=2024", "--crate-name", "codex_utils_stream_parser",
                 "--crate-type", "rlib", *feature, str(STREAM / "lib.rs"), "-o", str(library)], report)
            links = ["-L", f"native={directory}"] if variant == "native" else []
            if variant == "native":
                for module in MODULES:
                    links.extend(["-l", f"static=codex_hia_{module}"])
            common = [rustc, "--edition=2024", str(source),
                      "--extern", f"codex_utils_stream_parser={library}", *links]
            tests = temporary / f"prompt_tests_{variant}"
            run([*common, "--test", "-o", str(tests)], report)
            output = run([str(tests), "--test-threads=1"], report)
            match = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;", output)
            expected_tests = PROMPT.with_name("prompt_decode_tests.rs").read_text().count("#[test]")
            if match is None or int(match.group(1)) != expected_tests:
                raise RuntimeError("not all production decoder tests executed")
            report["production_unit_tests"][variant] = int(match.group(1))
            binary = temporary / f"prompt_{variant}"
            run([*common, "-o", str(binary)], report)
            symbols = run(["nm", "--defined-only", str(binary)], report)
            if ("codex_hia_utf8_stream" in symbols) != (variant == "native"):
                raise RuntimeError("consumer binary native UTF-8 symbol selection differs")
            binaries[variant] = binary
            report["binaries"][variant] = hashlib.sha256(binary.read_bytes()).hexdigest()
        cases = [
            ("empty", b"", b""),
            ("unicode", "é汉🦀\n".encode(), "é汉🦀\n".encode()),
            ("bom", "\ufeffé汉🦀\n".encode(), "é汉🦀\n".encode()),
            ("double_bom", "\ufeff\ufeffx".encode(), "\ufeffx".encode()),
            ("utf16_le", b"\xff\xfe\xe9\0\x3e\xd8\x80\xdd", "é🦀".encode()),
            ("utf16_be", b"\xfe\xff\0\xe9\xd8\x3e\xdd\x80", "é🦀".encode()),
            ("large_unicode", "é汉🦀\n".encode() * 110_000, "é汉🦀\n".encode() * 110_000),
        ]
        for name, raw, expected in cases:
            outputs = [subprocess.run([str(binaries[v])], input=raw, capture_output=True, timeout=30)
                       for v in ("reference", "native")]
            if any((r.returncode, r.stdout, r.stderr) != (0, expected, b"") for r in outputs):
                raise RuntimeError(f"literal prompt output differs: {name}")
            report["stdin_cases"].append({"name": name, "bytes": len(raw), "passed": True})
        for index, raw in enumerate([
            b"\xff", b"ok\xe2(\xa1", b"ok\xe2\x82x", b"ok\xf0\x90\x80x",
            b"\xef\xbb\xbfprompt\xf0\x90\x80", b"\xc3", b"ok\xe2\x82",
            b"\xff\xfea", b"\xfe\xff\xdc\0", b"\xff\xfe\0\0", b"\0\0\xfe\xff",
        ]):
            outputs = [subprocess.run([str(binaries[v])], input=raw, capture_output=True, timeout=30)
                       for v in ("reference", "native")]
            expected = outputs[0]
            actual = outputs[1]
            if (expected.returncode != 1 or expected.stdout or not expected.stderr
                    or (actual.returncode, actual.stdout, actual.stderr)
                    != (expected.returncode, expected.stdout, expected.stderr)):
                raise RuntimeError(f"invalid prompt error differs: {index}")
            report["stdin_cases"].append({"name": f"invalid_{index}", "bytes": len(raw),
                                          "error": actual.stderr.decode(), "passed": True})
    if not recheck_inputs(report):
        raise RuntimeError("bound source or native input changed during the caller run")
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--build-profile", choices=("full-native37", "full-native38"),
                        default="full-native37")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.prompt-decode-caller.v1", "passed": False,
              "commands": [], "production_unit_tests": {}, "stdin_cases": [], "binaries": {},
              "installed_cli_qualified": False, "whole_codex_rewritten": False}
    try:
        verify(args, report)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "unit_tests": report["production_unit_tests"],
                      "stdin_cases": len(report["stdin_cases"]), "error": report.get("error")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
