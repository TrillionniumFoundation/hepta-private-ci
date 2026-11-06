"""Accept only the official vodozemac patch and its existing zeroize closure."""

from copy import deepcopy
import hashlib
import io
import json
import re
import tarfile
import tomllib

from vodozemac_proposal_evidence import identity, require


def verify_archives(archives, spec):
    manifests = {}
    licenses = {}
    for crate in spec["crates"]:
        raw = archives[crate["version"]]
        require(
            len(raw) == crate["archive_bytes"]
            and identity(raw)["sha256"] == crate["checksum"],
            "OFFICIAL_ARCHIVE_IDENTITY_MISMATCH",
        )
        wanted = {"Cargo.toml", "Cargo.toml.orig", ".cargo_vcs_info.json", "LICENSE"}
        files = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            prefix = "vodozemac-" + crate["version"] + "/"
            for member in archive:
                name = member.name.removeprefix(prefix)
                if member.name != prefix + name or name not in wanted:
                    continue
                require(
                    member.isfile()
                    and name not in files
                    and member.size <= 1024 * 1024,
                    "INVALID_UPSTREAM_SOURCE_MEMBER",
                )
                files[name] = archive.extractfile(member).read()
                require(len(files[name]) == member.size, "TRUNCATED_UPSTREAM_SOURCE")
        require(files.keys() == wanted, "INCOMPLETE_UPSTREAM_SOURCE")
        require(
            identity(files["Cargo.toml"]) == crate["manifest"]
            and identity(files["Cargo.toml.orig"]) == crate["original_manifest"],
            "UPSTREAM_MANIFEST_IDENTITY_MISMATCH",
        )
        require(
            json.loads(files[".cargo_vcs_info.json"]) == crate["vcs"],
            "UPSTREAM_COMMIT_MISMATCH",
        )
        manifests[crate["version"]] = tomllib.loads(files["Cargo.toml"].decode())
        licenses[crate["version"]] = files["LICENSE"]
    expected = deepcopy(manifests["0.11.1"])
    require(expected["package"]["rust-version"] == "1.89", "UPSTREAM_MSRV_MISMATCH")
    expected["package"]["version"] = "0.11.2"
    for name in spec["required_zeroize_features"]:
        feature_list = expected["dependencies"][name].setdefault("features", [])
        require("zeroize" not in feature_list, "UPSTREAM_FEATURE_ALREADY_ENABLED")
        feature_list.append("zeroize")
    require(manifests["0.11.2"] == expected, "UNEXPECTED_UPSTREAM_MANIFEST_DRIFT")
    require(licenses["0.11.1"] == licenses["0.11.2"], "UPSTREAM_LICENSE_CHANGED")
    require(
        spec["crates"][1]["vcs"]["git"]["sha1"]
        == spec["upstream"]["release_git_commit"],
        "RELEASE_COMMIT_BINDING_MISMATCH",
    )
    return {
        "official_archives_verified": {
            c["version"]: c["checksum"] for c in spec["crates"]
        },
        "only_manifest_changes": "patch version and six declared zeroize features",
        "license_unchanged": identity(licenses["0.11.1"]),
        "rust_version_unchanged": "1.89",
    }


def graph_guard(before_raw, after_raw, spec):
    before, after = (tomllib.loads(raw.decode()) for raw in (before_raw, after_raw))
    expected = deepcopy(before)
    selected = [p for p in expected["package"] if p["name"] == "vodozemac"]
    require(selected == [spec["original_package"]], "ORIGINAL_PACKAGE_MISMATCH")
    require(
        [p for p in expected["package"] if p["name"] == "zeroize"]
        == [spec["existing_zeroize"]],
        "EXISTING_ZEROIZE_IDENTITY_MISMATCH",
    )
    selected[0]["version"] = "0.11.2"
    selected[0]["checksum"] = spec["crates"][1]["checksum"]
    for edge in spec["required_new_lock_edges"]:
        packages = [
            p
            for p in expected["package"]
            if (p["name"], p["version"]) == (edge["name"], edge["version"])
        ]
        require(
            len(packages) == 1
            and edge["dependency"] not in packages[0].get("dependencies", []),
            "ORIGINAL_OPTIONAL_EDGE_MISMATCH",
        )
        packages[0].setdefault("dependencies", []).append(edge["dependency"])

    def canonical(lock):
        result = deepcopy(lock)
        for package in result["package"]:
            if "dependencies" in package:
                package["dependencies"].sort()
        result["package"].sort(
            key=lambda p: (p["name"], p["version"], p.get("source", ""))
        )
        return result

    require(canonical(after) == canonical(expected), "UNEXPECTED_LOCK_GRAPH_DRIFT")
    return {
        "package_count_unchanged": len(before["package"]),
        "only_package_identity_change": {
            "name": "vodozemac",
            "before": "0.11.1",
            "after": "0.11.2",
        },
        "added_existing_zeroize_edges": spec["required_new_lock_edges"],
        "all_other_versions_sources_checksums_fields_and_edges_identical": True,
        "workspace_and_vendor_packages_unchanged": True,
    }


def module_guard(before_raw, after_raw, spec):
    before, after = (json.loads(raw) for raw in (before_raw, after_raw))
    section = "@@rules_rs+//rs:extensions.bzl%crate"
    original, generated = before["facts"][section], after["facts"][section]
    require(
        hashlib.sha256(original["vodozemac_0.11.1"].encode()).hexdigest()
        == spec["original_vodozemac_fact_sha256"],
        "ORIGINAL_MODULE_FACT_MISMATCH",
    )
    require(
        original.keys() - generated.keys() == {"vodozemac_0.11.1"}
        and generated.keys() - original.keys() == {"vodozemac_0.11.2"},
        "MODULE_FACT_ROSTER_DRIFT",
    )
    expected = json.loads(original["vodozemac_0.11.1"])
    for name in spec["required_zeroize_features"]:
        dependencies = [
            d
            for d in expected["dependencies"]
            if d["name"] == name and d.get("kind", "normal") == "normal"
        ]
        require(len(dependencies) == 1, "MODULE_DEPENDENCY_IDENTITY_MISMATCH")
        features = dependencies[0].setdefault("features", [])
        require("zeroize" not in features, "MODULE_FEATURE_ALREADY_ENABLED")
        features.append("zeroize")
    require(
        json.loads(generated["vodozemac_0.11.2"]) == expected,
        "MODULE_VODOZEMAC_FACT_DRIFT",
    )
    retained = spec["retained_external_module_registry_facts"]
    require(
        before["registryFileHashes"][retained["source_json_url"]]
        == retained["source_json_sha256"],
        "EXTERNAL_RULES_SOURCE_CHANGED",
    )
    for key, digest in retained["facts_sha256"].items():
        require(
            hashlib.sha256(original[key].encode()).hexdigest() == digest
            and generated[key] == original[key],
            "EXTERNAL_TOOLING_FACT_CHANGED",
        )
    del original["vodozemac_0.11.1"]
    del generated["vodozemac_0.11.2"]
    require(before == after, "UNRELATED_MODULE_LOCK_DRIFT")
    return {
        "only_removed_fact": "vodozemac_0.11.1",
        "only_added_fact": "vodozemac_0.11.2",
        "only_dependency_metadata_change": "six zeroize feature additions",
        "external_tooling_facts_retained_byte_identical": retained["facts_sha256"],
        "all_other_module_fields_identical": True,
    }


def feature_guard(raw, spec):
    rows = {}
    for line in raw.decode("utf-8", "strict").splitlines():
        match = re.fullmatch(
            r"([A-Za-z0-9_-]+) v([^ |]+)(?: [^|]*)?\|(.*?)(?: \(\*\))?", line
        )
        if match:
            key = (match[1], match[2])
            rows.setdefault(key, set()).add(
                frozenset(filter(None, match[3].split(",")))
            )
    require(
        ("vodozemac", "0.11.2") in rows
        and not any(
            name == "vodozemac" and version != "0.11.2" for name, version in rows
        ),
        "RESOLVED_VODOZEMAC_MISMATCH",
    )
    required = {**spec["required_zeroize_features"], "chacha20": "0.10.0"}
    proof = {}
    for name, version in required.items():
        selected = rows.get((name, version), set())
        require(
            selected and all("zeroize" in features for features in selected),
            "ZEROIZE_FEATURE_NOT_RESOLVED",
        )
        proof[name + "@" + version] = sorted(sorted(features) for features in selected)
    return {
        "native_cargo_tree_features": proof,
        "scope": "Declared Cargo tree resolution; not a substitute for complete-head native compilation and tests.",
    }
