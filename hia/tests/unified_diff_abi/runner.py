"""Run every retained component gate against the actual canonical native entry."""
import argparse
import datetime
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time
import traceback
import types

from . import admission, corpus_cases, frontend_cases, original, raw_cases, selector_cases
from .transport import Native

HERE = Path(__file__).resolve().parent
SCHEMA = "codex.hia.unified-diff-canonical-component-abi.v1"


def create(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=HERE.parents[2])
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--rustc", type=Path, default=Path(shutil.which("rustc") or "rustc"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.repo = args.repo.resolve(strict=True)
    args.library_dir = args.library_dir.resolve(strict=True)
    args.rustc = args.rustc.resolve(strict=True)
    args.report = args.report.resolve()
    args.output_dir = (args.output_dir or args.report.with_name(args.report.stem + ".work")).resolve()
    roots = (args.repo, args.library_dir, HERE.parent.parent.parent)
    admission.require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    admission.require(args.timeout > 0, "timeout must be positive")
    admission.require(not args.report.is_relative_to(args.output_dir),
                      "the final report must be outside the generated work directory")
    admission.require(not args.output_dir.exists() and not args.report.exists(),
                      "qualification outputs must be new")
    for output in (args.output_dir, args.report):
        admission.require(not any(output == root or output.is_relative_to(root) for root in roots),
                          "qualification outputs must be outside all source/artifact directories")
    return args


def native(args):
    return Native(
        args.library_dir / "libcodex_hia_unified_diff.so", "codex_hia_unified_diff",
        args.repo / "hia/unified_diff.hepta", args.library_dir / "build.json",
        args.repo / "hia/unified_diff_buffer_contract.json", False,
    )


def worker(args):
    args.output_dir.mkdir(parents=True)
    report = {
        "schema": SCHEMA, "passed": False, "tests_skipped": 0,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Actual canonical HIA component versus fresh complete Similar 2.7.0 references; raw memory boundaries, both original corpora, frontend collisions and the complete word matrix.",
        "public_fs_chunk_adapter_qualified": False,
        "production_compile_profile_binding_qualified": False,
        "mixed_codex_production_configuration_qualified": False,
        "cargo_executed": False, "whole_product_qualified": False,
        "whole_product_performance_qualified": False,
    }
    partial = args.report.with_name(args.report.stem + ".worker.json")
    active = None
    try:
        source_inputs = [
            admission.binding(path) for path in sorted(HERE.rglob("*")) if path.is_file()
        ] + [admission.binding(Path(sys.argv[0]).resolve())]
        admitted = native(args)
        report["native_admission"] = admitted.admission_scope
        report["native_bindings"] = admitted.bindings
        report["qualification_sources"] = source_inputs
        report["canonical_module_count"] = len(json.loads(
            (args.library_dir / "build.json").read_text())["modules"])
        report["original_reference"] = {"passed": False}
        references = original.prepare(args.output_dir / "reference", args.rustc,
                                      report["original_reference"])
        reference_bindings = {key: admission.binding(path) for key, path in references.items()}
        report["components"] = {}
        configurations = (
            ("original", corpus_cases, [references["adversarial"], references["baseline"]], [0, 1, 2, 3]),
            ("raw-abi", raw_cases, [references["adversarial"]], [0, 1]),
            ("frontend", frontend_cases, [references["adversarial"]], [0, 1, 2, 3]),
            ("word-boundary", selector_cases, [references["adversarial"]], [0, 1, 2, 3]),
        )
        expected_calls = {"original": 109152, "raw-abi": 2490, "frontend": 3136,
                          "word-boundary": 408080}
        corpus_cases.KNOWN = {
            reference_bindings[name]["sha256"]: original.CORPORA[name] for name in original.CORPORA
        }
        raw_cases.ORIGINAL_REPORT_SHA = reference_bindings["adversarial"]["sha256"]
        for name, module, reports, policies in configurations:
            active = native(args)
            active.trace_path = args.output_dir / (name + ".calls.jsonl")
            subreport = {"schema": "codex.hia.unified-diff-canonical-" + name + ".v1",
                         "passed": False, "tests_skipped": 0}
            component_args = types.SimpleNamespace(
                oracle_report=reports, policy=policies, development=False,
                report=args.output_dir / (name + ".json"), source=args.repo / "hia/unified_diff.hepta",
                original_report_sha=reference_bindings["adversarial"]["sha256"],
            )
            try:
                module.verify(component_args, active, subreport)
                counts = dict(active.counts)
                admission.require(counts["native_calls"] == expected_calls[name],
                                  "the retained complete call inventory changed: " + name)
                if name == "raw-abi":
                    admission.require(counts["error_no_write_cases"] == 1082 and
                                      subreport["concurrent_complete_pairs"] == 512 and
                                      subreport["additional_original_cases"] == 48,
                                      "the complete raw ABI gate was reduced")
                elif name == "original":
                    admission.require(subreport["original_case_count"] == 6758 and
                                      subreport["actual_native_plan_comparisons"] == 54064 and
                                      subreport["additional_concurrent_pairs"] == 512,
                                      "both full original corpora and four policies are required")
                elif name == "frontend":
                    admission.require(subreport["case_count"] == 180 and
                                      subreport["native_plan_comparisons"] == 1440 and
                                      subreport["concurrent_pairs"] == 128,
                                      "the full frontend matrix was reduced")
                else:
                    admission.require(subreport["case_count"] == 25489 and
                                      subreport["native_plan_comparisons"] == 203912 and
                                      subreport["concurrent_pairs"] == 128,
                                      "the complete word-boundary matrix was reduced")
                subreport["source_and_artifact_unchanged"] = active.unchanged()
                subreport["passed"] = True
            except Exception:
                subreport["exception"] = traceback.format_exc()
                raise
            finally:
                subreport["counts"] = dict(active.counts)
                subreport["last_call"] = active.last_case
                if active.trace_path.exists():
                    subreport["call_trace"] = admission.binding(active.trace_path)
                create(component_args.report, subreport)
                report["components"][name] = {
                    "passed": subreport["passed"], "report": admission.binding(component_args.report),
                    "counts": dict(active.counts),
                }
        for name, path in references.items():
            admission.validate_binding(reference_bindings[name])
            original.validate_original_corpus(path)
        for item in source_inputs:
            admission.validate_binding(item)
        report["source_and_artifact_unchanged"] = admitted.unchanged()
        report["native_calls"] = sum(item["counts"]["native_calls"]
                                     for item in report["components"].values())
        admission.require(report["native_calls"] == 522858, "the full gate inventory changed")
        report["passed"] = True
    except Exception:
        report["exception"] = traceback.format_exc()
    if active is not None:
        report["last_native_call"] = active.last_case
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    create(partial, report)
    print(json.dumps({"passed": report["passed"], "native_calls": report.get("native_calls"),
                      "report": str(partial)}), flush=True)
    return 0 if report["passed"] else 1


def main():
    args = arguments()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    if args.worker:
        return worker(args)
    partial = args.report.with_name(args.report.stem + ".worker.json")
    stdout, stderr = args.report.with_suffix(args.report.suffix + ".stdout"), args.report.with_suffix(args.report.suffix + ".stderr")
    admission.require(not any(path.exists() for path in (partial, stdout, stderr)),
                      "earlier qualification evidence must not be replaced")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-B", str(Path(sys.argv[0]).resolve()), *sys.argv[1:], "--worker"]
    start = time.monotonic()
    timed_out = False
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = subprocess.Popen(argv, stdout=out, stderr=err, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
    report = json.loads(partial.read_text()) if partial.exists() else {
        "schema": SCHEMA, "passed": False, "tests_skipped": 0,
        "exception": "Worker did not publish a result; inspect its real exit status and preserved call traces.",
        "whole_product_qualified": False,
    }
    report["worker_process"] = {
        "argv": argv, "returncode": code, "signal": -code if code < 0 else None,
        "timed_out": timed_out, "seconds": time.monotonic() - start,
        "stdout": admission.binding(stdout), "stderr": admission.binding(stderr),
    }
    if partial.exists():
        report["worker_report"] = admission.binding(partial)
    report["passed"] = report.get("passed") is True and code == 0 and not timed_out
    create(args.report, report)
    print(json.dumps({"passed": report["passed"], "native_calls": report.get("native_calls"),
                      "report": admission.binding(args.report),
                      "worker_returncode": code, "worker_signal": report["worker_process"]["signal"]}))
    return 0 if report["passed"] else 1
