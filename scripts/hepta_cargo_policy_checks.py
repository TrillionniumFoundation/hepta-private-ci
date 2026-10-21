#!/usr/bin/env python3
"""Verify the fixed Cargo policy candidate and its independent vendor harness."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads(
    Path(__file__).with_name("hepta_cargo_policy_inventory.json").read_text()
)
VENDORS = INVENTORY["vendors"]
FEATURES = "secret-service/crypto-rust,zbus-secret-service-keyring-store/crypto-rust"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source_hashes(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Source symlink is not permitted: {path}")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def prepare_harness(evidence):
    harness = evidence / "vendor-harness"
    harness.mkdir()
    copied = {}
    for name, vendor in VENDORS.items():
        source = ROOT / "codex-rs/third_party" / vendor["directory"]
        destination = harness / vendor["directory"]
        before = source_hashes(source)
        shutil.copytree(source, destination)
        after = source_hashes(destination)
        if before != after:
            raise ValueError(f"Harness copy differs from input: {name}")
        copied[name] = before
    manifest = '[workspace]\nresolver = "2"\nmembers = ' + json.dumps(
        [item["directory"] for item in VENDORS.values()]
    )
    manifest += "\n\n[patch.crates-io]\n"
    for name, vendor in VENDORS.items():
        manifest += f'{name} = {{ path = "{vendor["directory"]}" }}\n'
    (harness / "Cargo.toml").write_text(manifest)
    shutil.copyfile(ROOT / "codex-rs/Cargo.lock", harness / "Cargo.lock")
    shutil.copyfile(harness / "Cargo.lock", evidence / "harness-seed.Cargo.lock")
    shutil.copyfile(
        ROOT / "codex-rs/rust-toolchain.toml", harness / "rust-toolchain.toml"
    )
    config = harness / ".config"
    config.mkdir()
    (config / "nextest.toml").write_text(
        '[profile.default]\nslow-timeout = { period = "30s", terminate-after = 2 }\n'
        'retries = 1\n[profile.default.junit]\npath = "junit.xml"\n'
        '[profile.local]\nretries = 1\n[profile.local.junit]\npath = "junit.xml"\n'
    )
    (harness / "justfile").write_text(
        'test-doc:\n    cargo test --workspace --doc --locked --features "'
        + FEATURES
        + '" -- --test-threads=1\n\n'
        'fix:\n    cargo clippy --fix --workspace --tests --locked --allow-dirty --allow-no-vcs --features "'
        + FEATURES
        + '"\n'
    )
    write_json(evidence / "harness-source-hashes.json", copied)
    print(
        f"Copied all vendor files byte-for-byte into {harness}; production lock used as resolver seed"
    )


def package_identity(package):
    return package["name"], package["version"], package.get("source")


def normal_closure(metadata):
    packages = {item["id"]: item for item in metadata["packages"]}
    nodes = {item["id"]: item for item in metadata["resolve"]["nodes"]}
    pending = [
        item["id"]
        for item in packages.values()
        if item["name"] in VENDORS and item.get("source") is None
    ]
    visited = set()
    while pending:
        identity = pending.pop()
        if identity in visited:
            continue
        visited.add(identity)
        for edge in nodes[identity]["deps"]:
            if any(kind["kind"] in (None, "build") for kind in edge["dep_kinds"]):
                pending.append(edge["pkg"])
    return {
        package_identity(packages[identity]): nodes[identity]["features"]
        for identity in visited
    }


def verify_graph(evidence):
    production = json.loads((evidence / "metadata.json").read_text())
    harness = json.loads((evidence / "harness-metadata.json").read_text())
    if len(production["workspace_members"]) != 193:
        raise ValueError(
            "Production workspace membership changed from the original 193 packages"
        )
    for name, vendor in VENDORS.items():
        packages = [p for p in production["packages"] if p["name"] == name]
        expected = ROOT / "codex-rs/third_party" / vendor["directory"] / "Cargo.toml"
        if (
            len(packages) != 1
            or packages[0].get("source") is not None
            or Path(packages[0]["manifest_path"]) != expected
        ):
            raise ValueError(
                f"Production graph did not select the exact local patch for {name}"
            )
        if packages[0]["id"] in production["workspace_members"]:
            raise ValueError(f"Vendor was added to production workspace: {name}")
    production_graph = normal_closure(production)
    harness_graph = normal_closure(harness)
    unexpected = sorted(set(harness_graph) - set(production_graph), key=str)
    checksum_maps = []
    for path in (ROOT / "codex-rs/Cargo.lock", evidence / "vendor-harness/Cargo.lock"):
        lock = tomllib.loads(path.read_text())
        checksum_maps.append(
            {
                (p["name"], p["version"], p.get("source")): p.get("checksum")
                for p in lock["package"]
            }
        )
    differences = [
        identity
        for identity in harness_graph
        if checksum_maps[0].get(identity) != checksum_maps[1].get(identity)
    ]
    comparison = {
        "production_workspace_members": len(production["workspace_members"]),
        "production_normal_graph": [
            {"identity": k, "features": v}
            for k, v in sorted(production_graph.items(), key=str)
        ],
        "harness_normal_graph": [
            {"identity": k, "features": v}
            for k, v in sorted(harness_graph.items(), key=str)
        ],
        "harness_packages_absent_from_production_normal_graph": unexpected,
        "checksum_differences": differences,
        "feature_sets_are_recorded_not_claimed_identical": True,
    }
    write_json(evidence / "normal-graph-comparison.json", comparison)
    if unexpected or differences:
        raise ValueError(
            "Harness normal dependency identities/checksums differ from production; review recorded graphs"
        )
    print(
        "Every harness normal/build dependency has the same name/version/source/checksum in the production normal graph"
    )


def verify_list(evidence):
    listed = json.loads((evidence / "vendor-test-list.json").read_text())
    observed = {}
    for suite in listed["rust-suites"].values():
        name = suite["package-name"]
        if name not in VENDORS:
            raise ValueError(f"Unexpected harness test package: {name}")
        for test_name, case in suite["testcases"].items():
            identity = (name, test_name)
            if identity in observed:
                raise ValueError(f"Duplicate harness test: {identity}")
            observed[identity] = case
    expected = {
        (name, case["runtime_name"]): case
        for name, vendor in VENDORS.items()
        for case in vendor["tests"]
    }
    failures = []
    report = []
    for identity, case in expected.items():
        actual = observed.get(identity)
        if case["no_github_actions"]:
            state = "not_executed_original_GITHUB_ACTIONS_guard"
            valid = actual is None or actual["ignored"]
        elif case["ignored"]:
            state = "not_executed_original_ignore"
            valid = actual is not None and actual["ignored"]
        else:
            state = "required_execution"
            valid = (
                actual is not None
                and not actual["ignored"]
                and actual["filter-match"]["status"] == "matches"
            )
        report.append(
            {
                "package": identity[0],
                "test": identity[1],
                "source_status": state,
                "listed": actual,
                "valid": valid,
            }
        )
        if not valid:
            failures.append(identity)
    extra = sorted(set(observed) - set(expected))
    write_json(
        evidence / "vendor-test-inventory-check.json",
        {
            "declared": len(expected),
            "required_execution": 89,
            "original_unexecuted": 11,
            "tests": report,
            "unexpected": extra,
        },
    )
    if failures or extra:
        raise ValueError(
            f"Missing, newly ignored, filtered or unexpected tests: {failures}, {extra}"
        )
    print(
        "100 source tests accounted for: 89 required executions; original 9 ignores and 2 environment guards remain unexecuted"
    )


def verify_lock(evidence):
    packages = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())["package"]
    required = {
        "rustls-webpki": "0.103.16",
        "webpki-roots": "1.0.10",
        "webpki-root-certs": "1.0.10",
        "secret-service": "6.0.0",
        "zbus-secret-service-keyring-store": "1.0.1",
        "i18n-config": "0.4.8",
        "keyring": "4.2.0",
        "age": "0.11.5",
    }
    forbidden = {
        ("basic-toml", "0.1.10"),
        ("zbus_names", "4.3.4"),
        ("zvariant", "5.15.0"),
        ("zvariant_derive", "5.15.0"),
    }
    found = {(p["name"], p["version"]) for p in packages}
    missing = [
        (name, version)
        for name, version in required.items()
        if (name, version) not in found
    ]
    old = sorted(found & forbidden)
    for name, version in required.items():
        if name in ("rustls-webpki", "webpki-roots", "webpki-root-certs") and any(
            p["name"] == name and p["version"] in ("0.103.15", "1.0.9")
            for p in packages
        ):
            old.append((name, "original advisory version"))
    write_json(
        evidence / "lock-package-check.json",
        {"required": required, "missing": missing, "forbidden_present": old},
    )
    if missing or old:
        raise ValueError(
            "Cloud-generated lock has missing replacements or retains an original advisory"
        )
    print(
        "Cloud-generated lock contains all seven advisory replacements and retains keyring 4.2.0"
    )


def verify_results(evidence):
    list_path = evidence / "vendor-test-list.json"
    junit_path = evidence / "vendor-tests.junit.xml"
    listed = json.loads(list_path.read_text())["rust-suites"]
    expected = {
        (name, case["runtime_name"]): case
        for name, vendor in VENDORS.items()
        for case in vendor["tests"]
    }
    eligible = {
        identity
        for identity, case in expected.items()
        if not case["ignored"] and not case["no_github_actions"]
    }
    excluded = set(expected) - eligible
    document = ET.parse(junit_path)
    cases = []
    problems = []
    seen = set()
    seen_binaries = set()
    passed = set()
    retry_tags = {"flakyFailure", "flakyError", "rerunFailure", "rerunError"}
    if (
        document.getroot().tag != "testsuites"
        or len(expected) != 100
        or len(eligible) != 89
    ):
        problems.append("Unexpected JUnit root or changed frozen source inventory")
    for suite in document.getroot().findall("testsuite"):
        binary = suite.get("name")
        if binary in seen_binaries or binary not in listed:
            problems.append(f"Duplicate or unknown JUnit binary: {binary}")
        seen_binaries.add(binary)
        package = listed.get(binary, {}).get("package-name")
        for case in suite.findall("testcase"):
            identity = (package, case.get("name"))
            valid_identity = (
                binary in listed
                and case.get("classname") == binary
                and case.get("name") in listed[binary]["testcases"]
                and identity in expected
            )
            if not valid_identity or identity in seen:
                problems.append(
                    f"Unknown, mismatched or duplicate JUnit identity: {binary}, {identity}"
                )
            seen.add(identity)
            terminal = [
                child for child in case if child.tag in {"skipped", "failure", "error"}
            ]
            retries = [child for child in case if child.tag in retry_tags]
            flaky = [child for child in retries if child.tag.startswith("flaky")]
            reruns = [child for child in retries if child.tag.startswith("rerun")]
            if case.find("skipped") is not None:
                status = "skipped"
                if identity not in excluded or retries or len(terminal) != 1:
                    problems.append(
                        f"Unexpected skip or execution diagnostics for {identity}"
                    )
            elif case.find("failure") is not None or case.find("error") is not None:
                status = "failed"
                problems.append(f"Failed required execution: {identity}")
                if flaky or len(terminal) != 1:
                    problems.append(
                        f"Inconsistent failure/retry representation: {identity}"
                    )
            else:
                status = "passed_after_retry" if flaky else "passed_first_attempt"
                if reruns or identity not in eligible:
                    problems.append(
                        f"Excluded or inconsistent successful execution: {identity}"
                    )
                elif valid_identity:
                    passed.add(identity)
            if len(retries) > 1:
                problems.append(
                    f"More retries than the original retries=1 policy: {identity}"
                )
            cases.append(
                {
                    "package": package,
                    "binary_id": binary,
                    "name": case.get("name"),
                    "classname": case.get("classname"),
                    "identity_valid": valid_identity,
                    "status": status,
                    "attempts": 0 if status == "skipped" else 1 + len(retries),
                    "attributes": dict(case.attrib),
                    "retry_diagnostics": [
                        {
                            "tag": child.tag,
                            "attributes": dict(child.attrib),
                            "text": "".join(child.itertext()),
                            "xml": ET.tostring(child, encoding="unicode"),
                        }
                        for child in retries
                    ],
                    "xml": ET.tostring(case, encoding="unicode"),
                }
            )
    if sum(1 for _ in document.iter("testcase")) != len(cases):
        problems.append(
            "JUnit includes testcases outside the expected testsuite structure"
        )
    missing = sorted(eligible - passed)
    unexpected_success = sorted(passed - eligible)
    if missing or unexpected_success:
        problems.append(
            f"Successful JUnit identities differ from required source identities: missing={missing}, unexpected={unexpected_success}"
        )
    retried_successes = [
        case for case in cases if case["status"] == "passed_after_retry"
    ]
    report = {
        "list_sha256": hashlib.sha256(list_path.read_bytes()).hexdigest(),
        "junit_sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
        "eligible_identities": sorted(eligible),
        "successful_identities": sorted(passed),
        "original_excluded_identities": sorted(excluded),
        "passed_first_attempt": sum(
            case["status"] == "passed_first_attempt" for case in cases
        ),
        "passed_after_retry": len(retried_successes),
        "original_exclusions_are_not_passes": True,
        "missing": missing,
        "unexpected_success": unexpected_success,
        "problems": problems,
        "cases": cases,
    }
    write_json(evidence / "vendor-test-results.json", report)
    if problems:
        raise ValueError(
            f"Vendor JUnit did not prove the exact 89 required identities: {problems}"
        )
    print(
        f"JUnit binds all 89 eligible package/test identities uniquely: {89 - len(retried_successes)} first-attempt passes, {len(retried_successes)} passes after retry; original 11 exclusions are not passes"
    )


def verify_bazel_generated(evidence):
    query_path = evidence / "bazel-vendor-libraries.xml"
    document = ET.parse(query_path)
    metadata = json.loads((evidence / "metadata.json").read_text())
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    problems = []
    observed = {}
    if document.getroot().tag != "query":
        problems.append("Unexpected Bazel XML root")
    for rule in document.getroot().findall("rule"):
        label = rule.get("name", "")
        name = label.rsplit(":", 1)[-1]
        if name not in VENDORS or name in observed:
            problems.append(f"Unknown or duplicate generated library: {label}")
            continue
        version_field = rule.find("string[@name='version']")
        version = version_field.get("value") if version_field is not None else None
        features = {
            value.get("value")
            for value in rule.findall("list[@name='crate_features']/string")
        }
        dependencies = [
            value.get("value", "")
            for kind in ("deps", "proc_macro_deps")
            for value in rule.findall(f"list[@name='{kind}']/label")
        ]
        dependency_targets = {value.rsplit(":", 1)[-1] for value in dependencies}
        vendor = VENDORS[name]
        manifest = ROOT / "codex-rs/third_party" / vendor["directory"] / "Cargo.toml"
        package_manifest = tomllib.loads(manifest.read_text())["package"]
        selected = [package for package in packages.values() if package["name"] == name]
        expected_dependencies = set()
        if (
            len(selected) != 1
            or selected[0].get("source") is not None
            or Path(selected[0]["manifest_path"]) != manifest
        ):
            problems.append(
                f"Production metadata does not select the exact local patch: {name}"
            )
        else:
            for edge in nodes[selected[0]["id"]]["deps"]:
                if any(kind["kind"] is None for kind in edge["dep_kinds"]):
                    package = packages[edge["pkg"]]
                    expected_dependencies.add(
                        package["name"] + "-" + package["version"]
                    )
        if (
            rule.get("class") != "rust_library"
            or version != package_manifest["version"]
        ):
            problems.append(
                f"Generated target is not the exact versioned Rust library: {label}, {rule.get('class')}, {version}"
            )
        if (
            not dependencies
            or dependency_targets != expected_dependencies
            or any("//:" not in value for value in dependencies)
        ):
            problems.append(
                f"Generated dependencies differ from production normal edges: {name}, actual={sorted(dependency_targets)}, expected={sorted(expected_dependencies)}"
            )
        if name != "i18n-config" and "crypto-rust" not in features:
            problems.append(
                f"Generated library lost the encrypted Rust backend: {name}"
            )
        observed[name] = {
            "label": label,
            "class": rule.get("class"),
            "version": version,
            "features": sorted(features),
            "dependency_labels": dependencies,
            "dependency_targets": sorted(dependency_targets),
            "production_normal_dependencies": sorted(expected_dependencies),
            "xml": ET.tostring(rule, encoding="unicode"),
        }
    if set(observed) != set(VENDORS) or len(list(document.getroot())) != 3:
        problems.append(
            "Bazel query did not return exactly the three expected library rules"
        )
    write_json(
        evidence / "bazel-generated-library-check.json",
        {
            "query_sha256": hashlib.sha256(query_path.read_bytes()).hexdigest(),
            "libraries": observed,
            "problems": problems,
        },
    )
    if problems:
        raise ValueError(
            f"Native generated Bazel libraries failed identity/dependency/feature validation: {problems}"
        )
    print(
        "The three native path-patch libraries have exact versions and production dependency edges; both encrypted backends retain crypto-rust"
    )


def copy_fixed_sources(evidence):
    changes = []
    for vendor in VENDORS.values():
        source = evidence / "vendor-harness" / vendor["directory"]
        target = ROOT / "codex-rs/third_party" / vendor["directory"]
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            destination = target / relative
            if not destination.exists():
                raise ValueError(f"Unexpected harness file after Clippy: {path}")
            if path.read_bytes() != destination.read_bytes():
                if path.suffix != ".rs":
                    raise ValueError(f"Unexpected non-Rust harness edit: {path}")
                shutil.copyfile(path, destination)
                changes.append(destination.relative_to(ROOT).as_posix())
    write_json(evidence / "vendor-clippy-source-changes.json", changes)
    print(
        f"Exported {len(changes)} cloud Clippy source changes; exact postimages still require review"
    )


def main():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY")
        != "TrillionniumFoundation/hepta-private-ci"
    ):
        raise SystemExit(
            "This fixed proposal runs only in the project's GitHub Actions environment"
        )
    evidence = Path(os.environ["CARGO_POLICY_EVIDENCE_DIR"]).resolve()
    operations = {
        "prepare-harness": prepare_harness,
        "normal-graph": verify_graph,
        "test-list": verify_list,
        "test-results": verify_results,
        "lock-packages": verify_lock,
        "bazel-generated": verify_bazel_generated,
        "copy-fixed-sources": copy_fixed_sources,
    }
    operations[sys.argv[1]](evidence)


if __name__ == "__main__":
    main()
