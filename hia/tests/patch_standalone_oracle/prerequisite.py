"""Reuse only the same clean producer's actual complete-owner Cargo evidence."""
import json
from pathlib import Path
import re

from file_update_oracle import cargo
from file_update_oracle import identity
from patch_effects_oracle import admission
from .abi_admission import admit
from .abi_admission import require

MAIN_SHA256 = "31de3e573a13c50c81af81d262a11fdb758540408cbab3fafb5e638c66a50117"
STANDALONE_SHA256 = "33d7979c976a21b57fbb0c576ccf45b38127fef4cca4bf7af62077ce78d0c8ab"


def prepare(args, report):
    producer = args.producer.resolve(strict=True)
    library = args.library_dir.resolve(strict=True)
    parent_path = args.effects_report.resolve(strict=True)
    support = Path(__file__).resolve().parent
    require(support == producer / "hia/tests/patch_standalone_oracle",
            "process helpers must come from the actual producing checkout")
    for module, relative in ((cargo, "file_update_oracle/cargo.py"),
                             (identity, "file_update_oracle/identity.py"),
                             (admission, "patch_effects_oracle/admission.py")):
        require(Path(module.__file__).resolve() == producer / "hia/tests" / relative,
                "a shared admission helper escaped the actual producing checkout")
    original_boundary = admission.parent_original_checkout(parent_path, producer)
    roots = (producer, library, original_boundary)
    work = identity.outside(args.work_dir, roots)
    identity.outside(args.report, roots)
    identity.outside(parent_path, roots)
    require(not work.exists(), "the standalone process gate needs a new external workdir")
    work.mkdir(parents=True)
    logs = work / "commands"
    logs.mkdir()
    report.update(work_dir=str(work), commands_file=str(logs / "commands.json"),
                  process_observations_report=str(work / "process-observations/report.json"))
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
    original_manifest_path = bind(parent_work / "original-source-manifest.json")
    require(json.loads(original_manifest_path.read_text()) == manifest,
            "the embedded and separately recorded complete source inventories differ")
    require(manifest["commit"] == identity.BASE and manifest["crate_tree"] == identity.CRATE_TREE
            and manifest["crate_files"] == 104 and len(manifest["files"]) == 121,
            "the prerequisite original is not the complete immutable a201 crate")
    identity.verify_sources(snapshot, manifest)
    admission.original_lib(snapshot, manifest)
    original_tests = parent["original_tests"]
    require(original_tests["passed"] == 13 and original_tests["skipped"] == 0 and
            set(original_tests["names"]) == {"tests::" + name for name in admission.ORIGINAL_TESTS},
            "the prerequisite did not execute the 13 unchanged original root tests")
    producing = identity.producer_inputs(producer, snapshot, manifest, separate_lock=True)
    producing["complete_lib_inverse"] = admission.recover_lib(producer)
    require(producing["complete_lib_inverse"]["exact_routing_rewrites"] == 33,
            "standalone requires the complete reviewed 33-rewrite lib inverse")
    require(producing == parent["producer"], "the producer changed after its Cargo/public prerequisite")
    binding = admission.native_inputs(producer, library)
    require(binding == parent["native_inputs"] and "patch_standalone" in binding["modules"],
            "the prerequisite does not bind the current standalone owner")
    _, _, raw_bindings = admit(producer, library)
    for filename, value in raw_bindings.items():
        bind(filename, value["sha256"])
    for filename, digest in parent["harness_inputs"].items():
        path = Path(filename).resolve(strict=True)
        require(path.is_relative_to(producer), "prerequisite helper escaped the producer")
        bind(path, digest)
    for path in (*support.glob("*.py"), Path(cargo.__file__), Path(identity.__file__), Path(admission.__file__),
                 producer / "hia/tests/test_native_patch_standalone_caller.py",
                 producer / "codex-rs/apply-patch/src/hia_native_patch_standalone.rs",
                 producer / "hia/patch_standalone_buffer_contract.json"):
        bind(path)
    for name, expected in (("main.rs", MAIN_SHA256), ("standalone_executable.rs", STANDALONE_SHA256)):
        bind(snapshot / identity.CRATE / "src" / name, expected)
        bind(producer / identity.CRATE / "src" / name, expected)
        record = manifest["files"][identity.CRATE + "/src/" + name]
        require(record["sha256"] == expected, "the immutable whole executable source differs")
    original = bind(parent["original_library"]["path"], parent["original_library"]["sha256"])
    require(original.parent == parent_work, "the complete original library escaped its qualified workdir")
    parent_commands = bind(parent["commands_file"])
    require(parent_commands == parent_work / "commands/commands.json", "prerequisite command log escaped its workdir")
    commands_log = json.loads(parent_commands.read_text())
    compiled = [r for r in commands_log if r["label"] == "effects-compile-complete-original-lib"]
    require(len(compiled) == 1 and compiled[0]["returncode"] == 0 and
            compiled[0]["argv"].count(str(snapshot / identity.CRATE / "src/lib.rs")) == 1 and
            compiled[0]["argv"][-2:] == ["-o", str(original)],
            "the reference library lacks its successful complete-source compile command")
    for record in commands_log:
        require(record["returncode"] == 0, "a required prerequisite command failed")
        for stream in ("stdout", "stderr"):
            logged = bind(record[stream], record[stream + "_sha256"])
            require(logged.is_relative_to(parent_work) and logged.stat().st_size == record[stream + "_bytes"],
                    "a prerequisite command output changed")
    graphs = {}
    for side in ("original", "default", "native"):
        record = parent["actual_cargo_graph_manifests"][side]
        path = parent_work / (side + "-dependency-manifest.json")
        require(record["path"] == str(path) and record["bytes"] == path.stat().st_size,
                "the prerequisite graph path or length differs")
        bind(path, record["sha256"])
        graph = json.loads(path.read_text())
        cargo.verify_graph(graph)
        owner_unit = graph["direct"]["codex_apply_patch"]["unit"]
        require(graph["actual_cargo_build_succeeded"] is True and
                owner_unit["features"] == (["hia-native"] if side == "native" else []) and
                owner_unit["profile"] == admission.PROFILE,
                "the complete owner Cargo feature/profile dispatch differs")
        actual = parent["actual_cargo_builds"][side]
        require(actual["successful_build_finished"] and
                actual["artifact_jsonl_sha256"] == graph["artifact_jsonl_sha256"] and
                actual["owner_unit"] == graph["direct"]["codex_apply_patch"]["unit"] and
                actual["actual_library_units"] == len(graph["units"]) and
                actual["actual_library_files"] == len(graph["files"]),
                "the actual complete Cargo unit/feature/profile/artifact graph differs")
        graphs[side] = graph
    for side in ("original", "default", "native"):
        receipt = parent["actual_serde_identity"][side]
        admission.verify_fingerprints(receipt)
        selected = receipt["library"]
        require(graphs[side]["files"].get(Path(selected["path"]).name) == selected and
                receipt["unit"] in graphs[side]["units"], "the actual serde unit escaped its graph")
        bind(selected["path"], selected["sha256"])
        for path, digest in receipt["fingerprint_inputs"].items():
            bind(path, digest)
    original_checkout, metadata = admission.verify_parent_lanes(
        parent, parent_work, producer, graphs, bind)
    require(original_checkout == original_boundary,
            "prerequisite original checkout changed during admission")
    native = Path(graphs["native"]["direct"]["codex_apply_patch"]["path"])
    bind(native, graphs["native"]["files"][native.name]["sha256"])
    rustc, _, env, compiler = cargo.compiler(args.rustc, commands, producer)
    require(compiler == parent["toolchain"], "the process compiler differs from its actual owner prerequisite")
    env.update(PYTHONDONTWRITEBYTECODE="1", RUST_BACKTRACE="0")
    binaries = {side: work / ("standalone-" + side) for side in ("original", "native")}
    for side, owner in (("original", original), ("native", native)):
        graph = graphs[side]
        flags = cargo.flags(rustc, graph, original=True)
        if side == "native":
            flags += ["-L", "native=" + str(library)]
            for module in (*admission.MODULES, "patch_standalone"):
                flags += ["-l", "static=codex_hia_" + module]
        main = (snapshot if side == "original" else producer) / identity.CRATE / "src/main.rs"
        commands.run("compile-complete-standalone-" + side, flags + [
            "--crate-name", "standalone_" + side + "_process", "--extern",
            "codex_apply_patch=" + str(owner), main, "-o", binaries[side]], cwd=producer, env=(admission.original_compile_environment(
                producer, env, graph) if side == "original" else env))
        symbols = commands.run("standalone-symbols-" + side,
            ["nm", "--defined-only", binaries[side]], cwd=producer, env=env).read_text()
        count = len(re.findall(r"\b[Tt] codex_hia_patch_standalone$", symbols, re.MULTILINE))
        require(count == int(side == "native"), "the complete executable has a wrong native owner symbol inventory")
        bind(binaries[side])
    report.update(prerequisite={"path": str(parent_path), "sha256": identity.sha(parent_path),
        "actual_cargo_builds": parent["actual_cargo_builds"], "original_tests": original_tests},
        producing_source=producing, original_source_manifest_sha256=identity.sha(parent_work / "original-source-manifest.json"),
        native_binding=binding, compiler=compiler, input_bindings=bound,
        original_library={"path": str(original), "sha256": identity.sha(original)},
        native_library={"path": str(native), "sha256": identity.sha(native)},
        complete_programs={side: {"path": str(path), "sha256": identity.sha(path)} for side, path in binaries.items()},
        commands_file=str(logs / "commands.json"))
    return {"producer": producer, "library": library, "work": work, "binaries": binaries,
            "bound": bound, "graphs": graphs, "serde": parent["actual_serde_identity"],
            "snapshot": snapshot, "manifest": manifest, "producing": producing, "binding": binding,
            "original_checkout": original_checkout, "metadata": metadata}


def unchanged(context):
    cargo.verify_three_graphs(context["graphs"], context["metadata"],
                              context["original_checkout"], context["producer"])
    for receipt in context["serde"].values():
        admission.verify_fingerprints(receipt)
    identity.verify_sources(context["snapshot"], context["manifest"])
    current = identity.producer_inputs(context["producer"], context["snapshot"], context["manifest"], separate_lock=True)
    current["complete_lib_inverse"] = admission.recover_lib(context["producer"])
    require(current == context["producing"] and
            admission.native_inputs(context["producer"], context["library"]) == context["binding"],
            "source or native owner changed during process qualification")
    for filename, expected in context["bound"].items():
        path = Path(filename)
        require(identity.sha(path) == expected["sha256"] and path.stat().st_size == expected["bytes"],
                "a complete process gate input changed")
