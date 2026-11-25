"""Validate two owner rebindings and unchanged shared registry feature closure.

This is dependency correspondence, not native compatibility or advisory
qualification. Original metadata and both complete lockfiles remain evidence.
"""

import copy
import hashlib
import json
from pathlib import Path
import tomllib


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
OWNER_MANIFESTS = {
    "codex-cli": "codex-rs/cli/Cargo.toml",
    "codex-hooks": "codex-rs/hooks/Cargo.toml",
}
OWNERS = frozenset(OWNER_MANIFESTS)
TIME_DEPENDENCY = {"workspace": True, "features": ["wasm-bindgen"]}
WASM_CLOCK_TARGET = 'cfg(all(target_arch = "wasm32", not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))))'
WASM_CLOCK_DEPENDENCY = "=0.3.106"
WASM_CLOCK_IDENTITY = ("js-sys", "0.3.106", REGISTRY)
TARGETS = {
    "cookie": "0.18.3",
    "url": "2.5.9",
    "rmcp": "3.9.0",
    "sqlx": "0.9.1",
    "libsqlite3-sys": "0.39.1",
    "rusqlite": "0.41.0",
}
PRETTYPLEASE_CONSUMERS = {
    ("bindgen", "0.72.1", REGISTRY): "0.2.37",
    ("bindgen", "0.73.2", REGISTRY): "0.3.0",
    ("prost-build", "0.14.4", REGISTRY): "0.2.37",
    ("tonic-build", "0.14.6", REGISTRY): "0.2.37",
    ("tonic-prost-build", "0.14.3", REGISTRY): "0.2.37",
}
TIME_FEATURE_IDENTITIES = {
    ("time", "0.3.55", REGISTRY),
    ("time-core", "0.1.9", REGISTRY),
    ("time-macros", "0.2.32", REGISTRY),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
    """Derive two exact owner records, including their target-only clock edges."""
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
            name in OWNERS
            and name not in result
            and before["package"]["name"] == name
            and relative.as_posix() == OWNER_MANIFESTS[name],
            "manifest is not one of the two distinct original owners",
        )
        require(
            before["dependencies"]["chrono"]["workspace"] is True
            and "time" not in before["dependencies"]
            and "js-sys" not in before["dependencies"]
            and WASM_CLOCK_TARGET not in before.get("target", {}),
            "original direct Chrono-only declaration differs",
        )
        require(
            row["approved_time_dependency"] == TIME_DEPENDENCY,
            "time declaration differs from the reviewed existing feature selection",
        )
        require(
            row["approved_wasm_clock_dependency"]
            == {"target": WASM_CLOCK_TARGET, "js-sys": WASM_CLOCK_DEPENDENCY},
            "wasm clock declaration differs from the exact original clock target",
        )
        expected = copy.deepcopy(before)
        del expected["dependencies"]["chrono"]
        expected["dependencies"]["time"] = TIME_DEPENDENCY
        expected.setdefault("target", {})[WASM_CLOCK_TARGET] = {
            "dependencies": {"js-sys": WASM_CLOCK_DEPENDENCY},
        }
        require(
            after == expected,
            "manifest changes exceed the reviewed time and target-only clock declarations",
        )
        result[name] = {
            "manifest": relative.as_posix(),
            "had_time": False,
            "actual_time_dependency": after["dependencies"]["time"],
            "actual_wasm_clock_target": WASM_CLOCK_TARGET,
            "actual_wasm_clock_dependency": after["target"][WASM_CLOCK_TARGET][
                "dependencies"
            ],
            "before_sha256": row["before_sha256"],
            "after_sha256": row["after_sha256"],
        }
    require(result.keys() == OWNERS, "both distinct manifest rebindings are required")
    return result


def lock_rebinding(before, after, bindings, spec):
    """Preserve every package record except the two proven workspace owners."""
    require(bindings.keys() == OWNERS, "unexpected workspace rebinding owners")
    require(
        {key: value for key, value in before.items() if key != "package"}
        == {key: value for key, value in after.items() if key != "package"},
        "Cargo lock metadata changed",
    )
    old, new = package_map(before), package_map(after)
    require(new.keys() == old.keys(), "Cargo package identity roster changed")
    for name, version in {
        **TARGETS,
        "chrono": "0.4.45",
        "time": "0.3.55",
        "js-sys": "0.3.106",
    }.items():
        require(
            [key for key in old if key[0] == name] == [(name, version, REGISTRY)],
            "original pinned registry identity differs: " + name,
        )
    for key, version in PRETTYPLEASE_CONSUMERS.items():
        require(
            key in old
            and [d for d in old[key]["dependencies"] if d.startswith("prettyplease")]
            == ["prettyplease " + version],
            "accepted prettyplease alignment differs: " + key[0],
        )
    changed = []
    for key, original in old.items():
        actual = new[key]
        if key[0] in OWNERS:
            require(key[2] is None, "workspace owner became a registry dependency")
            expected = copy.deepcopy(original)
            dependencies = expected["dependencies"]
            require(
                len(dependencies) == len(set(dependencies))
                and dependencies.count("chrono") == 1
                and "time" not in dependencies
                and "js-sys" not in dependencies,
                "original owner lock references differ from the source manifests",
            )
            expected["dependencies"] = sorted(
                (set(dependencies) - {"chrono"}) | {"time", "js-sys"}
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
        else:
            require(
                actual == original,
                "unreviewed package/dependency/checksum drift: " + key[0],
            )
    require(
        len(changed) == 2 and {row["name"] for row in changed} == OWNERS,
        "both original owner records must be present once",
    )
    registry_rows = [row for key, row in old.items() if key[2] is not None]
    registry_rows.sort(key=lambda row: (row["name"], row["version"], row["source"]))
    return {
        "changed_workspace_records": sorted(changed, key=lambda row: row["name"]),
        "original_external_package_records": len(registry_rows),
        "original_external_records_sha256": hashlib.sha256(
            canonical(registry_rows).encode()
        ).hexdigest(),
        "original_package_count": len(old),
        "candidate_package_count": len(new),
        "all_other_records_unchanged": True,
        "accepted_prettyplease_alignment_unchanged": True,
        "unapproved_registry_version_or_checksum_drift": False,
        "advisory_qualification": False,
    }


def normalize_graph(metadata, work, lock):
    """Remove only actual package roots; retain graph and Cargo target meaning."""
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
    reverse, owner_nodes, full_graph, target_roster = [], {}, [], []
    alignment_ids = set(PRETTYPLEASE_CONSUMERS) | {
        ("prettyplease", "0.2.37", REGISTRY),
        ("prettyplease", "0.3.0", REGISTRY),
    }
    alignment, time_nodes, wasm_clock_nodes = {}, {}, []
    for package in packages.values():
        key = (package["name"], package["version"], package["source"])
        node = nodes[package["id"]]
        package_identity = identity(package)
        edges = sorted(
            [
                {
                    "edge_name": edge["name"],
                    "dependency": identity(packages[edge["pkg"]]),
                    "dep_kinds": sorted(edge["dep_kinds"], key=canonical),
                }
                for edge in node["deps"]
            ],
            key=canonical,
        )
        normalized = {
            "identity": package_identity,
            "features": sorted(node["features"]),
            "links": package.get("links"),
            "deps": edges,
        }
        full_graph.append(normalized)
        if key in alignment_ids:
            alignment[package["name"] + "@" + package["version"]] = normalized
        if key in TIME_FEATURE_IDENTITIES:
            time_nodes[package["name"]] = normalized
        if key == WASM_CLOCK_IDENTITY:
            wasm_clock_nodes.append(normalized)
        for edge in edges:
            if edge["dependency"] == identity(chrono[0]):
                reverse.append(
                    {
                        "dependent": package_identity,
                        "dependent_features": sorted(node["features"]),
                        **edge,
                    }
                )
        if package["source"] is None and package["name"] in OWNERS:
            require(package["name"] not in owner_nodes, "multiple actual owner nodes")
            owner_nodes[package["name"]] = {
                "identity": package_identity,
                "features": sorted(node["features"]),
                "time_edges": [
                    edge for edge in edges if edge["dependency"]["name"] == "time"
                ],
                "wasm_clock_edges": [
                    edge for edge in edges if edge["dependency"]["name"] == "js-sys"
                ],
                "chrono_edges": sum(
                    edge["dependency"]["name"] == "chrono" for edge in edges
                ),
            }
        targets = []
        target_root = (
            work if package["source"] is None else Path(package["manifest_path"]).parent
        )
        for target in package["targets"]:
            item = copy.deepcopy(target)
            item["src_path"] = (
                Path(item["src_path"]).relative_to(target_root).as_posix()
            )
            targets.append(item)
        target_roster.append(
            {"identity": package_identity, "targets": sorted(targets, key=canonical)}
        )
    require(
        len(alignment) == len(alignment_ids),
        "actual accepted prettyplease graph is incomplete",
    )
    require(len(time_nodes) == 3, "actual time feature closure nodes are incomplete")
    require(
        len(wasm_clock_nodes) == 1, "actual original wasm clock registry node is absent"
    )
    members = [
        Path(packages[key]["manifest_path"]).relative_to(work).as_posix()
        for key in metadata["workspace_members"]
    ]
    require(
        len(members) == len(set(members)), "workspace membership repeats a manifest"
    )
    return {
        "workspace_member_manifests": sorted(members),
        "package_count": len(packages),
        "resolve_node_count": len(nodes),
        "full_resolve_graph_sha256": hashlib.sha256(
            canonical(sorted(full_graph, key=canonical)).encode()
        ).hexdigest(),
        "all_package_targets_sha256": hashlib.sha256(
            canonical(sorted(target_roster, key=canonical)).encode()
        ).hexdigest(),
        "cargo_target_count": sum(len(row["targets"]) for row in target_roster),
        "chrono_identity": identity(chrono[0]),
        "chrono_features": sorted(nodes[chrono_id]["features"]),
        "chrono_reverse_edges": sorted(reverse, key=canonical),
        "rebound_owner_nodes": owner_nodes,
        "prettyplease_alignment": alignment,
        "time_feature_nodes": time_nodes,
        "wasm_clock_registry_node": wasm_clock_nodes[0],
    }


def graph_rebinding(metadata, spec, work, lock, bindings):
    actual = normalize_graph(metadata, work, lock)
    expected = spec["expected_graph"]
    require(
        len(actual["workspace_member_manifests"]) == 193
        and actual["workspace_member_manifests"] == spec["workspace_member_manifests"],
        "actual 193-member workspace roster changed",
    )
    require(
        actual["package_count"] == actual["resolve_node_count"] == 1525
        and actual["package_count"] == expected["package_count"]
        and actual["resolve_node_count"] == expected["resolve_node_count"],
        "actual package or resolve-node roster changed",
    )
    require(
        actual["full_resolve_graph_sha256"] == expected["full_resolve_graph_sha256"],
        "complete graph has unapproved identities, links, features, or edge conditions",
    )
    require(
        actual["all_package_targets_sha256"] == expected["all_package_targets_sha256"]
        and actual["cargo_target_count"] == expected["cargo_target_count"],
        "actual Cargo target roster or target semantics changed",
    )
    require(
        actual["prettyplease_alignment"] == expected["prettyplease_alignment"],
        "accepted prettyplease alignment changed",
    )
    require(
        actual["chrono_identity"] == expected["chrono_identity"]
        and actual["chrono_features"] == expected["chrono_features"],
        "remaining Chrono identity, checksum, or features changed",
    )
    require(
        len(actual["chrono_reverse_edges"]) == 29
        and actual["chrono_reverse_edges"] == expected["chrono_reverse_edges"],
        "actual Chrono inverse edges are not the accepted 31 minus the two owners",
    )
    require(
        actual["time_feature_nodes"] == expected["time_feature_nodes"]
        and all(
            "large-dates" not in row["features"]
            for row in actual["time_feature_nodes"].values()
        )
        and "wasm-bindgen" in actual["time_feature_nodes"]["time"]["features"],
        "actual time feature closure differs from the accepted original three nodes",
    )
    require(
        actual["wasm_clock_registry_node"] == expected["wasm_clock_registry_node"]
        and actual["wasm_clock_registry_node"]["features"]
        == ["default", "std", "unsafe-eval"],
        "actual wasm clock registry identity or existing feature closure changed",
    )
    require(
        actual["rebound_owner_nodes"].keys() == bindings.keys() == OWNERS,
        "actual owners are incomplete",
    )
    for name, node in actual["rebound_owner_nodes"].items():
        require(
            node == expected["rebound_owner_nodes"][name]
            and node["identity"]["manifest"] == bindings[name]["manifest"]
            and node["chrono_edges"] == 0
            and len(node["time_edges"]) == 1
            and len(node["wasm_clock_edges"]) == 1,
            "actual owner has not made its exact direct-edge replacement: " + name,
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
        clock = node["wasm_clock_edges"][0]
        require(
            clock["edge_name"] == "js_sys"
            and clock["dependency"] == actual["wasm_clock_registry_node"]["identity"]
            and clock["dep_kinds"] == [{"kind": None, "target": WASM_CLOCK_TARGET}],
            "actual owner browser clock dependency changed: " + name,
        )
    actual.update(
        {
            "actual_inverse_edge_count": 29,
            "original_inverse_edge_count": 31,
            "chrono_unmaintained_unresolved": True,
            "all_features_edges_are_not_default_or_runtime_activity": True,
            "shared_time_features_unchanged": True,
            "prior_large_dates_plan_not_applied": True,
            "wasm_clock_target_edges_added": 2,
            "existing_time_consumers_before": 33,
            "full_raw_graph_retained": True,
            "compatibility_or_advisory_qualified": False,
        }
    )
    return actual


def bazel_lock_correspondence(before_raw, after_raw, spec):
    """The complete Bazel postimage must be the accepted original bytes."""
    before, after = strict_json(before_raw), strict_json(after_raw)
    expected = spec["accepted_baseline_locks"]["MODULE.bazel.lock"]
    require(
        len(before_raw) == expected["bytes"]
        and hashlib.sha256(before_raw).hexdigest() == expected["sha256"],
        "Bazel preimage differs from the accepted original",
    )
    require(
        after_raw == before_raw and after == before,
        "Bazel postimage must remain byte-identical",
    )
    return {
        "full_postimage_byte_identical": True,
        "bytes": len(after_raw),
        "sha256": hashlib.sha256(after_raw).hexdigest(),
        "complete_postimage_retained": True,
        "advisory_or_native_qualification": False,
    }
