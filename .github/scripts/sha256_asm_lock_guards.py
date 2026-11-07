"""Accept only the fixed Linux AArch64 SHA-256 backend dependency delta."""

from copy import deepcopy
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import tomllib


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
ASM_VERSION = "0.6.4"
ASM_CHECKSUM = "b845214d6175804686b2bd482bcffe96651bb2d1200742b712003504a2dac1ab"
SHA2_CHECKSUM = "a7507d819769d01a365ab707794a4084392c824f54a7a6a7862f8c3d0892b283"
CC_CHECKSUM = "47b26a0954ae34af09b50f0de26458fa95369a0d478d8236d3f93082b219bd29"
SHAPE_CHECKSUM = "654fd162ca9dc781e16977a156bbb4985420404b69dfe43f0645be40d4345df7"
CONDITION = 'cfg(all(target_arch = "aarch64", target_os = "linux"))'
FACT_KEY = "sha2-asm_0.6.4"
FACT = {
    "dependencies": [{"kind": "build", "name": "cc", "req": "^1.0"}],
    "features": {},
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def unique(items, key):
    result = {key(item): item for item in items}
    require(len(result) == len(items), "DUPLICATE_IDENTITY")
    return result


def one_package(packages, name, version):
    matches = [p for p in packages if p["name"] == name and p["version"] == version]
    require(len(matches) == 1, "PACKAGE_ROSTER_MISMATCH")
    return matches[0]


def canonical_lock(value):
    value = deepcopy(value)
    for package in value["package"]:
        if "dependencies" in package:
            require(
                len(set(package["dependencies"])) == len(package["dependencies"]),
                "DUPLICATE_LOCK_EDGE",
            )
            package["dependencies"].sort()
    value["package"].sort(key=lambda p: (p["name"], p["version"], p.get("source", "")))
    unique(value["package"], lambda p: (p["name"], p["version"], p.get("source", "")))
    return value


def cargo_guard(before_raw, after_raw):
    before, after = [tomllib.loads(raw.decode()) for raw in (before_raw, after_raw)]
    expected = deepcopy(before)
    require(
        not any(p["name"] == "sha2-asm" for p in expected["package"]),
        "ASM_ALREADY_PRESENT",
    )
    sha2 = one_package(expected["package"], "sha2", "0.10.9")
    cc = one_package(expected["package"], "cc", "1.2.55")
    for package, checksum in ((sha2, SHA2_CHECKSUM), (cc, CC_CHECKSUM)):
        require(
            package["source"] == REGISTRY and package["checksum"] == checksum,
            "BASE_PACKAGE_IDENTITY_MISMATCH",
        )
    sha2["dependencies"].append("sha2-asm")
    expected["package"].append(
        {
            "name": "sha2-asm",
            "version": ASM_VERSION,
            "source": REGISTRY,
            "checksum": ASM_CHECKSUM,
            "dependencies": ["cc"],
        }
    )
    require(
        canonical_lock(after) == canonical_lock(expected), "UNRELATED_CARGO_GRAPH_DRIFT"
    )
    delta = list(
        difflib.ndiff(
            before_raw.decode().splitlines(keepends=True),
            after_raw.decode().splitlines(keepends=True),
        )
    )
    additions = [line[2:] for line in delta if line.startswith("+ ")]
    removals = [line[2:] for line in delta if line.startswith("- ")]
    expected_lines = [
        "",
        "[[package]]",
        'name = "sha2-asm"',
        'version = "0.6.4"',
        'source = "' + REGISTRY + '"',
        'checksum = "' + ASM_CHECKSUM + '"',
        "dependencies = [",
        ' "cc",',
        "]",
        ' "sha2-asm",',
    ]
    require(
        not removals
        and sorted(additions) == sorted(line + "\n" for line in expected_lines),
        "UNRELATED_CARGO_TEXT_DRIFT",
    )
    return {
        "new_registry_package": "sha2-asm@0.6.4",
        "new_package_checksum": ASM_CHECKSUM,
        "added_existing_package_edge": "sha2@0.10.9 -> sha2-asm@0.6.4",
        "new_package_build_edge": "sha2-asm@0.6.4 -> cc@1.2.55",
        "all_old_package_versions_sources_checksums_and_other_edges_preserved": True,
        "all_old_lines_preserved": True,
        "package_count_before": len(before["package"]),
        "package_count_after": len(after["package"]),
    }


def canonical_metadata(value):
    value = deepcopy(value)
    for package in value["packages"]:
        package["dependencies"].sort(
            key=lambda dependency: json.dumps(dependency, sort_keys=True)
        )
    value["packages"].sort(key=lambda package: package["id"])
    unique(value["packages"], lambda package: package["id"])
    for node in value["resolve"]["nodes"]:
        node["dependencies"].sort()
        node["deps"].sort(key=lambda dependency: json.dumps(dependency, sort_keys=True))
    value["resolve"]["nodes"].sort(key=lambda node: node["id"])
    unique(value["resolve"]["nodes"], lambda node: node["id"])
    return value


def metadata_guard(before, after):
    expected = deepcopy(before)
    packages = expected["packages"]
    require(
        not any(p["name"] == "sha2-asm" for p in packages),
        "ASM_METADATA_ALREADY_PRESENT",
    )
    contracts = one_package(packages, "codex-hepta-contracts", "0.0.0")
    sha2 = one_package(packages, "sha2", "0.10.9")
    cc = one_package(packages, "cc", "1.2.55")
    require(
        contracts["source"] is None and sha2["source"] == cc["source"] == REGISTRY,
        "METADATA_SOURCE_MISMATCH",
    )
    declared = [dep for dep in contracts["dependencies"] if dep["name"] == "sha2"]
    require(
        len(declared) == 1
        and declared[0]["target"] is None
        and declared[0]["features"] == [],
        "BASE_SHA2_DECLARATION_CHANGED",
    )
    dependency = deepcopy(declared[0])
    dependency.update(target=CONDITION, features=["asm"])
    contracts["dependencies"].append(dependency)
    shape_raw = Path(__file__).with_name("sha256-asm-metadata-shape.json").read_bytes()
    require(
        hashlib.sha256(shape_raw).hexdigest() == SHAPE_CHECKSUM,
        "OFFICIAL_METADATA_SHAPE_CHANGED",
    )
    asm = json.loads(shape_raw)
    registry_root = PurePosixPath(sha2["manifest_path"]).parent.parent
    require(
        registry_root.is_absolute() and ".." not in registry_root.parts,
        "INVALID_REGISTRY_ROOT",
    )
    asm_root = registry_root / "sha2-asm-0.6.4"
    asm["manifest_path"] = str(asm_root / "Cargo.toml")
    for target in asm["targets"]:
        target["src_path"] = target["src_path"].replace(
            "__SHA2_ASM_ROOT__", str(asm_root)
        )
    packages.append(asm)
    nodes = unique(expected["resolve"]["nodes"], lambda node: node["id"])
    edge = [dep for dep in nodes[contracts["id"]]["deps"] if dep["pkg"] == sha2["id"]]
    require(
        len(edge) == 1 and edge[0]["dep_kinds"] == [{"kind": None, "target": None}],
        "BASE_RESOLVED_SHA2_EDGE_CHANGED",
    )
    edge[0]["dep_kinds"].append({"kind": None, "target": CONDITION})
    sha_node = nodes[sha2["id"]]
    require(
        not {"asm", "sha2-asm"}.intersection(sha_node["features"]),
        "ASM_FEATURES_ALREADY_ENABLED",
    )
    sha_node["features"] = sorted(sha_node["features"] + ["asm", "sha2-asm"])
    sha_node["dependencies"].append(asm["id"])
    asm_declaration = [dep for dep in sha2["dependencies"] if dep["name"] == "sha2-asm"]
    require(
        len(asm_declaration) == 1
        and asm_declaration[0]["optional"] is True
        and asm_declaration[0]["kind"] is None,
        "BASE_ASM_DECLARATION_CHANGED",
    )
    sha_node["deps"].append(
        {
            "name": "sha2_asm",
            "pkg": asm["id"],
            "dep_kinds": [{"kind": None, "target": asm_declaration[0]["target"]}],
        }
    )
    expected["resolve"]["nodes"].append(
        {
            "id": asm["id"],
            "dependencies": [cc["id"]],
            "deps": [
                {
                    "name": "cc",
                    "pkg": cc["id"],
                    "dep_kinds": [{"kind": "build", "target": None}],
                }
            ],
            "features": [],
        }
    )
    require(
        canonical_metadata(after) == canonical_metadata(expected),
        "UNRELATED_METADATA_DRIFT",
    )
    return {
        "target_condition": CONDITION,
        "new_package": "sha2-asm@0.6.4",
        "official_metadata_shape_sha256": SHAPE_CHECKSUM,
        "only_existing_feature_additions": {"sha2@0.10.9": ["asm", "sha2-asm"]},
        "all_other_metadata_fields_preserved": True,
        "metadata_union_is_not_platform_isolation_proof": True,
    }


def module_guard(before_raw, after_raw):
    before, after = [json.loads(raw) for raw in (before_raw, after_raw)]
    expected = deepcopy(before)
    facts = expected["facts"]["@@rules_rs+//rs:extensions.bzl%crate"]
    require(FACT_KEY not in facts, "ASM_FACT_ALREADY_PRESENT")
    fact_text = json.dumps(FACT, sort_keys=True, separators=(",", ":"))
    facts[FACT_KEY] = fact_text
    require(after == expected, "UNRELATED_MODULE_LOCK_DRIFT")
    delta = list(
        difflib.ndiff(
            before_raw.decode().splitlines(keepends=True),
            after_raw.decode().splitlines(keepends=True),
        )
    )
    additions = [line[2:] for line in delta if line.startswith("+ ")]
    removals = [line[2:] for line in delta if line.startswith("- ")]
    expected_line = (
        "      " + json.dumps(FACT_KEY) + ": " + json.dumps(fact_text) + ",\n"
    )
    require(
        not removals and additions == [expected_line], "UNRELATED_MODULE_TEXT_DRIFT"
    )
    return {
        "added_fact": {FACT_KEY: fact_text},
        "all_existing_facts_and_other_fields_unchanged": True,
        "all_old_lines_preserved": True,
        "rules_rs_external_hyper_and_pin_utils_facts_unchanged": True,
    }
