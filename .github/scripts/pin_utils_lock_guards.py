"""Reject unrelated Bazel lock facts in the fixed five-version proposal."""

from copy import deepcopy
import base64
import hashlib
import io
import json
import tarfile
import tomllib
import urllib.request

from pin_utils_proposal_evidence import require


def external_source_guard(spec, source_raw, archive_raw):
    retained = spec["retained_external_module_registry_facts"]
    for label, raw in (("source_json", source_raw), ("archive", archive_raw)):
        require(len(raw) == retained[label + "_bytes"]
                and hashlib.sha256(raw).hexdigest() == retained[label + "_sha256"],
                "EXTERNAL_SOURCE_IDENTITY_MISMATCH")
    source = json.loads(source_raw)
    require(source["url"] == retained["archive_url"]
            and source["strip_prefix"] == retained["strip_prefix"]
            and source["integrity"] == "sha256-" + base64.b64encode(
                bytes.fromhex(retained["archive_sha256"])).decode(), "EXTERNAL_ARCHIVE_BINDING_MISMATCH")
    selected = {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
        for member in archive:
            prefix = retained["strip_prefix"] + "/"
            if not member.name.startswith(prefix):
                continue
            name = member.name.removeprefix(prefix)
            if name not in retained["source_files"]:
                continue
            require(member.isfile() and name not in selected, "INVALID_EXTERNAL_SOURCE_MEMBER")
            expected = retained["source_files"][name]
            require(member.size == expected["bytes"], "EXTERNAL_SOURCE_FILE_SIZE_MISMATCH")
            raw = archive.extractfile(member).read()
            require(hashlib.sha256(raw).hexdigest() == expected["sha256"], "EXTERNAL_SOURCE_FILE_HASH_MISMATCH")
            selected[name] = raw
    require(selected.keys() == retained["source_files"].keys(), "INCOMPLETE_EXTERNAL_SOURCE_PROOF")
    require(selected["MODULE.bazel"].count(
        b'crate.from_cargo(\n    name = "rrprd",\n    cargo_lock = "//rs/private/prost:Cargo.lock",\n'
        b'    cargo_toml = "//rs/private/prost:Cargo.toml",') == 1, "EXTERNAL_PROST_HUB_MISMATCH")
    lock = selected[retained["cargo_lock_path"]]
    require(hashlib.sha256(lock).hexdigest() == retained["cargo_lock_sha256"]
            and hashlib.sha256(selected[retained["normalization_source"]]).hexdigest()
            == retained["normalization_source_sha256"], "EXTERNAL_PROST_SOURCE_MISMATCH")
    changed_keys = {crate["name"] + "_" + crate["version"] for crate in spec["crates"]}
    changed_keys.add("pin-utils_" + spec["pin_utils"]["version"])
    overlap = {package["name"] + "_" + package["version"]: package
               for package in tomllib.loads(lock.decode())["package"]
               if package["name"] + "_" + package["version"] in changed_keys}
    require(overlap.keys() == retained["facts_sha256"].keys(), "EXTERNAL_PROST_OVERLAP_MISMATCH")
    require(overlap["pin-utils_" + spec["pin_utils"]["version"]] == spec["pin_utils"],
            "EXTERNAL_PIN_SOURCE_MISMATCH")
    hyper = next(crate for crate in spec["crates"] if crate["name"] == "hyper")
    external_hyper = overlap["hyper_" + hyper["version"]]
    require(external_hyper["checksum"] == hyper["checksum"]
            and external_hyper["source"] == spec["pin_utils"]["source"]
            and "pin-utils" in external_hyper["dependencies"], "EXTERNAL_HYPER_SOURCE_MISMATCH")
    return {"source_json_sha256": retained["source_json_sha256"],
            "archive_sha256": retained["archive_sha256"], "source_files": retained["source_files"],
            "prost_hub_and_shared_registry_sources_verified": True}


def verify_external_source(spec):
    retained = spec["retained_external_module_registry_facts"]
    payloads = []
    for label in ("source_json", "archive"):
        with urllib.request.urlopen(retained[label + "_url"], timeout=60) as response:
            require(response.status == 200, "EXTERNAL_SOURCE_HTTP_ERROR")
            payloads.append(response.read(retained[label + "_bytes"] + 1))
    return external_source_guard(spec, *payloads)


def normalized_fact(raw, *, path_fact=False):
    fact = json.loads(raw)
    expected_fields = {"dependencies", "features"}
    if path_fact:
        expected_fields.add("strip_prefix")
    require(set(fact) == expected_fields, "UNEXPECTED_CRATE_FACT_FIELDS")
    if path_fact:
        require(fact.pop("strip_prefix") == "", "UNEXPECTED_PATH_STRIP_PREFIX")
    dependencies = []
    for original in fact["dependencies"]:
        dependency = deepcopy(original)
        dependency.setdefault("kind", "normal")
        dependency.setdefault("target", None)
        dependency.setdefault("default_features", True)
        dependency.setdefault("optional", False)
        dependency.setdefault("features", [])
        dependency["features"].sort()
        requirement = dependency["req"]
        if requirement and requirement[0].isdigit():
            dependency["req"] = "^" + requirement
        dependencies.append(dependency)
    fact["dependencies"] = sorted(dependencies, key=lambda item: json.dumps(item, sort_keys=True))
    fact["features"] = {name: sorted(values) for name, values in fact["features"].items()}
    return fact


def module_guard(before_raw, after_raw, spec):
    before, after = (json.loads(raw) for raw in (before_raw, after_raw))
    section = "@@rules_rs+//rs:extensions.bzl%crate"
    original = before["facts"][section]
    generated = after["facts"][section]
    old_keys = {crate["name"] + "_" + crate["version"] for crate in spec["crates"]}
    pin_key = "pin-utils_" + spec["pin_utils"]["version"]
    old_keys.add(pin_key)
    retained = spec["retained_external_module_registry_facts"]
    retained_keys = set(retained["facts_sha256"])
    hyper = next(crate for crate in spec["crates"] if crate["name"] == "hyper")
    require(retained_keys == {"hyper_" + hyper["version"], pin_key}, "MODULE_RETAINED_FACT_ROSTER_MISMATCH")
    require(before["registryFileHashes"][retained["source_json_url"]] == retained["source_json_sha256"],
            "MODULE_EXTERNAL_SOURCE_MISMATCH")
    for key, sha256 in retained["facts_sha256"].items():
        require(hashlib.sha256(original[key].encode()).hexdigest() == sha256
                and generated.get(key) == original[key], "MODULE_EXTERNAL_FACT_CHANGED")
    removed_keys = old_keys - retained_keys
    new_keys = {"path+crates/" + crate["vendor"].removeprefix("codex-rs/") + "_" + crate["name"]
                for crate in spec["crates"]}
    require(len(old_keys) == 6 and len(new_keys) == 5, "MODULE_CRATE_ROSTER_MISMATCH")
    require(original.keys() - generated.keys() == removed_keys, "MODULE_REMOVED_FACTS_MISMATCH")
    require(generated.keys() - original.keys() == new_keys, "MODULE_ADDED_FACTS_MISMATCH")
    require(normalized_fact(original[pin_key]) == {"dependencies": [], "features": {}},
            "UNEXPECTED_PIN_UTILS_FACT")
    checks = []
    for crate in spec["crates"]:
        old_key = crate["name"] + "_" + crate["version"]
        new_key = "path+crates/" + crate["vendor"].removeprefix("codex-rs/") + "_" + crate["name"]
        expected = normalized_fact(original[old_key])
        removed = [dependency for dependency in expected["dependencies"] if dependency["name"] == "pin-utils"]
        require(len(removed) == 1, "MODULE_PIN_EDGE_MISMATCH")
        expected["dependencies"].remove(removed[0])
        # Pinned rules_rs cargo_toml_dependencies emits normal/build metadata for
        # path dependencies. Its resolver also ignores registry development
        # dependencies; the vendored manifests and tests keep those entries.
        development = [dependency for dependency in expected["dependencies"] if dependency["kind"] == "dev"]
        expected["dependencies"] = [dependency for dependency in expected["dependencies"]
                                    if dependency["kind"] != "dev"]
        if crate["name"] == "loom":
            expected["features"]["pin-utils"] = []
        if crate["name"] == "hyper":
            expected["features"]["http1"].remove("dep:pin-utils")
        require(normalized_fact(generated[new_key], path_fact=True) == expected, "MODULE_CRATE_FACT_DRIFT")
        checks.append({"old_key": old_key, "new_key": new_key,
                       "normal_and_build_dependency_and_feature_semantics_preserved_except_pin_removal": True,
                       "development_metadata_omitted_by_pinned_rules_rs_path_representation": len(development),
                       "path_strip_prefix_empty": True})
    for key in removed_keys:
        del original[key]
    for key in new_keys:
        del generated[key]
    require(before == after, "UNRELATED_MODULE_LOCK_DRIFT")
    return {"removed_registry_facts": sorted(removed_keys), "added_path_facts": sorted(new_keys),
            "external_tooling_registry_facts_retained_byte_identical": retained["facts_sha256"],
            "crate_checks": checks, "all_other_module_fields_identical": True}
