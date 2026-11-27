"""Build and retain the original dependency graph from its immutable workspace.

The reference workspace is never edited to adopt the producer's dependency
versions. Its ordinary Cargo build has a separate target directory and no HIA
compiler wrapper. Both the original checkout and every retained artifact remain
bound through the end of each comparison that consumes this receipt.
"""
import json
from pathlib import Path

from . import cargo, identity

ORIGINALS = {
    identity.BASE: identity.CRATE_TREE,
    "aeb88f596b83186456caac577080bcb2f253ad32":
        "df2e05444c0768915f267c7aa5ba65f896a54ec5",
}
DECLARATIONS = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
                identity.CRATE + "/Cargo.toml")
WRAPPING_PROFILE = (
    "[profile.dev.package.similar]\noverflow-checks=false\n"
    "[profile.dev.package.codex-apply-patch]\noverflow-checks=false\n"
)


def bind(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": identity.sha(path)}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def same_json_value(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            same_json_value(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            same_json_value(left, right) for left, right in zip(actual, expected))
    return actual == expected


def verify_cargo_evidence(graph, metadata, commands, original, target):
    """Re-derive receipt identities from the retained actual Cargo streams."""
    raw_metadata = json.loads(Path(commands[0]["stdout"]).read_text())
    require(Path(raw_metadata["target_directory"]).resolve() == target,
            "historical target directory differs from actual Cargo metadata")
    packages = {row["id"]: row for row in raw_metadata["packages"]}
    require(len(packages) == len(raw_metadata["packages"]),
            "historical Cargo metadata contains duplicate package identities")
    expected_metadata = {name: {
        "manifest_path": str(Path(row["manifest_path"]).resolve(strict=True)),
        "manifest_sha256": identity.sha(row["manifest_path"]),
        "source": row["source"], "name": row["name"], "version": row["version"]}
        for name, row in packages.items()}
    require(same_json_value(metadata["packages"], expected_metadata),
            "historical source inventory differs from actual Cargo metadata")
    owner = next(row for row in packages.values() if
                 Path(row["manifest_path"]).resolve() == original / identity.CRATE / "Cargo.toml")
    node = next(row for row in raw_metadata["resolve"]["nodes"] if row["id"] == owner["id"])
    wanted = {row["name"].replace("-", "_"): row["pkg"] for row in node["deps"]}
    wanted["codex_apply_patch"] = owner["id"]
    messages = [json.loads(line) for line in Path(commands[1]["stdout"]).read_text().splitlines()]
    endings = [row for row in messages if row.get("reason") == "build-finished"]
    require(len(endings) == 1 and endings[0].get("success") is True and
            messages[-1] == endings[0], "historical Cargo did not finish successfully")
    units, files, native_paths = [], {}, set()
    for row in messages:
        if row.get("reason") == "build-script-executed":
            native_paths.update(row.get("linked_paths", []))
        if row.get("reason") != "compiler-artifact":
            continue
        paths = [Path(value).resolve(strict=True) for value in row["filenames"]
                 if Path(value).suffix in {".rlib", ".rmeta", ".so"}]
        if not paths:
            continue
        package = packages[row["package_id"]]
        require(row["target"] in package["targets"], "historical Cargo target/source differs")
        primary = next(path for path in paths if path.suffix in {".rlib", ".so"})
        suffix = primary.stem.rsplit("-", 1)[-1]
        fingerprint = primary.parent.parent / ".fingerprint" / (package["name"] + "-" + suffix) / (
            "lib-" + row["target"]["name"] + ".json")
        recorded = json.loads(fingerprint.read_text())
        require(json.loads(recorded["features"]) == row["features"] and recorded["rustflags"] == [],
                "historical Cargo fingerprint has different features or compiler flags")
        unit = {"package_id": package["id"], "target": row["target"],
                "features": row["features"], "profile": row["profile"],
                "files": [path.name for path in paths], "fingerprint_sha256": identity.sha(fingerprint)}
        units.append(unit)
        for path in paths:
            require(path.name not in files, "historical Cargo repeats a library artifact")
            files[path.name] = {"source": str(path), "path": str(Path(graph["stage"]) / path.name),
                "bytes": path.stat().st_size, "sha256": graph["files"][path.name]["sha256"],
                "package_id": package["id"]}
    require(same_json_value(graph["units"], units) and
            same_json_value(graph["files"], files) and
            same_json_value(graph["native_paths"], sorted(native_paths)),
            "historical graph differs from the actual Cargo artifact stream")
    for name, selected in graph["direct"].items():
        choices = [unit for unit in units if unit["target"]["name"] == name and
                   unit["package_id"] == wanted[name]]
        require(same_json_value(choices, [selected["unit"]]) and
                selected["path"] in [str(Path(graph["stage"]) / member)
                                     for member in choices[0]["files"] if member.endswith(".rlib")],
                "historical direct dependency is not the actual resolved Cargo unit: " + name)


def source(original, commit):
    require(commit in ORIGINALS, "unreviewed historical dependency baseline")
    original = Path(original).resolve(strict=True)
    actual = identity.clean_identity(original)
    require(actual["commit"] == commit, "historical workspace is not its exact pinned commit")
    crate_tree = identity.git(original, "rev-parse", f"HEAD:{identity.CRATE}").decode().strip()
    require(crate_tree == ORIGINALS[commit], "historical whole-owner tree changed")
    declarations = {name: bind(original / name) for name in DECLARATIONS}
    return {"root": str(original), **actual, "crate_tree": crate_tree,
            "declarations": declarations}


def capture(original, commit, rustc, env, output, *, overflow_mode=0):
    require(type(overflow_mode) is int and overflow_mode in (0, 1),
            "historical dependency policy must be checked or wrapping")
    original = Path(original).resolve(strict=True)
    rustc = Path(rustc).resolve(strict=True)
    before = source(original, commit)
    require(identity.sha(rustc) == identity.RUSTC_SHA256,
            "historical dependencies require the fixed Linux Rust 1.96.1 compiler")
    overrides = {name: value for name, value in env.items() if value and (
        name in {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS"}
        or (name.startswith("CARGO_TARGET_") and name.endswith("_RUSTFLAGS")))}
    require(not overrides, "historical dependency compiler flags cannot be overridden by the environment")
    output = identity.outside(output, (original,))
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "commands"
    logs.mkdir()
    commands = cargo.Commands(logs)
    target = Path(env["CARGO_TARGET_DIR"]).resolve() / "historical-originals" / commit / str(overflow_mode)
    identity.outside(target, (original,))
    target.mkdir(parents=True, exist_ok=True)
    child = dict(env)
    removed = {}
    for name in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                 "CODEX_HIA_SIMILAR_POLICY_CONFIG", "CODEX_HIA_NATIVE_LIB_DIR"):
        removed[name] = child.pop(name, None)
    child.update(RUSTC=str(rustc), RUSTUP_TOOLCHAIN="1.96.1",
                 CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0",
                 CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_TEST_DEBUG="0")
    child.setdefault("CARGO_BUILD_JOBS", "1")
    real_cargo = rustc.parent / "cargo"
    _, packages, owner, dependencies, metadata = cargo.metadata(
        real_cargo, original, child, commands)
    profiles = []
    configuration = None
    if overflow_mode == 1:
        profile = output / "wrapping.toml"
        profile.write_text(WRAPPING_PROFILE)
        configuration = bind(profile)
        profiles = ["--config", profile]
    captured = commands.run("cargo-original", [real_cargo, *profiles, "build",
        "--locked", "--no-default-features", "-p", "codex-apply-patch", "--tests",
        "--message-format=json-render-diagnostics"],
        cwd=original / "codex-rs", env=child, jsonl=True)
    graph = cargo.admit(captured, packages, owner, dependencies, target,
                        output / "deps", native=False, overflow_mode=overflow_mode)
    graph_path = output / "dependency-manifest.json"
    graph_path.write_text(json.dumps(graph, indent=2) + "\n")
    metadata_path = output / "metadata-source-inputs.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    require(source(original, commit) == before,
            "historical workspace changed during its actual Cargo build")
    record = {
        "schema": "codex.hia.historical-dependency-graph.v1",
        "source": before, "rustc": bind(rustc), "cargo": bind(real_cargo),
        "graph": bind(graph_path), "metadata": bind(metadata_path),
        "commands": bind(logs / "commands.json"),
        "overflow_mode": overflow_mode, "configuration": configuration,
        "excluded_producer_wrapper_environment": removed,
        "codegen_environment_overrides": overrides,
        "actual_target_directory": str(target),
        "actual_ordinary_cargo_build_succeeded": True,
        "native_features_enabled": False,
    }
    verify(record)
    return graph, packages, record


def verify(record):
    require(record.get("schema") == "codex.hia.historical-dependency-graph.v1" and
            record.get("actual_ordinary_cargo_build_succeeded") is True and
            record.get("native_features_enabled") is False,
            "missing successful historical Cargo dependency qualification")
    require(record.get("codegen_environment_overrides") == {},
            "historical dependency compiler flags lack their explicit admission")
    expected = record["source"]
    require(same_json_value(source(expected["root"], expected["commit"]), expected),
            "historical source/dependency baseline changed")
    for key in ("rustc", "cargo", "graph", "metadata", "commands"):
        require(same_json_value(bind(record[key]["path"]), record[key]),
                "historical dependency input or receipt changed: " + key)
    require(record["rustc"]["sha256"] == identity.RUSTC_SHA256,
            "historical compiler is not the pinned compiler")
    require(Path(record["cargo"]["path"]) == Path(record["rustc"]["path"]).parent / "cargo",
            "historical Cargo is not from the fixed compiler toolchain")
    configuration = record["configuration"]
    mode = record["overflow_mode"]
    require(type(mode) is int and mode in (0, 1), "invalid historical overflow policy")
    if mode == 0:
        require(configuration is None, "checked historical policy has an unexpected override")
    else:
        require(configuration is not None and same_json_value(bind(configuration["path"]), configuration) and
                Path(configuration["path"]).read_text() == WRAPPING_PROFILE,
                "historical wrapping policy differs")
    commands = json.loads(Path(record["commands"]["path"]).read_text())
    require([row["label"] for row in commands] == ["cargo-metadata", "cargo-original"],
            "missing or extra historical dependency commands")
    expected_metadata = [record["cargo"]["path"], "metadata", "--locked",
        "--format-version=1", "--filter-platform", "x86_64-unknown-linux-gnu",
        "--no-default-features"]
    expected_build = [record["cargo"]["path"],
        *(["--config", configuration["path"]] if configuration is not None else []),
        "build", "--locked", "--no-default-features", "-p", "codex-apply-patch",
        "--tests", "--message-format=json-render-diagnostics"]
    require(commands[0]["argv"] == expected_metadata and commands[1]["argv"] == expected_build,
            "historical Cargo command or feature selection changed")
    for command in commands:
        require(type(command["returncode"]) is int and command["returncode"] == 0 and command["cwd"] ==
                str(Path(expected["root"]) / "codex-rs"),
                "historical dependency command failed or used another workspace")
        for stream in ("stdout", "stderr"):
            require(same_json_value(bind(command[stream]), {"path": command[stream],
                    "bytes": command[stream + "_bytes"],
                    "sha256": command[stream + "_sha256"]}),
                    "historical dependency command output changed")
    graph = json.loads(Path(record["graph"]["path"]).read_text())
    require(graph["actual_cargo_build_succeeded"] is True and
            graph["artifact_jsonl_sha256"] == commands[1]["stdout_sha256"],
            "historical graph is not bound to its successful Cargo output")
    owner = graph["direct"]["codex_apply_patch"]["unit"]
    require(owner["features"] == [] and Path(owner["target"]["src_path"]).resolve() ==
            Path(expected["root"]) / identity.CRATE / "src/lib.rs",
            "historical graph selected another owner or native feature")
    target = Path(record["actual_target_directory"]).resolve(strict=True)
    require(all(Path(row["source"]).resolve().is_relative_to(target)
                for row in graph["files"].values()),
            "historical dependency artifact escaped the actual target directory")
    require(set(graph["direct"]) == identity.REQUIRED | {"codex_apply_patch"},
            "historical direct dependency inventory differs")
    for name, selected in graph["direct"].items():
        unit = selected["unit"]
        profile = {"opt_level": "0", "debuginfo": 0, "debug_assertions": True,
                   "overflow_checks": not (mode == 1 and name in {"similar", "codex_apply_patch"}),
                   "test": False}
        require(unit in graph["units"] and
                all(type(unit["profile"].get(key)) is type(value) and
                    unit["profile"][key] == value for key, value in profile.items()),
                "historical direct dependency profile or unit differs: " + name)
    cargo.verify_graph(graph)
    metadata = json.loads(Path(record["metadata"]["path"]).read_text())
    require(metadata["metadata_sha256"] == commands[0]["stdout_sha256"],
            "historical source inventory is not bound to actual Cargo metadata")
    for package in metadata["packages"].values():
        require(identity.sha(package["manifest_path"]) == package["manifest_sha256"],
                "historical dependency manifest changed")
    verify_cargo_evidence(graph, metadata, commands, Path(expected["root"]), target)
    return graph
