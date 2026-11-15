"""Actual scoped Cargo graphs; complete direct and transitive artifact admission."""
import json
from pathlib import Path
import re
import shutil

from .common import require, sha
from .original import CRATE
from .artifacts import libraries

REQUIRED = frozenset(("serde", "serde_json", "regex_lite", "pretty_assertions"))
PROFILE = {"opt_level": "0", "debuginfo": 0, "debug_assertions": True,
           "overflow_checks": True, "test": False}


def metadata(cargo, producer, env, commands):
    path = commands.run("cargo-metadata", [cargo, "metadata", "--locked", "--format-version=1",
        "--filter-platform", "x86_64-unknown-linux-gnu", "--no-default-features"],
        cwd=producer / "codex-rs", env=env, jsonl=True)
    graph = json.loads(path.read_bytes())
    packages = {p["id"]: p for p in graph["packages"]}
    require(len(packages) == len(graph["packages"]), "duplicate actual metadata package IDs")
    owners = [p for p in packages.values() if Path(p["manifest_path"]).resolve() == producer / CRATE / "Cargo.toml"]
    require(len(owners) == 1 and owners[0]["name"] == "codex-utils-string", "actual owner manifest differs")
    owner = owners[0]
    nodes = [n for n in graph["resolve"]["nodes"] if n["id"] == owner["id"]]
    require(len(nodes) == 1, "missing actual owner resolution")
    dependencies = {d["name"].replace("-", "_"): d["pkg"] for d in nodes[0]["deps"]}
    require(set(dependencies) == REQUIRED, "the complete four-dependency set differs")
    for package in packages.values():
        manifest = Path(package["manifest_path"]).resolve(strict=True)
        require(package["source"] is not None or manifest.is_relative_to(producer),
                "a path dependency escaped the producing checkout")
    return graph, packages, owner, dependencies


def capture(cargo, producer, env, native, commands):
    child = env.copy()
    if not native:
        child.pop("CODEX_HIA_NATIVE_LIB_DIR", None)
    args = [cargo, "build", "--locked", "--no-default-features", "-p", "codex-utils-string",
            "--lib", "--tests", "--message-format=json-render-diagnostics"]
    if native:
        args += ["--features", "hia-native"]
    return commands.run("cargo-native" if native else "cargo-default", args,
                        cwd=producer / "codex-rs", env=child, jsonl=True)


def admit(path, packages, owner, dependencies, target_dir, stage, *, native):
    messages = [json.loads(line) for line in path.read_text().splitlines()]
    endings = [m for m in messages if m.get("reason") == "build-finished"]
    if len(endings) != 1 or endings[0].get("success") is not True or messages[-1] != endings[0]:
        raise RuntimeError("Cargo must emit exactly one final successful build-finished record")
    stage.mkdir()
    direct = {name: [] for name in REQUIRED | {"codex_utils_string"}}
    wanted = {**dependencies, "codex_utils_string": owner["id"]}
    files, units, native_paths, publication_aliases = {}, [], set(), []
    for message in messages:
        if message.get("reason") == "build-script-executed":
            native_paths.update(message.get("linked_paths", []))
        if message.get("reason") != "compiler-artifact":
            continue
        package = packages.get(message["package_id"])
        if package is None:
            raise RuntimeError("artifact package is absent from actual Cargo metadata")
        target = message["target"]
        if target not in package["targets"]:
            raise RuntimeError("artifact target/src_path differs from actual package metadata")
        features = message["features"]
        if features != sorted(set(features)) or not set(features) <= set(package["features"]):
            raise RuntimeError("artifact features are not canonical declared features")
        profile = message["profile"]
        library_files, aliases = libraries(message, target_dir)
        publication_aliases.extend(aliases)
        if not library_files:
            continue
        if profile["test"] is not False:
            raise RuntimeError("a test executable cannot substitute a library dependency")
        identities = []
        for real in library_files:
            if not real.is_relative_to(target_dir):
                raise RuntimeError("a Cargo library escaped the actual target directory")
            name = real.name
            digest = sha(real)
            if name in files:
                raise RuntimeError("duplicate library filename in the actual artifact graph")
            with real.open("rb") as handle:
                magic = handle.read(8)
            if real.suffix == ".rlib" and magic != b"!<arch>\n":
                raise RuntimeError("a required Rust library is not an actual archive")
            if real.suffix == ".so" and magic[:4] != b"\x7fELF":
                raise RuntimeError("a proc-macro library is not an actual ELF")
            link = stage / name
            shutil.copyfile(real, link)
            if sha(link) != digest:
                raise RuntimeError("staged real artifact differs from its source")
            files[name] = {"source": str(real), "path": str(link), "bytes": real.stat().st_size,
                           "sha256": digest, "package_id": package["id"]}
            identities.append(name)
        primary = next((f for f in library_files if f.suffix in {".rlib", ".so"}), None)
        if primary is None:
            raise RuntimeError("a standalone metadata file cannot replace a real library")
        suffix = primary.stem.rsplit("-", 1)[-1]
        if re.fullmatch("[0-9a-f]{16}", suffix) is None:
            raise RuntimeError("unexpected Cargo library identity")
        fingerprint = primary.parent.parent / ".fingerprint" / (package["name"] + "-" + suffix) / ("lib-" + target["name"] + ".json")
        recorded = json.loads(fingerprint.read_text())
        if json.loads(recorded["features"]) != features:
            raise RuntimeError("real Cargo fingerprint features disagree with compiler-artifact")
        unit = {"package_id": package["id"], "target": target, "features": features,
                "profile": profile, "files": identities, "fingerprint_sha256": sha(fingerprint)}
        require(type(message.get("fresh")) is bool, "actual Cargo freshness is missing")
        unit["fresh"] = message["fresh"]
        units.append(unit)
        name = target["name"]
        if name in direct and package["id"] == wanted[name]:
            rlibs = [f for f in library_files if f.suffix == ".rlib"]
            expected = {"opt_level": "0", "debuginfo": 0, "debug_assertions": True,
                        "overflow_checks": True, "test": False}
            if len(rlibs) != 1 or any(profile.get(k) != v for k, v in expected.items()):
                raise RuntimeError(f"wrong actual direct-library profile: {name}")
            direct[name].append({"path": str(stage / rlibs[0].name), "unit": unit})
    if {p.name for p in stage.iterdir()} != set(files):
        raise RuntimeError("missing or extra files in the isolated complete dependency directory")
    chosen = {}
    for name, choices in direct.items():
        if len(choices) != 1:
            raise RuntimeError(f"missing or ambiguous actual direct artifact: {name}")
        chosen[name] = choices[0]
    if chosen["codex_utils_string"]["unit"]["features"] != (["hia-native"] if native else []):
        raise RuntimeError("actual production owner feature dispatch is wrong")
    return {"direct": chosen, "files": files, "units": units,
            "native_paths": sorted(native_paths), "artifact_jsonl_sha256": sha(path),
            "publication_aliases": publication_aliases,
            "stage": str(stage), "actual_cargo_build_succeeded": True}


def verify_graph(graph):
    if {p.name for p in Path(graph["stage"]).iterdir()} != set(graph["files"]):
        raise RuntimeError("the isolated complete dependency set changed")
    for record in graph["files"].values():
        if sha(record["path"]) != record["sha256"] or sha(record["source"]) != record["sha256"]:
            raise RuntimeError("a staged or producing dependency changed")
