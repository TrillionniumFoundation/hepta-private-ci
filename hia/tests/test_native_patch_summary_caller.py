#!/usr/bin/env python3
"""Observe summary writes using the qualified complete original and Cargo owner.

The effects gate supplies a real complete original library and fresh admitted
Cargo graphs. This gate revalidates those inputs, compiles two public observers,
and executes the fixed writer corpus. It does not claim a second Cargo build.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
DRIVER_SHA256 = "5a8e83b127ba52aa381188b8325f0e32ddab9776e27b422561343b62c90073b2"


def verify(args, report):
    producer = args.producer.resolve(strict=True)
    library = args.library_dir.resolve(strict=True)
    parent_path = args.effects_report.resolve(strict=True)
    sys.path.insert(0, str(producer / "hia/tests"))
    from file_update_oracle import cargo, identity
    from patch_effects_oracle import admission
    from patch_summary_oracle import observations

    require = observations.require
    require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    support = Path(observations.__file__).resolve().parent
    require(support == producer / "hia/tests/patch_summary_oracle" and
            Path(__file__).resolve() == producer / "hia/tests/test_native_patch_summary_caller.py",
            "public writer helpers must come from the actual producing checkout")
    original_boundary = admission.parent_original_checkout(parent_path, producer)
    roots = (producer, library, original_boundary)
    work = identity.outside(args.work_dir, roots)
    identity.outside(args.report, roots)
    identity.outside(parent_path, roots)
    require(not work.exists(), "public writer output must be a new external directory")
    work.mkdir(parents=True)
    logs = work / "commands"
    logs.mkdir()
    commands = cargo.Commands(logs)
    bound = {}

    def bind(path, expected=None):
        path = Path(path).resolve(strict=True)
        digest = identity.sha(path)
        require(expected is None or digest == expected, "bound input differs: " + str(path))
        bound[str(path)] = {"bytes": path.stat().st_size, "sha256": digest}
        return path

    bind(parent_path)
    parent = json.loads(parent_path.read_text())
    require(parent["schema"] == "codex.hia.native-patch-effects-caller.v1" and
            parent["passed"] and parent["source_and_artifacts_unchanged"],
            "the prerequisite complete-owner effects gate did not pass")
    parent_work = identity.outside(parent["work_dir"], roots)
    snapshot = parent_work / "original"
    manifest = parent["original_inputs"]
    require(manifest["commit"] == identity.BASE and manifest["crate_tree"] == identity.CRATE_TREE
            and manifest["crate_files"] == 104 and len(manifest["files"]) == 121,
            "the prerequisite original is not the complete pinned crate")
    identity.verify_sources(snapshot, manifest)
    admission.original_lib(snapshot, manifest)
    producing = identity.producer_inputs(producer, snapshot, manifest, separate_lock=True)
    producing["complete_lib_inverse"] = admission.recover_lib(producer)
    require(producing == parent["producer"], "the producing source changed after the effects gate")
    binding = admission.native_inputs(producer, library)
    require(binding == parent["native_inputs"] and "patch_summary" in binding["modules"],
            "the prerequisite native build does not bind the current summary module")
    for path, digest in parent["harness_inputs"].items():
        current = Path(path).resolve(strict=True)
        require(current.is_relative_to(producer), "prerequisite helper escaped the producer")
        bind(current, digest)
    for path in (Path(__file__), *support.glob("*.py"), support / "driver.rs",
                 Path(cargo.__file__), Path(identity.__file__), Path(admission.__file__),
                 producer / "codex-rs/apply-patch/src/hia_native_patch_summary.rs",
                 producer / "hia/patch_summary_buffer_contract.json"):
        bind(path)
    bind(support / "driver.rs", DRIVER_SHA256)
    original = bind(parent["original_library"]["path"],
                    parent["original_library"]["sha256"])
    require(original.parent == parent_work, "whole original library escaped its qualified workdir")
    graphs = {}
    for side in ("original", "default", "native"):
        manifest_record = parent["actual_cargo_graph_manifests"][side]
        graph_path = parent_work / (side + "-dependency-manifest.json")
        require(manifest_record["path"] == str(graph_path) and
                manifest_record["bytes"] == graph_path.stat().st_size,
                "prerequisite Cargo graph path or byte length differs")
        bind(graph_path, manifest_record["sha256"])
        graph = json.loads(graph_path.read_text())
        cargo.verify_graph(graph)
        actual = parent["actual_cargo_builds"][side]
        require(actual["successful_build_finished"] and
                actual["artifact_jsonl_sha256"] == graph["artifact_jsonl_sha256"] and
                actual["owner_unit"] == graph["direct"]["codex_apply_patch"]["unit"] and
                actual["actual_library_units"] == len(graph["units"]) and
                actual["actual_library_files"] == len(graph["files"]),
                "prerequisite Cargo graph or actual owner unit differs")
        graphs[side] = graph
    original_checkout, metadata = admission.verify_parent_lanes(
        parent, parent_work, producer, graphs, bind)
    require(original_checkout == original_boundary,
            "prerequisite original checkout changed during admission")
    native = Path(graphs["native"]["direct"]["codex_apply_patch"]["path"])
    bind(native, graphs["native"]["files"][native.name]["sha256"])
    rustc, _, env, compiler = cargo.compiler(args.rustc, commands, producer)
    require(compiler == parent["toolchain"], "public writer compiler differs from its prerequisite")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    binaries = {side: work / ("summary-" + side) for side in ("original", "native")}
    for side, owner in (("original", original), ("native", native)):
        graph = graphs[side]
        flags = cargo.flags(rustc, graph, original=True)
        flags += ["--check-cfg", "cfg(native_summary)"]
        if side == "native":
            flags += ["--cfg", "native_summary", "-C",
                      "link-arg=-Wl,--wrap=codex_hia_patch_summary",
                      "-L", "native=" + str(library)]
            for module in admission.MODULES:
                flags += ["-l", "static=codex_hia_" + module]
        commands.run("compile-summary-" + side, flags + [
            "--crate-name", "patch_summary_" + side + "_observer", "--extern",
            "codex_apply_patch=" + str(owner), support / "driver.rs", "-o", binaries[side]],
            cwd=producer, env=(admission.original_compile_environment(
                producer, env, graph) if side == "original" else env))
        symbols = commands.run("summary-symbols-" + side,
            ["nm", "--defined-only", binaries[side]], cwd=producer, env=env).read_text()
        for symbol in ("codex_hia_patch_summary", "__wrap_codex_hia_patch_summary"):
            count = len(re.findall(r"\b[Tt] " + symbol + r"$", symbols, re.MULTILINE))
            require(count == int(side == "native"), "wrong real summary symbol inventory")
        bind(binaries[side])
    report.update(prerequisite={"path": str(parent_path), "sha256": identity.sha(parent_path),
        "actual_cargo_builds": parent["actual_cargo_builds"],
        "original_tests": parent["original_tests"]}, producing_source=producing,
        original_source_manifest_sha256=identity.sha(parent_work / "original-source-manifest.json"),
        native_binding=binding, compiler=compiler, inputs=bound,
        original_library={"path": str(original), "sha256": identity.sha(original)},
        native_library={"path": str(native), "sha256": identity.sha(native)},
        commands_file=str(logs / "commands.json"))
    public = observations.run(binaries, producer, env, work / "public-observations")
    report["public_observations"] = {key: value for key, value in public.items() if key != "results"}
    report["public_observations"]["report_path"] = str(work / "public-observations/report.json")
    require(public["passed"] and public["compared_pairs"] == 1002 and
            public["actual_processes"] == 2004 and public["skipped"] == public["mismatches"] == 0,
            "the complete public writer corpus did not pass")
    cargo.verify_three_graphs(graphs, metadata, original_checkout, producer)
    identity.verify_sources(snapshot, manifest)
    final = identity.producer_inputs(producer, snapshot, manifest, separate_lock=True)
    final["complete_lib_inverse"] = admission.recover_lib(producer)
    require(final == producing and admission.native_inputs(producer, library) == binding,
            "production sources or native artifacts changed during writer qualification")
    for path, record in bound.items():
        require(identity.sha(path) == record["sha256"] and
                Path(path).stat().st_size == record["bytes"], "a bound writer input changed")
    report["source_and_artifacts_unchanged"] = True
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("producer", "library-dir", "effects-report", "rustc", "work-dir", "report"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    path = args.report.resolve()
    if path.exists() or any(path.is_relative_to(root.resolve())
                            for root in (args.producer, args.library_dir)):
        raise RuntimeError("report must be new and outside source/artifact directories")
    report = {"schema": "codex.hia.native-patch-summary-caller.v1", "passed": False,
        "scope": "Complete original and actual Cargo owner public print_summary; exact formatting callbacks, accepted write prefixes, Interrupted, WriteZero and custom errors.",
        "cargo_compilation_executed_by_this_gate": False,
        "filesystem_operations_executed_by_this_gate": False,
        "entire_crate_test_suite_qualified_by_this_report": False,
        "whole_product_qualification": False, "legacy_retirement_qualification": False}
    try:
        verify(args, report)
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        print(report["error"], file=sys.stderr)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(path),
                      "public": report.get("public_observations", {})}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
