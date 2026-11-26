"""Pure data contracts for a new, inactive SQLx four-lock generation scope.

The fixture normalizer and declaration checks are verbatim from the reviewed
native-owner source proposal. Generated values still require Root acceptance.
"""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = "qualification/sqlx_temporal_default_v1"
COMPATIBILITY = "qualification/sqlx_temporal_explicit_chrono_v1"
SQLX_FAMILY = frozenset(
    (
        "sqlx",
        "sqlx-core",
        "sqlx-sqlite",
        "sqlx-macros",
        "sqlx-macros-core",
        "sqlx-mysql",
        "sqlx-postgres",
    )
)
CRATE_FACT = "@@rules_rs+//rs:extensions.bzl%crate"
PACKAGES = (
    "codex-cli",
    "codex-hepta-agentd",
    "codex-hepta-authbus",
    "codex-hepta-automation",
    "codex-hepta-evidence",
    "codex-hepta-matrix-store",
    "codex-hepta-memory",
    "codex-hepta-operations",
    "codex-hepta-runtime",
    "codex-hepta-shadow-qualification",
    "codex-state",
    "codex-thread-store",
)
FIXTURES = (
    ("default", DEFAULT, "sqlx-temporal-default-contract-v1", False),
    ("compatibility", COMPATIBILITY, "sqlx-temporal-explicit-chrono-contract-v1", True),
)


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def read_regular(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "input is not a regular file")
        require(0 <= before.st_size <= maximum, "input exceeds its byte bound")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        len(raw) <= maximum
        and len(raw) == before.st_size
        and all(getattr(before, key) == getattr(after, key) for key in fields),
        "input changed or exceeded its byte bound",
    )
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized_patches(manifest, directory):
    result = {}
    for source, entries in manifest.get("patch", {}).items():
        normalized = {}
        for name, original in entries.items():
            item = dict(original)
            if "path" in item:
                actual = (directory / item["path"]).resolve()
                require(
                    actual.is_relative_to(ROOT), "fixture patch leaves accepted source"
                )
                item["path"] = actual.relative_to(ROOT).as_posix()
            normalized[name] = item
        result[source] = normalized
    return result


def check_fixture_declarations():
    workspace = tomllib.loads(
        read_regular(ROOT / "codex-rs/Cargo.toml", 1024 * 1024).decode()
    )
    original_patches = normalized_patches(workspace, ROOT / "codex-rs")
    require(
        "chrono" not in workspace["workspace"]["dependencies"]["sqlx"]["features"],
        "main workspace still requests the implicit SQLx Chrono codec",
    )
    for relative, expected_features in (
        (DEFAULT, ["sqlite-bundled"]),
        (COMPATIBILITY, ["chrono", "sqlite-bundled"]),
    ):
        directory = ROOT / relative
        manifest = tomllib.loads(
            read_regular(directory / "Cargo.toml", 1024 * 1024).decode()
        )
        require(
            manifest["workspace"] == {"resolver": "2"}
            and manifest["dependencies"]["sqlx"]
            == {
                "version": "=0.9.1",
                "default-features": False,
                "features": expected_features,
            }
            and manifest["dependencies"]["chrono"]
            == {"version": "=0.4.45", "default-features": False, "features": ["std"]}
            and normalized_patches(manifest, directory) == original_patches,
            "independent fixture SQLx capability or accepted workspace patches differ",
        )


def normalized_fixture_graph(metadata):
    packages = {row["id"]: row for row in metadata["packages"]}
    nodes = {row["id"]: row for row in metadata["resolve"]["nodes"]}
    require(
        len(packages) == len(metadata["packages"])
        and len(nodes) == len(metadata["resolve"]["nodes"])
        and packages.keys() == nodes.keys(),
        "fixture metadata package and resolved-node rosters differ",
    )

    def identity(package_id):
        package = packages[package_id]
        manifest = None
        if package["source"] is None:
            manifest = Path(package["manifest_path"]).relative_to(ROOT).as_posix()
        return {
            "name": package["name"],
            "version": package["version"],
            "source": package["source"],
            "manifest": manifest,
        }

    normalized = []
    for package_id, package in packages.items():
        node = nodes[package_id]
        target_root = (
            ROOT if package["source"] is None else Path(package["manifest_path"]).parent
        )
        targets = []
        for original in package["targets"]:
            target = dict(original)
            target["src_path"] = (
                Path(target["src_path"]).relative_to(target_root).as_posix()
            )
            targets.append(target)
        normalized.append(
            {
                "identity": identity(package_id),
                "links": package.get("links"),
                "features": sorted(node["features"]),
                "targets": sorted(targets, key=canonical),
                "deps": sorted(
                    (
                        {
                            "name": edge["name"],
                            "dependency": identity(edge["pkg"]),
                            "dep_kinds": sorted(edge["dep_kinds"], key=canonical),
                        }
                        for edge in node["deps"]
                    ),
                    key=canonical,
                ),
            }
        )
    return {
        "packages": sorted(normalized, key=canonical),
        "workspace_members": sorted(
            (identity(value) for value in metadata["workspace_members"]), key=canonical
        ),
        "workspace_default_members": sorted(
            (identity(value) for value in metadata["workspace_default_members"]),
            key=canonical,
        ),
        "resolve_root": identity(metadata["resolve"]["root"]),
    }


def lock_map(lock):
    require(lock.get("version") == 4, "Cargo lock schema changed")
    rows = lock.get("package", [])
    mapped = {(row["name"], row["version"], row.get("source")): row for row in rows}
    require(
        rows and len(mapped) == len(rows),
        "Cargo package identities repeat or are absent",
    )
    for key, row in mapped.items():
        if key[2] is not None and key[2].startswith("registry+"):
            require(
                re.fullmatch(r"[0-9a-f]{64}", row.get("checksum", "")),
                "registry checksum is absent",
            )
    return mapped


def dependency_ids(row, packages):
    result = []
    for text in row.get("dependencies", []):
        base, separator, source = text.partition(" (")
        parts = base.split(" ")
        require(
            len(parts) in (1, 2) and (not separator or source.endswith(")")),
            "unsupported Cargo dependency identity",
        )
        matches = [
            key
            for key in packages
            if key[0] == parts[0]
            and (len(parts) == 1 or key[1] == parts[1])
            and (not separator or key[2] == source[:-1])
        ]
        require(len(matches) == 1, "Cargo dependency is absent or ambiguous: " + text)
        result.append(matches[0])
    require(len(result) == len(set(result)), "Cargo package repeats a dependency")
    return set(result)


def lock_relation(baseline, candidate, fixture_name=None):
    before, after = lock_map(baseline), lock_map(candidate)
    added = after.keys() - before.keys()
    expected_added = {(fixture_name, "0.0.0", None)} if fixture_name else set()
    require(
        added == expected_added, "generated lock added an unreviewed package identity"
    )
    require(
        fixture_name is not None
        or {key for key in before if key[2] is None}.issubset(after),
        "main lock dropped an accepted first-party or patched package",
    )
    changes = []
    for key, row in after.items():
        edges = dependency_ids(row, after)
        if key in added:
            require(
                set(row) <= {"name", "version", "dependencies"},
                "fixture root has an unexpected lock attribute",
            )
            require(edges.issubset(before), "fixture root depends on a new identity")
            continue
        old = before[key]
        require(
            {k: v for k, v in row.items() if k != "dependencies"}
            == {k: v for k, v in old.items() if k != "dependencies"},
            "package version, source, checksum or other attributes drifted",
        )
        old_edges = dependency_ids(old, before)
        removed, new = old_edges - edges, edges - old_edges
        if fixture_name:
            require(
                not new, "fixture selected a different dependency version or source"
            )
        elif key[0] in SQLX_FAMILY:
            require(
                not new and all(value[0] == "chrono" for value in removed),
                "SQLx root-lock change exceeds the removed Chrono capability",
            )
        else:
            require(edges == old_edges, "non-SQLx root-lock dependencies changed")
        if edges != old_edges:
            changes.append(
                {
                    "identity": key,
                    "removed": sorted(removed, key=canonical),
                    "added": sorted(new, key=canonical),
                }
            )
    if fixture_name is None:
        require(
            {k: v for k, v in candidate.items() if k != "package"}
            == {k: v for k, v in baseline.items() if k != "package"},
            "main lock changed non-package metadata",
        )
    else:
        require(
            set(candidate) <= {"version", "package", "patch"},
            "fixture lock contains unreviewed top-level metadata",
        )
        patch = candidate.get("patch", {})
        require(set(patch) <= {"unused"}, "fixture changed patch-lock structure")
        original_unused = {
            (r["name"], r["version"], r.get("source")): r
            for r in baseline.get("patch", {}).get("unused", [])
        }
        for unused in patch.get("unused", []):
            key = (unused["name"], unused["version"], unused.get("source"))
            require(
                key in before or key in original_unused,
                "fixture has a foreign unused patch",
            )
            original = before.get(key, original_unused.get(key))
            require(
                all(original.get(field) == value for field, value in unused.items()),
                "fixture unused-patch identity or checksum changed",
            )
    return {
        "packages": len(after),
        "removed_identities": sorted(before.keys() - after.keys(), key=canonical),
        "added_identities": sorted(added, key=canonical),
        "dependency_deltas": changes,
        "registry_versions_and_checksums_reused": True,
        "qualification": False,
    }


def fixture_observation(metadata, lock, fixture_name, compatibility):
    packages = lock_map(lock)
    normalized = normalized_fixture_graph(metadata)
    metadata_ids = {
        (p["name"], p["version"], p["source"]) for p in metadata["packages"]
    }
    require(
        metadata_ids.issubset(packages),
        "fixture metadata is not covered by its own actual lock",
    )
    codecs = [
        p
        for p in normalized["packages"]
        if p["identity"]["name"] in ("sqlx", "sqlx-core", "sqlx-sqlite")
    ]
    require(
        len(codecs) == 3
        and all(p["identity"]["version"] == "0.9.1" for p in codecs)
        and all(("chrono" in p["features"]) is compatibility for p in codecs),
        "fixture has the wrong SQLx Chrono capability",
    )
    if not compatibility:
        require(
            all(
                "chrono" not in p["features"]
                for p in normalized["packages"]
                if p["identity"]["name"] in SQLX_FAMILY
            ),
            "an indirect SQLx Chrono capability reached the default fixture",
        )
    require(
        normalized["resolve_root"]["name"] == fixture_name
        and normalized["resolve_root"]["manifest"]
        == (COMPATIBILITY if compatibility else DEFAULT) + "/Cargo.toml",
        "fixture metadata has a different independent root",
    )
    return normalized, {
        "normalized_graph_sha256": digest(canonical(normalized)),
        "package_count": len(normalized["packages"]),
        "root_package_id": metadata["resolve"]["root"],
        "sqlx_chrono_opt_in": compatibility,
        "qualification": False,
    }


def consumer_targets(metadata):
    selected = [p for p in metadata["packages"] if p["name"] in PACKAGES]
    require(
        len(selected) == 12
        and Counter(p["name"] for p in selected) == Counter(PACKAGES),
        "actual twelve-consumer package roster differs",
    )
    result = {}
    for package in selected:
        targets = []
        for original in package["targets"]:
            target = dict(original)
            target["src_path"] = Path(target["src_path"]).relative_to(ROOT).as_posix()
            targets.append(target)
        result[package["name"]] = sorted(targets, key=canonical)
    return result


def bazel_relation(before_raw, after_raw):
    before, after = strict_json(before_raw), strict_json(after_raw)
    require(
        isinstance(before, dict)
        and isinstance(after, dict)
        and before.keys() == after.keys()
        and before["lockFileVersion"] == 28,
        "Bazel lock top-level schema differs",
    )
    require(
        {key: value for key, value in before.items() if key != "facts"}
        == {key: value for key, value in after.items() if key != "facts"},
        "Bazel changed registry, selected-yank, toolchain, extension or version identities",
    )
    left, right = before["facts"], after["facts"]
    require(
        left.keys() == right.keys()
        and CRATE_FACT in left
        and {key: value for key, value in left.items() if key != CRATE_FACT}
        == {key: value for key, value in right.items() if key != CRATE_FACT},
        "Bazel changed a non-crate fact",
    )
    return {
        "full_postimage_byte_identical": before_raw == after_raw,
        "mutable_fact_key": CRATE_FACT,
        "crate_fact_changed": left[CRATE_FACT] != right[CRATE_FACT],
        "before_crate_fact": left[CRATE_FACT],
        "after_crate_fact": right[CRATE_FACT],
        "all_non_crate_fields_equal": True,
        "crate_fact_semantics_accepted": False,
        "requires_root_full_fact_review": True,
        "qualification": False,
    }
