#!/usr/bin/env python3
"""Compare all three public patch-application APIs from complete actual crates.

The effects gate supplies a real complete original library and fresh admitted
Cargo graphs. This gate revalidates those inputs, compiles two public observers,
and executes natural filesystem scenarios with actual in-memory Write contracts.
It does not claim a second Cargo build.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
DRIVER_SHA256 = "0306fc9ae81434d1846ad0e1ebd037e7d027b99ea3abd4afdf59bcfc0c3468c8"


def verify(args, report):
    producer = args.producer.resolve(strict=True)
    library = args.library_dir.resolve(strict=True)
    parent_path = args.effects_report.resolve(strict=True)
    sys.path.insert(0, str(producer / "hia/tests"))
    from file_update_oracle import cargo, identity
    from patch_effects_oracle import admission
    from patch_application_oracle import observations

    require = observations.require
    require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    support = Path(observations.__file__).resolve().parent
    require(support == producer / "hia/tests/patch_application_oracle" and
            Path(__file__).resolve() == producer / "hia/tests/test_native_patch_application_caller.py",
            "public writer helpers must come from the actual producing checkout")
    roots = (producer, library)
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
    require(parent["schema"] == "codex.hia.native-patch-effects-caller.v2" and
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
    original_tests = parent["original_tests"]
    require(original_tests["passed"] == 13 and original_tests["skipped"] == 0 and
            set(original_tests["names"]) == {"tests::" + name for name in admission.ORIGINAL_TESTS},
            "the complete-original prerequisite did not run the exact 13 root tests")
    dependency_baseline = parent["dependency_baseline"]
    producing = identity.producer_inputs(producer, snapshot, manifest,
                                        dependency_baseline=dependency_baseline)
    producing["complete_lib_inverse"] = admission.recover_lib(producer)
    require(producing == parent["producer"], "the producing source changed after the effects gate")
    binding = admission.native_inputs(producer, library)
    require(binding == parent["native_inputs"] and "patch_application" in binding["modules"],
            "the prerequisite native build does not bind the current patch-application module")
    for path, digest in parent["harness_inputs"].items():
        current = Path(path).resolve(strict=True)
        require(current.is_relative_to(producer), "prerequisite helper escaped the producer")
        bind(current, digest)
    for path in (Path(__file__), *support.glob("*.py"), *support.glob("*.rs"),
                 producer / "hia/tests/patch_effects_oracle/observations.py",
                 producer / "hia/tests/patch_effects_oracle/observed_fs.rs",
                 Path(cargo.__file__), Path(identity.__file__), Path(admission.__file__),
                 producer / "codex-rs/apply-patch/src/hia_native_patch_application.rs",
                 producer / "hia/patch_application_buffer_contract.json"):
        bind(path)
    bind(support / "driver.rs", DRIVER_SHA256)
    bind(producer / "hia/tests/patch_effects_oracle/observed_fs.rs",
         "bec939e2e1804f1c0cfc2b7ff222c167c9c55c824a732d20840afddfae040d8b")
    contract = json.loads((producer / "hia/patch_application_buffer_contract.json").read_text())
    require(contract["schema"] == "codex.hia.patch-application-buffer-contract.v1" and
            contract["symbol"] == "codex_hia_patch_application" and contract["revision"] == 1,
            "the application continuation contract differs")
    original = bind(parent["original_library"]["path"],
                    parent["original_library"]["sha256"])
    require(original.parent == parent_work, "whole original library escaped its qualified workdir")
    parent_commands = bind(parent["commands_file"])
    require(parent_commands == parent_work / "commands/commands.json",
            "prerequisite command log escaped its qualified workdir")
    commands_log = json.loads(parent_commands.read_text())
    original_compiles = [r for r in commands_log if r["label"] == "effects-compile-complete-original-lib"]
    require(len(original_compiles) == 1 and original_compiles[0]["returncode"] == 0 and
            original_compiles[0]["argv"].count(str(snapshot / identity.CRATE / "src/lib.rs")) == 1
            and original_compiles[0]["argv"][-2:] == ["-o", str(original)],
            "the original library lacks its successful complete-source compile command")
    for record in commands_log:
        require(record["returncode"] == 0, "the prerequisite contains a failed required command")
        for stream in ("stdout", "stderr"):
            logged = bind(record[stream], record[stream + "_sha256"])
            require(logged.is_relative_to(parent_work) and
                    logged.stat().st_size == record[stream + "_bytes"], "command log identity differs")
    graphs = {}
    for side in ("default", "native"):
        manifest_record = parent["actual_cargo_graph_manifests"][side]
        require(side != "default" or manifest_record["sha256"] == dependency_baseline["graph"]["sha256"],
                "the reference dependency graph is not the qualified historical graph")
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
    serde = parent["actual_serde_identity"]
    for side in ("default", "native"):
        admission.verify_fingerprints(serde[side])
        selected = serde[side]["library"]
        actual = graphs[side]["files"].get(Path(selected["path"]).name)
        require(actual == selected and serde[side]["unit"] in graphs[side]["units"],
                "sandbox serde library is not in the actual admitted dependency graph")
        bind(selected["path"], selected["sha256"])
        for path, digest in serde[side]["fingerprint_inputs"].items():
            bind(path, digest)
    native = Path(graphs["native"]["direct"]["codex_apply_patch"]["path"])
    bind(native, graphs["native"]["files"][native.name]["sha256"])
    rustc, _, env, compiler = cargo.compiler(args.rustc, commands, producer)
    require(compiler == parent["toolchain"], "public writer compiler differs from its prerequisite")
    env.update(PYTHONDONTWRITEBYTECODE="1", RUST_BACKTRACE="0")
    binaries = {side: work / ("application-" + side) for side in ("original", "native")}
    for side, owner in (("original", original), ("native", native)):
        graph = graphs["default" if side == "original" else "native"]
        flags = cargo.flags(rustc, graph, original=True)
        flags += ["--check-cfg", "cfg(native_application)"]
        flags += ["--extern", "serde_json=" +
                  serde["default" if side == "original" else "native"]["library"]["path"]]
        if side == "native":
            flags += ["--cfg", "native_application", "-C",
                      "link-arg=-Wl,--wrap=codex_hia_patch_application",
                      "-L", "native=" + str(library)]
            for module in admission.MODULES:
                flags += ["-l", "static=codex_hia_" + module]
        commands.run("compile-application-" + side, flags + [
            "--crate-name", "patch_application_" + side + "_observer", "--extern",
            "codex_apply_patch=" + str(owner), support / "driver.rs", "-o", binaries[side]],
            cwd=producer, env=env)
        symbols = commands.run("application-symbols-" + side,
            ["nm", "--defined-only", binaries[side]], cwd=producer, env=env).read_text()
        for symbol in ("codex_hia_patch_application", "__wrap_codex_hia_patch_application"):
            count = len(re.findall(r"\b[Tt] " + symbol + r"$", symbols, re.MULTILINE))
            require(count == int(side == "native"), "wrong real patch-application symbol inventory")
        bind(binaries[side])
    report.update(prerequisite={"path": str(parent_path), "sha256": identity.sha(parent_path),
        "actual_cargo_builds": parent["actual_cargo_builds"],
        "original_tests": parent["original_tests"]}, producing_source=producing,
        original_source_manifest_sha256=identity.sha(parent_work / "original-source-manifest.json"),
        native_binding=binding, compiler=compiler, inputs=bound,
        original_library={"path": str(original), "sha256": identity.sha(original)},
        native_library={"path": str(native), "sha256": identity.sha(native)},
        commands_file=str(logs / "commands.json"))
    public = observations.run(binaries, producer, env, work / "public-observations", contract)
    report["public_observations"] = {key: value for key, value in public.items() if key != "cases"}
    report["public_observations"]["report_path"] = str(work / "public-observations/report.json")
    require(public["passed"] and public["compared_pairs"] == 1470 and
            public["actual_processes"] == 2940 and public["skipped"] == public["mismatches"] == 0,
            "the complete public writer corpus did not pass")
    for graph in graphs.values():
        cargo.verify_graph(graph)
    for receipt in serde.values():
        admission.verify_fingerprints(receipt)
    identity.verify_sources(snapshot, manifest)
    final = identity.producer_inputs(producer, snapshot, manifest,
                                    dependency_baseline=dependency_baseline)
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
    report = {"schema": "codex.hia.native-patch-application-caller.v1", "passed": False,
        "scope": "Complete original and actual Cargo owner apply_patch_with_options/apply_patch/apply_hunks; exact public errors/deltas, natural filesystem results and real Write/write_fmt behavior.",
        "cargo_compilation_executed_by_this_gate": False,
        "filesystem_operations_executed_by_this_gate": True,
        "filesystem_results_substituted": False,
        "paths_or_errors_normalized": False,
        "controlled_pending_or_cancellation_qualified": False,
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
