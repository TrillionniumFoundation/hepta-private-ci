#!/usr/bin/env python3
"""Qualify complete original/current patch effects with real Cargo dependencies.

Every generated source snapshot, dependency stage, executable, request, command
log and fixture is written to the fresh external work directory.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_transport(producer):
    path = producer / "hia/tests/patch_effects_oracle/transport.py"
    specification = importlib.util.spec_from_file_location(
        "patch_effects_actual_transport_gate", path)
    if specification is None or specification.loader is None:
        raise RuntimeError("the actual production transport regression helper is absent")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module, path


def verify(args, report):
    producer = args.producer.resolve(strict=True)
    original = args.original_root.resolve(strict=True)
    library = args.library_dir.resolve(strict=True)
    sys.path.insert(0, str(producer / "hia/tests"))
    from file_update_oracle import cargo, identity
    from patch_effects_oracle import admission, observations

    require = admission.require
    require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    require(Path(cargo.__file__).resolve() ==
            producer / "hia/tests/file_update_oracle/cargo.py",
            "shared Cargo admission helper is not from the actual producer")
    require(Path(identity.__file__).resolve() ==
            producer / "hia/tests/file_update_oracle/identity.py",
            "shared source admission helper is not from the actual producer")
    support = Path(admission.__file__).resolve().parent
    require(Path(observations.__file__).resolve().parent == support,
            "qualification helper package is mixed")
    roots = (producer, original, support.parent, library)
    work = identity.outside(args.work_dir, roots)
    report_path = identity.outside(args.report, roots)
    require(not report_path.exists(), "refusing to replace an existing qualification report")
    observations.safe_fixture_root(work)
    target = Path(os.environ["CARGO_TARGET_DIR"]).resolve(strict=True)
    identity.outside(target, (producer, original))
    require(not work.exists(), "qualification work directory must be new")
    work.mkdir(parents=True)
    logs = work / "commands"
    logs.mkdir()
    commands = cargo.Commands(logs)
    transport, transport_path = load_transport(producer)
    inputs = {
        Path(__file__).resolve(),
        *support.glob("*.py"), support / "driver.rs", support / "observed_fs.rs",
        Path(cargo.__file__).resolve(), Path(identity.__file__).resolve(),
        transport_path, transport_path.with_name("transport_error_driver.rs"),
    }
    input_hashes = {str(path): identity.sha(path) for path in sorted(inputs)}
    for name, digest in admission.OBSERVER_HASHES.items():
        require(identity.sha(support / name) == digest,
                "the reviewed forward-only public observer changed: " + name)
    report.update(work_dir=str(work), commands_file=str(logs / "commands.json"),
                  harness_inputs=input_hashes)

    original_identity = identity.clean_identity(original)
    snapshot = work / "original"
    original_manifest = identity.snapshot(original, snapshot)
    admission.original_lib(snapshot, original_manifest)
    write_json(work / "original-source-manifest.json", original_manifest)
    producing = identity.producer_inputs(producer, snapshot, original_manifest, separate_lock=True)
    producing["complete_lib_inverse"] = admission.recover_lib(producer)
    native_binding = admission.native_inputs(producer, library)
    report.update(original_inputs=original_manifest, producer=producing,
                  native_inputs=native_binding)

    rustc, real_cargo, env, compiler = cargo.compiler(args.rustc, commands, producer)
    env.update(CODEX_HIA_NATIVE_LIB_DIR=str(library), PYTHONDONTWRITEBYTECODE="1",
               RUST_BACKTRACE="0")
    report["toolchain"] = compiler
    report["effective_build_environment"] = {
        name: env.get(name) for name in (
            "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_JOBS",
            "CARGO_TARGET_DIR", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG",
            "BINDGEN_EXTRA_CLANG_ARGS", "LIBCLANG_PATH", "TMPDIR",
        )
    }
    graphs, metadata = cargo.capture_three_graphs(
        real_cargo, producer, original, env, commands, work, target)
    report["cargo_metadata_inputs"] = metadata["default"]
    report["three_way_cargo_metadata"] = metadata
    report["three_way_cargo_graphs"] = {side: graph["lane"] for side, graph in graphs.items()}
    write_json(work / "metadata-source-inputs.json", metadata["default"])
    graph_manifests = {}
    for side, graph in graphs.items():
        graph_path = work / (side + "-dependency-manifest.json")
        graph_manifests[side] = {"path": str(graph_path), "bytes": graph_path.stat().st_size,
                                 "sha256": identity.sha(graph_path)}
    report["actual_cargo_graph_manifests"] = graph_manifests
    report["actual_cargo_builds"] = {
        side: {"successful_build_finished": graph["actual_cargo_build_succeeded"],
               "artifact_jsonl_sha256": graph["artifact_jsonl_sha256"],
               "actual_library_units": len(graph["units"]),
               "actual_library_files": len(graph["files"]),
               "owner_unit": graph["direct"]["codex_apply_patch"]["unit"]}
        for side, graph in graphs.items()
    }
    serde = {side: admission.shared_serde(graph, metadata[side]["packages"])
             for side, graph in graphs.items()}
    report["actual_serde_identity"] = serde
    write_json(work / "actual-serde-identity.json", serde)
    binaries, owner_receipts = admission.build_owners(
        rustc, producer, snapshot, support, graphs["original"], graphs["default"],
        graphs["native"], serde, env, commands, work)
    report.update(owner_receipts)
    public = observations.run(binaries, producer, env, work / "public-observations")
    report["public_observations"] = {
        key: value for key, value in public.items() if key != "cases"
    }
    report["public_observations"]["report_path"] = str(
        work / "public-observations/report.json")
    require(public["passed"] and public["semantic_pairs"] == 360 and
            public["actual_processes"] == 720 and public["skipped"] == 0 and
            public["mismatches"] == 0, "the complete natural public matrix did not pass")
    transport_receipt = transport.verify(
        rustc, graphs["native"], env, commands, library, producer, work / "native-transport")
    require(transport_receipt["passed"] and
            transport_receipt["actual_processes"] == 14 and
            transport_receipt["planner_call_attempts"] == 95 and
            transport_receipt["real_native_forwarded_calls"] == 88,
            "the existing native transport regression gate did not pass")
    report["native_transport_error_regression"] = transport_receipt
    write_json(work / "native-transport-report.json", transport_receipt)

    for side, binary in binaries.items():
        require(identity.sha(binary) == report["binaries"][side]["sha256"],
                "an executed public binary changed")
    for key in ("original_library", "original_tests_binary"):
        require(identity.sha(Path(report[key]["path"])) == report[key]["sha256"],
                "an executed/linked original artifact changed")
    for side, graph in graphs.items():
        cargo.verify_graph(graph)
        admission.verify_fingerprints(serde[side])
        manifest_record = graph_manifests[side]
        manifest_path = Path(manifest_record["path"])
        require(identity.sha(manifest_path) == manifest_record["sha256"] and
                manifest_path.stat().st_size == manifest_record["bytes"],
                "an admitted actual Cargo graph manifest changed")
    identity.verify_sources(snapshot, original_manifest)
    final_producer = identity.producer_inputs(producer, snapshot, original_manifest, separate_lock=True)
    final_producer["complete_lib_inverse"] = admission.recover_lib(producer)
    require(final_producer == producing, "the actual producing source changed")
    require(admission.native_inputs(producer, library) == native_binding,
            "native source/archive/build binding changed")
    require(identity.clean_identity(original) == original_identity,
            "the separate immutable original checkout changed")
    cargo.verify_three_graphs(graphs, metadata, original, producer)
    for side, receipt in metadata.items():
        require(json.loads((work / (side + "-metadata-source-inputs.json")).read_text()) == receipt,
                "an actual Cargo lane metadata receipt changed")
    for path, digest in input_hashes.items():
        require(identity.sha(path) == digest, "a qualification source input changed")
    for side, graph in graphs.items():
        label = "cargo-metadata" if side == "default" else "cargo-" + side + "-metadata"
        captured = [record for record in commands.records if record["label"] == label]
        require(len(captured) == 1 and captured[0]["returncode"] == 0
                and identity.sha(captured[0]["stdout"]) == metadata[side]["metadata_sha256"],
                "an actual Cargo metadata command log changed")
    report["source_and_artifacts_unchanged"] = True
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("library-dir", "original-root", "producer", "rustc", "work-dir", "report"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report_path = args.report.resolve()
    roots = (args.producer.resolve(), args.original_root.resolve(),
             args.library_dir.resolve(), Path(__file__).resolve().parent)
    if report_path.exists() or any(report_path == root or report_path.is_relative_to(root)
                                  for root in roots):
        raise RuntimeError("report must be new and outside every source/artifact directory")
    report = {
        "schema": "codex.hia.native-patch-effects-caller.v1", "passed": False,
        "scope": "Complete pinned original library versus actual feature-selected Cargo owner; fixed natural public inputs and unchanged real LOCAL_FS.",
        "normalization": "Only exact fresh fixture-root bytes and bounded nested hex spellings in declared path/diagnostic fields. Input bytes, patch text, structured content fields and relative filesystem snapshots remain exact.",
        "metadata_timestamps_serialized": False,
        "filesystem_or_writer_errors_injected": False,
        "unsafe_abi_qualified_by_this_report": False,
        "configured_os_sandbox_qualified_by_this_report": False,
        "entire_crate_test_suite_qualified_by_this_report": False,
        "whole_product_qualification": False,
        "legacy_retirement_qualification": False,
    }
    try:
        verify(args, report)
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        print(report["error"], file=sys.stderr)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(report_path),
                      "public": report.get("public_observations", {})}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
