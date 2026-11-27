#!/usr/bin/env python3
"""Run a complete immutable Rust file-update owner against the actual HIA crate.

All source snapshots, Cargo captures, isolated dependency files, requests,
executables, logs and persistent fixtures are written to the external output dir.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from file_update_oracle import cargo
from file_update_oracle import corpus
from file_update_oracle import historical
from file_update_oracle import identity
from file_update_oracle import wire

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = Path(__file__).with_name("file_update_oracle")
# Sealed after the independent transport inventory check, before publication.
EXPECTED_CORPUS_SHA256 = "9a27f794cde40d26458db10a7e8373a3cf8b0b64d938f74941a4d54141707d52"


def verify(args, report):
    original = args.original_root.resolve(strict=True)
    library = args.library_dir.resolve(strict=True)
    output = identity.outside(args.output_dir, (ROOT, original))
    target = Path(os.environ["CARGO_TARGET_DIR"]).resolve(strict=True)
    identity.outside(target, (ROOT, original))
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "commands"
    logs.mkdir()
    commands = cargo.Commands(logs)
    report["output_dir"] = str(output)
    report["commands_file"] = str(logs / "commands.json")
    input_files = [Path(__file__), *sorted(SUPPORT.glob("*.py")), SUPPORT / "driver.rs"]
    report["test_inputs"] = {str(p.relative_to(ROOT)): identity.sha(p) for p in input_files}
    cases = corpus.corpus()
    digest = corpus.digest(cases)
    if digest != EXPECTED_CORPUS_SHA256:
        raise RuntimeError("the sealed complete input corpus changed")
    (output / "cases.json").write_bytes(corpus.canonical_bytes(cases))
    report["corpus"] = {"sha256": digest, "source_cases": corpus.CASE_COUNT,
        "executions_per_binary": corpus.EXECUTION_COUNT, "semantic_cases": corpus.SEMANTIC_COUNT,
        "separate_preconditions": corpus.PRECONDITION_COUNT,
        "predictions_are_static_until_observed": True}
    snapshot = output / "original"
    original_manifest = identity.snapshot(original, snapshot)
    report["original_inputs"] = original_manifest
    (output / "original-source-manifest.json").write_text(json.dumps(original_manifest, indent=2) + "\n")
    native_inputs = identity.native_inputs(ROOT, library)
    report["native_inputs"] = native_inputs
    rustc, real_cargo, env, compiler = cargo.compiler(args.rustc, commands, ROOT)
    env["CODEX_HIA_NATIVE_LIB_DIR"] = str(library)
    report["toolchain"] = compiler
    original_graph, _, dependency_baseline = historical.capture(
        original, identity.BASE, rustc, env, output / "historical-dependencies")
    report["dependency_baseline"] = dependency_baseline
    producer = identity.producer_inputs(ROOT, snapshot, original_manifest,
                                       dependency_baseline=dependency_baseline)
    report["producer"] = producer
    graph, packages, owner, dependencies, graph_receipt = cargo.metadata(real_cargo, ROOT, env, commands)
    del graph
    report["metadata"] = graph_receipt
    (output / "metadata-source-inputs.json").write_text(json.dumps(graph_receipt, indent=2) + "\n")
    default_capture = cargo.capture(real_cargo, ROOT, env, False, commands)
    default = cargo.admit(default_capture, packages, owner, dependencies, target,
                          output / "default-deps", native=False)
    native_capture = cargo.capture(real_cargo, ROOT, env, True, commands)
    native = cargo.admit(native_capture, packages, owner, dependencies, target,
                         output / "native-deps", native=True)
    for name, receipt in (("default", default), ("native", native)):
        (output / (name + "-dependency-manifest.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    binaries = cargo.build_drivers(rustc, snapshot, ROOT, SUPPORT / "driver.rs",
                                   original_graph, default, native, env, commands, output)
    report["original_tests"] = {"passed": 5, "skipped": 0,
        "scope": "The five unchanged file_update tests inside the complete original library test binary; not the entire crate suite."}
    binary_hashes = {name: identity.sha(path) for name, path in binaries.items()}
    report["binaries"] = {name: {"path": str(path), "sha256": binary_hashes[name]}
                          for name, path in binaries.items()}
    observed = output / "observations"
    observed.mkdir()
    results = []
    for case, mode, route in corpus.expand(cases):
        name = f"{case['id']}-mode{mode}-route{route}"
        directory = observed / name
        directory.mkdir()
        request, source = wire.encode(case, mode, route)
        (directory / "request.bin").write_bytes(request)
        decoded = wire.decode_request(request)
        expected = {"mode": mode, "route": route, "file_kind": case["file_kind"],
                    "source": source, "chunks": case["chunks"], "patch": case["patch"]}
        if decoded != expected:
            raise RuntimeError("the complete typed input changed during transport")
        item = {"case": case["id"], "mode": mode, "route": route,
                "precondition": case["precondition"],
                "request_bytes": len(request), "request_sha256": hashlib.sha256(request).hexdigest(),
                "original": {}, "native": {}, "matches": False}
        for kind, binary in binaries.items():
            try:
                item[kind] = wire.observe(binary, request, source, case, mode, route, directory / kind)
            except (OSError, KeyError, ValueError, RuntimeError) as error:
                item[kind] = {"valid": False, "error": f"{type(error).__name__}: {error}"}
        if item["original"].get("valid") and item["native"].get("valid"):
            if case["precondition"]:
                item["matches"] = item["original"]["outcome"] == item["native"]["outcome"] == "panic"
                item["post_panic_state_equivalence_required"] = False
            else:
                item["matches"] = all((directory / "original" / filename).read_bytes() ==
                                      (directory / "native" / filename).read_bytes()
                                      for filename in ("normalized.stdout", "normalized.stderr"))
                item["matches"] &= (item["original"]["independent_file_state"] ==
                                    item["native"]["independent_file_state"])
        results.append(item)
        (observed / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    report["actual"] = {
        "paired_process_inputs": len(results),
        "semantic_comparisons_passed": sum(r["matches"] and not r["precondition"] for r in results),
        "separate_preconditions_observed": sum(r["matches"] and r["precondition"] for r in results),
        "mismatches": [r["case"] for r in results if not r["matches"]],
    }
    if report["actual"] != {"paired_process_inputs": 159, "semantic_comparisons_passed": 157,
                             "separate_preconditions_observed": 2, "mismatches": []}:
        raise RuntimeError("the complete original/native public result matrix did not pass")
    for name, path in binaries.items():
        if identity.sha(path) != binary_hashes[name]:
            raise RuntimeError("an executed binary changed during observation")
    cargo.verify_graph(default)
    cargo.verify_graph(native)
    historical.verify(dependency_baseline)
    identity.verify_sources(snapshot, original_manifest)
    if identity.producer_inputs(ROOT, snapshot, original_manifest,
                               dependency_baseline=dependency_baseline) != producer:
        raise RuntimeError("the actual producing source changed")
    if identity.native_inputs(ROOT, library) != native_inputs:
        raise RuntimeError("the actual native source/archive changed")
    if identity.clean_identity(original)["commit"] != identity.BASE:
        raise RuntimeError("the original checkout changed")
    for package in graph_receipt["packages"].values():
        if identity.sha(package["manifest_path"]) != package["manifest_sha256"]:
            raise RuntimeError("a real graph manifest changed")
    for relative, digest in report["test_inputs"].items():
        if identity.sha(ROOT / relative) != digest:
            raise RuntimeError("a harness input changed during the gate")
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-root", required=True, type=Path)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report_path = identity.outside(args.report, (ROOT, args.original_root.resolve()))
    if report_path.exists():
        raise RuntimeError("refusing to replace an existing qualification report")
    report = {"schema": "codex.hia.native-file-update-caller.v2", "passed": False,
        "scope": "Complete pinned original crate with its actual historical dependencies and actual feature-selected production crate with current dependencies; real LOCAL_FS and full public results.",
        "normalization": "Only exact supplied per-process fixture-root bytes and the emitted actual Rust Debug spelling are replaced in path/diagnostic fields; all raw streams and independent post-exit file state are retained.",
        "original_private_planner_transcripts_observed": False,
        "unsafe_abi_qualified_by_this_report": False,
        "whole_product_qualification": False}
    try:
        verify(args, report)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": report["passed"], "actual": report.get("actual"), "report": str(report_path)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
