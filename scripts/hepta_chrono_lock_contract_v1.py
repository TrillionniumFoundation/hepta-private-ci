"""Validate five workspace rebindings and one exact prettyplease alignment.

These checks describe dependency correspondence, not advisory or native
qualification. The original metadata and both complete lockfiles stay evidence.
"""

import copy
import hashlib
import json
from pathlib import Path
import tomllib


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
OWNERS = frozenset(
    {
        "codex-agent-identity",
        "codex-external-agent-migration",
        "codex-git-utils",
        "codex-network-proxy",
        "codex-otel",
    }
)
TARGETS = {
    "cookie": "0.18.3",
    "url": "2.5.9",
    "rmcp": "3.9.0",
    "sqlx": "0.9.1",
    "libsqlite3-sys": "0.39.1",
    "rusqlite": "0.41.0",
}
PRETTYPLEASE_NEW = ("prettyplease", "0.3.0", REGISTRY)
PRETTYPLEASE_NEW_CHECKSUM = (
    "2bfe0f4c752e450fc2faf62654f1c134747922825d5b04ca717b8874f41a40c0"
)
PRETTYPLEASE_CONSUMERS = {
    ("bindgen", "0.72.1", REGISTRY): "0.2.37",
    ("bindgen", "0.73.2", REGISTRY): "0.3.0",
    ("prost-build", "0.14.4", REGISTRY): "0.2.37",
    ("tonic-build", "0.14.6", REGISTRY): "0.2.37",
    ("tonic-prost-build", "0.14.3", REGISTRY): "0.2.37",
}
CRATE_FACTS = "@@rules_rs+//rs:extensions.bzl%crate"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def package_map(lock):
    rows = lock.get("package")
    require(isinstance(rows, list) and rows, "Cargo lock package list is absent")
    result = {}
    for row in rows:
        key = (row["name"], row["version"], row.get("source"))
        require(key not in result, "Cargo lock repeats a package identity")
        result[key] = row
    return result


def source_bindings(spec, root):
    """Derive the allowed edge changes from the actual five source manifests."""
    result = {}
    for row in spec["manifest_rebindings"]:
        relative = Path(row["path"])
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "manifest path leaves the reviewed source",
        )
        raw = (root / relative).read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == row["after_sha256"],
            "actual rebound manifest differs from reviewed bytes",
        )
        before_raw = row["before_toml"].encode()
        require(
            hashlib.sha256(before_raw).hexdigest() == row["before_sha256"],
            "original manifest bytes differ from the frozen source",
        )
        before = tomllib.loads(before_raw.decode())
        after = tomllib.loads(raw.decode())
        name = after["package"]["name"]
        require(
            name in OWNERS and name not in result and before["package"]["name"] == name,
            "manifest owner is not one of the five distinct original owners",
        )
        require(
            before["dependencies"]["chrono"]["workspace"] is True,
            "original direct Chrono declaration is absent",
        )
        expected = copy.deepcopy(before)
        del expected["dependencies"]["chrono"]
        expected["dependencies"]["time"] = row["approved_time_dependency"]
        require(
            row["approved_time_dependency"]["workspace"] is True,
            "time must use the original workspace dependency",
        )
        require(
            after == expected,
            "manifest changes exceed the reviewed Chrono-to-time declaration",
        )
        result[name] = {
            "manifest": relative.as_posix(),
            "had_time": "time" in before["dependencies"],
            "actual_time_dependency": after["dependencies"]["time"],
            "before_sha256": row["before_sha256"],
            "after_sha256": row["after_sha256"],
        }
    require(result.keys() == OWNERS, "the complete five-manifest rebinding is required")
    return result


def lock_rebinding(before, after, bindings, spec):
    """Allow only the dependency-list changes proven by source_bindings."""
    require(bindings.keys() == OWNERS, "unexpected workspace rebinding owners")
    require(
        {key: value for key, value in before.items() if key != "package"}
        == {key: value for key, value in after.items() if key != "package"},
        "Cargo lock metadata changed",
    )
    old, new = package_map(before), package_map(after)
    require(
        PRETTYPLEASE_NEW not in old and new.keys() == old.keys() | {PRETTYPLEASE_NEW},
        "the only new Cargo identity must be prettyplease 0.3.0; no old identity may disappear",
    )
    approved_new = spec["prettyplease_alignment"]["new_lock_record"]
    require(
        approved_new
        == {
            "name": "prettyplease",
            "version": "0.3.0",
            "source": REGISTRY,
            "checksum": PRETTYPLEASE_NEW_CHECKSUM,
            "dependencies": ["proc-macro2", "syn 3.0.9"],
        },
        "new prettyplease record differs from the exact official release",
    )
    require(
        new[PRETTYPLEASE_NEW] == approved_new,
        "actual prettyplease 0.3.0 package differs",
    )
    original_consumers = {
        key for key, row in old.items() if "prettyplease" in row.get("dependencies", [])
    }
    require(
        original_consumers == PRETTYPLEASE_CONSUMERS.keys(),
        "original prettyplease consumers differ from the five reviewed actual graph parents",
    )
    for name, version in {**TARGETS, "chrono": "0.4.45", "time": "0.3.55"}.items():
        selected = [key for key in old if key[0] == name]
        require(
            selected == [(name, version, REGISTRY)],
            "original pinned registry identity differs: " + name,
        )
    changed = []
    alignment_changes = []
    for key, original in old.items():
        actual = new[key]
        if key[0] in OWNERS:
            require(key[2] is None, "workspace owner became a registry dependency")
            expected = copy.deepcopy(original)
            dependencies = expected["dependencies"]
            require(
                len(dependencies) == len(set(dependencies))
                and dependencies.count("chrono") == 1,
                "original owner has an unexpected Chrono lock reference",
            )
            require(
                ("time" in dependencies) == bindings[key[0]]["had_time"],
                "original manifest and Cargo lock time declaration differ",
            )
            expected["dependencies"] = sorted(
                (set(dependencies) - {"chrono"}) | {"time"}
            )
            require(
                actual == expected,
                "workspace lock changes exceed the actual source declaration: "
                + key[0],
            )
            changed.append(
                {
                    "name": key[0],
                    "before": original,
                    "after": actual,
                    "manifest": bindings[key[0]]["manifest"],
                }
            )
        elif key in PRETTYPLEASE_CONSUMERS:
            expected = copy.deepcopy(original)
            require(
                expected["dependencies"].count("prettyplease") == 1,
                "original prettyplease reference is ambiguous",
            )
            expected["dependencies"] = sorted(
                "prettyplease " + PRETTYPLEASE_CONSUMERS[key]
                if name == "prettyplease"
                else name
                for name in expected["dependencies"]
            )
            require(
                actual == expected,
                "prettyplease consumer changed beyond the reviewed edge: " + key[0],
            )
            alignment_changes.append(
                {
                    "name": key[0],
                    "version": key[1],
                    "before": original,
                    "after": actual,
                    "selected_prettyplease": PRETTYPLEASE_CONSUMERS[key],
                    "semantic_dependency_changed": key[1] == "0.73.2"
                    and key[0] == "bindgen",
                }
            )
        else:
            require(
                actual == original,
                "unreviewed package/dependency/checksum drift: " + key[0],
            )
    require(
        len(changed) == len(OWNERS) and {row["name"] for row in changed} == OWNERS,
        "all five original owner records must be present once",
    )
    registry_rows = [row for key, row in old.items() if key[2] is not None]
    registry_rows.sort(key=lambda row: (row["name"], row["version"], row["source"]))
    return {
        "changed_workspace_records": sorted(changed, key=lambda row: row["name"]),
        "original_external_package_records": len(registry_rows),
        "original_external_records_sha256": hashlib.sha256(
            canonical(registry_rows).encode()
        ).hexdigest(),
        "prettyplease_reference_changes": sorted(alignment_changes, key=canonical),
        "new_prettyplease_record": approved_new,
        "original_package_count": len(old),
        "candidate_package_count": len(new),
        "old_registry_identities_and_checksums_unchanged": True,
        "unapproved_registry_version_or_checksum_drift": False,
        "advisory_qualification": False,
    }


def normalize_graph(metadata, work, lock):
    """Remove only the owned checkout prefix; preserve identities and edge data."""
    require(metadata.get("version") == 1, "unexpected Cargo metadata format")
    packages = {row["id"]: row for row in metadata["packages"]}
    nodes = {row["id"]: row for row in metadata["resolve"]["nodes"]}
    require(
        len(packages) == len(metadata["packages"])
        and len(nodes) == len(metadata["resolve"]["nodes"]),
        "metadata repeats package or node identities",
    )
    require(packages.keys() == nodes.keys(), "metadata package and node rosters differ")
    locked = package_map(lock)

    def identity(package):
        key = (package["name"], package["version"], package["source"])
        require(
            key in locked, "metadata package is absent from the observed Cargo lock"
        )
        manifest = None
        if package["source"] is None:
            manifest = Path(package["manifest_path"]).relative_to(work).as_posix()
        return {
            "name": key[0],
            "version": key[1],
            "source": key[2],
            "checksum": locked[key].get("checksum"),
            "manifest": manifest,
        }

    chrono = [row for row in packages.values() if row["name"] == "chrono"]
    require(
        len(chrono) == 1
        and chrono[0]["version"] == "0.4.45"
        and chrono[0]["source"] == REGISTRY,
        "actual Chrono identity differs",
    )
    chrono_id = chrono[0]["id"]
    reverse = []
    owner_nodes = {}
    for node_id, node in nodes.items():
        package = packages[node_id]
        package_identity = identity(package)
        for edge in node["deps"]:
            if edge["pkg"] == chrono_id:
                reverse.append(
                    {
                        "dependent": package_identity,
                        "dependent_features": sorted(node["features"]),
                        "dependency": identity(packages[edge["pkg"]]),
                        "edge_name": edge["name"],
                        "dep_kinds": sorted(edge["dep_kinds"], key=canonical),
                    }
                )
        if package["source"] is None and package["name"] in OWNERS:
            require(package["name"] not in owner_nodes, "multiple actual owner nodes")
            owner_nodes[package["name"]] = {
                "identity": package_identity,
                "features": sorted(node["features"]),
                "time_edges": [
                    {
                        "edge_name": edge["name"],
                        "dependency": identity(packages[edge["pkg"]]),
                        "dep_kinds": sorted(edge["dep_kinds"], key=canonical),
                    }
                    for edge in node["deps"]
                    if packages[edge["pkg"]]["name"] == "time"
                ],
                "chrono_edges": sum(edge["pkg"] == chrono_id for edge in node["deps"]),
            }
    members = [
        Path(packages[key]["manifest_path"]).relative_to(work).as_posix()
        for key in metadata["workspace_members"]
    ]
    require(
        len(members) == len(set(members)),
        "actual workspace membership repeats a manifest",
    )
    alignment_ids = set(PRETTYPLEASE_CONSUMERS) | {
        ("prettyplease", "0.2.37", REGISTRY),
        PRETTYPLEASE_NEW,
    }
    alignment = {}
    full_graph = []
    for package in packages.values():
        key = (package["name"], package["version"], package["source"])
        node = nodes[package["id"]]
        normalized_node = {
            "identity": identity(package),
            "features": sorted(node["features"]),
            "links": package.get("links"),
            "deps": sorted(
                [
                    {
                        "edge_name": edge["name"],
                        "dependency": identity(packages[edge["pkg"]]),
                        "dep_kinds": sorted(edge["dep_kinds"], key=canonical),
                    }
                    for edge in node["deps"]
                ],
                key=canonical,
            ),
        }
        full_graph.append(normalized_node)
        if key in alignment_ids:
            alignment[package["name"] + "@" + package["version"]] = normalized_node
    require(
        len(alignment) == len(alignment_ids),
        "actual prettyplease alignment graph is incomplete",
    )
    return {
        "workspace_member_manifests": sorted(members),
        "package_count": len(packages),
        "resolve_node_count": len(nodes),
        "full_resolve_graph_sha256": hashlib.sha256(
            canonical(sorted(full_graph, key=canonical)).encode()
        ).hexdigest(),
        "chrono_identity": identity(chrono[0]),
        "chrono_features": sorted(nodes[chrono_id]["features"]),
        "chrono_reverse_edges": sorted(reverse, key=canonical),
        "rebound_owner_nodes": owner_nodes,
        "prettyplease_alignment": alignment,
    }


def graph_rebinding(metadata, spec, work, lock, bindings):
    actual = normalize_graph(metadata, work, lock)
    require(
        len(actual["workspace_member_manifests"]) == 193
        and actual["workspace_member_manifests"] == spec["workspace_member_manifests"],
        "actual 193-member workspace roster changed",
    )
    expected = spec["expected_graph"]
    require(
        actual["package_count"] == expected["package_count"]
        and actual["resolve_node_count"] == expected["resolve_node_count"],
        "actual package or resolve-node roster changed",
    )
    require(
        actual["full_resolve_graph_sha256"] == expected["full_resolve_graph_sha256"],
        "actual normalized complete graph has unapproved identities, links, features, or edge conditions",
    )
    require(
        actual["prettyplease_alignment"] == expected["prettyplease_alignment"],
        "actual bindgen/prettyplease/syn identities, links, edge conditions, or features differ",
    )
    require(
        actual["chrono_identity"] == expected["chrono_identity"]
        and actual["chrono_features"] == expected["chrono_features"],
        "remaining Chrono identity, checksum, or features changed",
    )
    require(
        len(actual["chrono_reverse_edges"]) == 31
        and actual["chrono_reverse_edges"] == expected["chrono_reverse_edges"],
        "actual Chrono inverse edges are not the original 36 minus the reviewed five",
    )
    require(
        actual["rebound_owner_nodes"].keys() == OWNERS,
        "actual rebinding owners are incomplete",
    )
    for name, node in actual["rebound_owner_nodes"].items():
        require(
            node["identity"] == expected["rebound_owner_nodes"][name]["identity"]
            and node["features"] == expected["rebound_owner_nodes"][name]["features"],
            "actual workspace owner identity or features changed: " + name,
        )
        require(
            node["identity"]["manifest"] == bindings[name]["manifest"]
            and node["chrono_edges"] == 0
            and len(node["time_edges"]) == 1,
            "actual owner has not replaced its direct Chrono edge: " + name,
        )
        edge = node["time_edges"][0]
        require(
            edge["edge_name"] == "time"
            and edge["dependency"]["name"] == "time"
            and edge["dependency"]["version"] == "0.3.55"
            and edge["dependency"]["source"] == REGISTRY
            and edge["dep_kinds"] == [{"kind": None, "target": None}],
            "actual owner time dependency changed: " + name,
        )
    actual.update(
        {
            "actual_inverse_edge_count": 31,
            "original_inverse_edge_count": 36,
            "chrono_unmaintained_unresolved": True,
            "all_features_edges_are_not_default_or_runtime_activity": True,
            "full_raw_graph_retained": True,
            "compatibility_or_advisory_qualified": False,
        }
    )
    return actual


def bazel_lock_correspondence(before, after, spec):
    # The only new registry manifest is the exact prettyplease 0.3.0 release.
    # Existing facts, toolchains, registry hashes, yanked versions, and other
    # extension data are unchanged; both complete postimages remain evidence.
    key = "prettyplease_0.3.0"
    require(
        key not in before["facts"][CRATE_FACTS] and key in after["facts"][CRATE_FACTS],
        "new prettyplease Bazel fact is absent or not new",
    )

    def pairs(items):
        value = {}
        for name, item in items:
            require(name not in value, "duplicate JSON key in new Bazel crate fact")
            value[name] = item
        return value

    raw = after["facts"][CRATE_FACTS][key]

    def nonfinite(value):
        raise ValueError("nonfinite JSON number in new Bazel crate fact: " + value)

    actual = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    require(
        actual == spec["prettyplease_alignment"]["new_bazel_fact"],
        "new Bazel crate fact differs from the official release declaration",
    )
    expected = copy.deepcopy(before)
    expected["facts"][CRATE_FACTS][key] = raw
    require(
        after == expected,
        "Bazel facts changed outside the one reviewed compatibility addition",
    )
    return {
        "only_added_fact": key,
        "complete_postimage_retained": True,
        "advisory_or_native_qualification": False,
    }
