"""Capture actual library and lib-test units; never infer dev dependencies from a lib."""
import json
from pathlib import Path
import re
import shutil

from .artifacts import libraries
from .common import binding, require, sha, verify
from .original import CRATE, catalog

OWNER = "codex_utils_template"
REQUIRED = frozenset(("pretty_assertions", "diff", "yansi"))
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
    require(len(owners) == 1 and owners[0]["name"] == "codex-utils-template", "actual owner manifest differs")
    owner = owners[0]
    nodes = [n for n in graph["resolve"]["nodes"] if n["id"] == owner["id"]]
    require(len(nodes) == 1 and len(nodes[0]["deps"]) == 1, "unexpected complete owner dependency set")
    dependency = nodes[0]["deps"][0]
    require(dependency["name"] == "pretty_assertions"
            and dependency["dep_kinds"] == [{"kind": "dev", "target": None}],
            "pretty_assertions must be the sole dev dependency")
    expected = catalog()["registry_packages"]
    wanted = {packages[key]["name"].replace("-", "_"): key for key in expected if key in packages}
    require(set(wanted) == REQUIRED and wanted["pretty_assertions"] == dependency["pkg"],
            "the complete locked test dependency closure differs")
    for package in packages.values():
        manifest = Path(package["manifest_path"]).resolve(strict=True)
        require(package["source"] is not None or manifest.is_relative_to(producer),
                "a path dependency escaped the producing checkout")
    return graph, packages, owner, wanted


def capture(cargo, producer, env, native, commands):
    child = env.copy()
    if not native:
        child.pop("CODEX_HIA_NATIVE_LIB_DIR", None)
    args = [cargo, "build", "--locked", "--no-default-features", "--jobs=1", "-p",
            "codex-utils-template", "--lib", "--tests", "--message-format=json-render-diagnostics"]
    if native:
        args += ["--features", "hia-native"]
    return commands.run("cargo-native" if native else "cargo-default", args,
                        cwd=producer / "codex-rs", env=child, jsonl=True)


def regular(path, target_dir):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and not path.is_symlink()
            and path.resolve(strict=True) == path and path.is_relative_to(target_dir),
            "an actual compiler output escaped the target directory")
    return path


def fingerprint(primary, package, target, features, *, test):
    suffix = primary.stem.rsplit("-", 1)[-1]
    require(re.fullmatch(r"[0-9a-f]{16}", suffix) is not None,
            "the actual library/test output lacks a unique Cargo suffix")
    kind = "test-lib-" if test else "lib-"
    base = primary.parent.parent / ".fingerprint" / (package["name"] + "-" + suffix) / (kind + target["name"])
    body = json.loads(base.with_suffix(".json").read_bytes())
    require(json.loads(body["features"]) == features, "actual fingerprint features disagree with Cargo")
    require(re.fullmatch(rb"[0-9a-f]{16}", base.read_bytes()) is not None,
            "actual fingerprint identity is missing or malformed")
    return {"identity_file": binding(base), "json_file": binding(base.with_suffix(".json"))}


def admit(path, packages, owner, dependencies, target_dir, stage, *, native):
    messages = [json.loads(line) for line in path.read_text().splitlines()]
    endings = [m for m in messages if m.get("reason") == "build-finished"]
    require(len(endings) == 1 and endings[0].get("success") is True and messages[-1] == endings[0],
            "Cargo must emit exactly one final successful build-finished record")
    stage.mkdir()
    wanted = {**dependencies, OWNER: owner["id"]}
    direct = {name: [] for name in wanted}
    files, units, tests, auxiliary, aliases, builds = {}, [], [], [], [], []
    for message in messages:
        if message.get("reason") == "build-script-executed":
            require(message["package_id"] == owner["id"], "unexpected build script in the scoped graph")
            builds.append(message)
        if message.get("reason") != "compiler-artifact":
            continue
        package = packages.get(message["package_id"])
        require(package is not None, "artifact package is absent from real metadata")
        target, features, profile = (message[key] for key in ("target", "features", "profile"))
        require(target in package["targets"] and Path(message["manifest_path"]).resolve()
                == Path(package["manifest_path"]).resolve(), "artifact target or manifest differs from metadata")
        require(features == sorted(set(features)) and set(features) <= set(package["features"]),
                "artifact features are not canonical declared features")
        require(type(message.get("fresh")) is bool, "actual Cargo freshness is missing")
        if profile["test"]:
            require(package["id"] == owner["id"] and target["kind"] == ["lib"]
                    and target["name"] == OWNER and message.get("executable"),
                    "unexpected test target in complete owner graph")
            require(all(profile.get(k) == v for k, v in {**PROFILE, "test": True}.items()),
                    "actual lib-test profile differs")
            binary = regular(message["executable"], target_dir)
            require(message["filenames"] == [str(binary)], "lib-test output is not unambiguous")
            with binary.open("rb") as stream:
                require(stream.read(4) == b"\x7fELF", "lib-test is not an actual ELF")
            tests.append({"package_id": package["id"], "target": target, "features": features,
                "profile": profile, "fresh": message["fresh"], "executable": binding(binary),
                "fingerprint": fingerprint(binary, package, target, features, test=True)})
            continue
        library_files, observed_aliases = libraries(message, target_dir)
        aliases.extend(observed_aliases)
        if not library_files:
            require(package["id"] == owner["id"] and target["kind"] == ["custom-build"],
                    "unrecognized nonlibrary compilation unit")
            require(message["filenames"], "build-script compiler artifact has no outputs")
            auxiliary.append({"package_id": package["id"], "target": target, "features": features,
                "profile": profile, "fresh": message["fresh"],
                "files": [binding(regular(name, target_dir)) for name in message["filenames"]]})
            continue
        name = target["name"]
        require(name in wanted and package["id"] == wanted[name] and target["kind"] == ["lib"],
                "unexpected library outside the complete four-unit graph")
        require(all(profile.get(k) == value for k, value in PROFILE.items()),
                "actual ordinary library profile differs: " + name)
        identities = []
        for real in library_files:
            require(real.name not in files, "duplicate actual artifact filename")
            require(real.suffix in {".rlib", ".rmeta"}, "unexpected template dependency artifact kind")
            with real.open("rb") as stream:
                require(real.suffix != ".rlib" or stream.read(8) == b"!<arch>\n", "rlib is not an archive")
            digest = sha(real)
            copied = stage / real.name
            shutil.copyfile(real, copied)
            require(sha(copied) == digest, "staged actual artifact bytes differ")
            files[real.name] = {"source": str(real), "path": str(copied), "bytes": real.stat().st_size,
                                "sha256": digest, "package_id": package["id"]}
            identities.append(real.name)
        rlibs = [p for p in library_files if p.suffix == ".rlib"]
        require(len(rlibs) == 1, "ordinary unit must contain exactly one real rlib")
        unit = {"package_id": package["id"], "target": target, "features": features, "profile": profile,
                "files": identities, "fresh": message["fresh"],
                "fingerprint": fingerprint(rlibs[0], package, target, features, test=False)}
        units.append(unit)
        direct[name].append({"path": str(stage / rlibs[0].name), "unit": unit})
    require(all(len(choices) == 1 for choices in direct.values()), "missing or ambiguous actual library unit")
    chosen = {name: rows[0] for name, rows in direct.items()}
    require(len(units) == 4 and len(tests) == 1 and len(auxiliary) == 1 and len(builds) == 1,
            "the complete ordinary/test/build-script graph differs")
    expected_features = ["hia-native"] if native else []
    require(chosen[OWNER]["unit"]["features"] == tests[0]["features"] == auxiliary[0]["features"]
            == expected_features, "real owner/test/build-script feature dispatch differs")
    expected_links = ["static=codex_hia_template_parse", "static=codex_hia_template_render",
                      "static=codex_hia_template_index"] if native else []
    require(builds[0]["linked_libs"] == expected_links, "real Cargo native linkage differs")
    require({p.name for p in stage.iterdir()} == set(files), "staged graph has missing or extra files")
    return {"direct": chosen, "files": files, "units": units, "owner_test": tests[0],
            "build_script_compilations": auxiliary, "build_script_results": builds,
            "native_paths": sorted(set(builds[0]["linked_paths"])),
            "publication_aliases": aliases, "artifact_jsonl": binding(path),
            "stage": str(stage), "actual_cargo_build_succeeded": True}


def verify_graph(graph):
    require({p.name for p in Path(graph["stage"]).iterdir()} == set(graph["files"]),
            "the staged dependency set changed")
    for record in graph["files"].values():
        for name in ("source", "path"):
            require(sha(record[name]) == record["sha256"]
                    and Path(record[name]).stat().st_size == record["bytes"], "a real dependency changed")
    for unit in [*graph["units"], graph["owner_test"]]:
        for record in unit["fingerprint"].values():
            verify(record)
    verify(graph["owner_test"]["executable"])
    verify(graph["artifact_jsonl"])
    for unit in graph["build_script_compilations"]:
        for record in unit["files"]:
            verify(record)
