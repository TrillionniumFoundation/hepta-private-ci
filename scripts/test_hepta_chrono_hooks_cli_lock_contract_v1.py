"""Synthetic correspondence controls; no resolver or native qualification."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

import hepta_chrono_hooks_cli_lock_contract_v1 as contract


ROOT = Path(__file__).resolve().parent.parent


class ChronoHooksCliLockContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(
            (ROOT / "scripts/hepta_chrono_hooks_cli_lock_inputs_v1.json").read_bytes()
        )
        cls.before = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())
        cls.bindings = contract.source_bindings(cls.spec, ROOT)

    def proposed_lock(self):
        value = copy.deepcopy(self.before)
        for row in value["package"]:
            if row["name"] in contract.OWNERS:
                row["dependencies"] = sorted(
                    (set(row["dependencies"]) - {"chrono"}) | {"time", "js-sys"}
                )
        return value

    def normalized_graph(self):
        value = copy.deepcopy(self.spec["expected_graph"])
        value["workspace_member_manifests"] = list(
            self.spec["workspace_member_manifests"]
        )
        return value

    def test_two_source_manifests_bind_exact_lock_replacements(self):
        result = contract.lock_rebinding(
            self.before, self.proposed_lock(), self.bindings, self.spec
        )
        self.assertEqual(
            {row["name"] for row in result["changed_workspace_records"]},
            contract.OWNERS,
        )
        self.assertEqual(
            result["candidate_package_count"], result["original_package_count"]
        )
        self.assertTrue(result["all_other_records_unchanged"])
        graph = self.normalized_graph()
        with mock.patch.object(contract, "normalize_graph", return_value=graph):
            result = contract.graph_rebinding(
                {}, self.spec, ROOT, self.proposed_lock(), self.bindings
            )
        self.assertEqual(result["actual_inverse_edge_count"], 29)
        self.assertTrue(result["shared_time_features_unchanged"])
        self.assertTrue(result["prior_large_dates_plan_not_applied"])
        self.assertEqual(result["wasm_clock_target_edges_added"], 2)

    def test_registry_and_old_prettyplease_alignment_cannot_drift(self):
        for name, version, field, value in [
            ("cookie", "0.18.3", "checksum", "0" * 64),
            ("cookie", "0.18.3", "version", "0.18.4"),
            ("url", "2.5.9", "dependencies", ["unreviewed"]),
            ("bindgen", "0.73.2", "dependencies", ["prettyplease 0.2.37"]),
            ("bindgen", "0.72.1", "dependencies", ["prettyplease 0.3.0"]),
            ("prost-build", "0.14.4", "dependencies", ["prettyplease 0.3.0"]),
            ("js-sys", "0.3.106", "checksum", "0" * 64),
            ("js-sys", "0.3.106", "version", "0.3.107"),
        ]:
            with self.subTest(name=name, field=field):
                after = self.proposed_lock()
                next(
                    row
                    for row in after["package"]
                    if row["name"] == name and row["version"] == version
                )[field] = value
                with self.assertRaises(ValueError):
                    contract.lock_rebinding(
                        self.before, after, self.bindings, self.spec
                    )

    def test_missing_duplicate_extra_and_reintroduced_chrono_are_rejected(self):
        for operation in (
            "missing",
            "duplicate",
            "extra",
            "chrono",
            "omitted-time",
            "omitted-clock",
        ):
            with self.subTest(operation=operation):
                after = self.proposed_lock()
                if operation == "missing":
                    after["package"].pop(0)
                elif operation == "duplicate":
                    after["package"].append(copy.deepcopy(after["package"][0]))
                elif operation == "extra":
                    after["package"].append({"name": "unreviewed", "version": "0.0.0"})
                else:
                    row = next(
                        row for row in after["package"] if row["name"] == "codex-hooks"
                    )
                    if operation == "chrono":
                        row["dependencies"].append("chrono")
                    elif operation == "omitted-time":
                        row["dependencies"].remove("time")
                    else:
                        row["dependencies"].remove("js-sys")
                with self.assertRaises(ValueError):
                    contract.lock_rebinding(
                        self.before, after, self.bindings, self.spec
                    )

    def test_source_hash_cannot_authorize_unrelated_manifest_or_feature_changes(self):
        for operation in (
            "unrelated",
            "feature",
            "clock-version",
            "clock-target",
            "missing",
            "duplicate",
        ):
            with (
                self.subTest(operation=operation),
                tempfile.TemporaryDirectory(
                    prefix="chrono-hooks-cli-contract-"
                ) as directory,
            ):
                root = Path(directory)
                spec = copy.deepcopy(self.spec)
                for row in spec["manifest_rebindings"]:
                    destination = root / row["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((ROOT / row["path"]).read_bytes())
                row = spec["manifest_rebindings"][0]
                path = root / row["path"]
                if operation == "unrelated":
                    raw = (
                        path.read_bytes()
                        + b"\n[package.metadata.unreviewed]\nvalue = true\n"
                    )
                    path.write_bytes(raw)
                    row["after_sha256"] = hashlib.sha256(raw).hexdigest()
                elif operation == "feature":
                    raw = path.read_bytes().replace(
                        b'["wasm-bindgen"]', b'["large-dates", "wasm-bindgen"]'
                    )
                    path.write_bytes(raw)
                    row["after_sha256"] = hashlib.sha256(raw).hexdigest()
                    row["approved_time_dependency"]["features"] = [
                        "large-dates",
                        "wasm-bindgen",
                    ]
                elif operation == "clock-version":
                    raw = path.read_bytes().replace(
                        b'js-sys = "=0.3.106"', b'js-sys = "0.3"'
                    )
                    path.write_bytes(raw)
                    row["after_sha256"] = hashlib.sha256(raw).hexdigest()
                    row["approved_wasm_clock_dependency"]["js-sys"] = "0.3"
                elif operation == "clock-target":
                    raw = path.read_bytes().replace(b', target_os = "linux"', b"")
                    path.write_bytes(raw)
                    row["after_sha256"] = hashlib.sha256(raw).hexdigest()
                elif operation == "missing":
                    spec["manifest_rebindings"].pop()
                else:
                    spec["manifest_rebindings"].append(copy.deepcopy(row))
                with self.assertRaises(ValueError):
                    contract.source_bindings(spec, root)

    def test_full_graph_gate_rejects_roster_target_kind_feature_checksum_drift(self):
        original_spec = copy.deepcopy(self.spec)
        mutations = (
            lambda value: value.update(full_resolve_graph_sha256="0" * 64),
            lambda value: value.update(all_package_targets_sha256="0" * 64),
            lambda value: value.update(
                cargo_target_count=value["cargo_target_count"] - 1
            ),
            lambda value: value["workspace_member_manifests"].pop(),
            lambda value: value["chrono_reverse_edges"].pop(),
            lambda value: value["chrono_reverse_edges"][0]["dep_kinds"].append(
                {"kind": "dev", "target": "cfg(windows)"}
            ),
            lambda value: value["chrono_reverse_edges"][0]["dependent_features"].append(
                "unreviewed"
            ),
            lambda value: value["chrono_identity"].update(checksum="0" * 64),
            lambda value: value["chrono_features"].pop(),
            lambda value: value["prettyplease_alignment"]["bindgen@0.73.2"][
                "deps"
            ].pop(),
            lambda value: value["rebound_owner_nodes"]["codex-cli"]["time_edges"][0][
                "dep_kinds"
            ].append({"kind": "dev", "target": None}),
            lambda value: value["rebound_owner_nodes"]["codex-cli"]["wasm_clock_edges"][
                0
            ]["dep_kinds"][0].update(target=None),
            lambda value: value["rebound_owner_nodes"]["codex-hooks"][
                "wasm_clock_edges"
            ][0].update(edge_name="unreviewed_clock"),
        )
        expected_errors = (
            "complete graph has unapproved identities, links, features, or edge conditions",
            "actual Cargo target roster or target semantics changed",
            "actual Cargo target roster or target semantics changed",
            "actual 193-member workspace roster changed",
            "actual Chrono inverse edges are not the accepted 31 minus the two owners",
            "actual Chrono inverse edges are not the accepted 31 minus the two owners",
            "actual Chrono inverse edges are not the accepted 31 minus the two owners",
            "remaining Chrono identity, checksum, or features changed",
            "remaining Chrono identity, checksum, or features changed",
            "accepted prettyplease alignment changed",
            "actual owner has not made its exact direct-edge replacement: codex-cli",
            "actual owner has not made its exact direct-edge replacement: codex-cli",
            "actual owner has not made its exact direct-edge replacement: codex-hooks",
        )
        self.assertEqual(len(mutations), len(expected_errors))
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                changed = self.normalized_graph()
                mutation(changed)
                with mock.patch.object(
                    contract, "normalize_graph", return_value=changed
                ):
                    with self.assertRaises(ValueError) as caught:
                        contract.graph_rebinding(
                            {}, self.spec, ROOT, self.proposed_lock(), self.bindings
                        )
                self.assertEqual(str(caught.exception), expected_errors[index])
                self.assertEqual(self.spec, original_spec)

    def test_original_time_features_and_exact_wasm_clock_closure_are_required(self):
        original_spec = copy.deepcopy(self.spec)
        for name in ("time", "time-core", "time-macros"):
            with self.subTest(name=name):
                changed = self.normalized_graph()
                changed["time_feature_nodes"][name]["features"].append("large-dates")
                with mock.patch.object(
                    contract, "normalize_graph", return_value=changed
                ):
                    with self.assertRaises(ValueError) as caught:
                        contract.graph_rebinding(
                            {}, self.spec, ROOT, self.proposed_lock(), self.bindings
                        )
                self.assertEqual(
                    str(caught.exception),
                    "actual time feature closure differs from the accepted original three nodes",
                )
                self.assertEqual(self.spec, original_spec)
        for operation in ("clock-feature", "clock-checksum", "clock-edge"):
            with self.subTest(operation=operation):
                changed = self.normalized_graph()
                node = changed["wasm_clock_registry_node"]
                if operation == "clock-feature":
                    node["features"].remove("unsafe-eval")
                elif operation == "clock-checksum":
                    node["identity"]["checksum"] = "0" * 64
                else:
                    node["deps"].pop()
                with mock.patch.object(
                    contract, "normalize_graph", return_value=changed
                ):
                    with self.assertRaises(ValueError) as caught:
                        contract.graph_rebinding(
                            {}, self.spec, ROOT, self.proposed_lock(), self.bindings
                        )
                self.assertEqual(
                    str(caught.exception),
                    "actual wasm clock registry identity or existing feature closure changed",
                )
                self.assertEqual(self.spec, original_spec)
        for operation in ("missing-wasm", "new-edge", "wrong-checksum"):
            with self.subTest(operation=operation):
                changed = self.normalized_graph()
                node = changed["time_feature_nodes"]["time"]
                if operation == "missing-wasm":
                    node["features"].remove("wasm-bindgen")
                elif operation == "new-edge":
                    node["deps"].append(copy.deepcopy(node["deps"][0]))
                else:
                    node["identity"]["checksum"] = "0" * 64
                with mock.patch.object(
                    contract, "normalize_graph", return_value=changed
                ):
                    with self.assertRaises(ValueError) as caught:
                        contract.graph_rebinding(
                            {}, self.spec, ROOT, self.proposed_lock(), self.bindings
                        )
                self.assertEqual(
                    str(caught.exception),
                    "actual time feature closure differs from the accepted original three nodes",
                )
                self.assertEqual(self.spec, original_spec)

    def test_normalizer_keeps_target_paths_and_edge_conditions(self):
        lock = self.proposed_lock()
        expected = self.spec["expected_graph"]
        templates = copy.deepcopy(list(expected["prettyplease_alignment"].values()))
        templates.extend(copy.deepcopy(list(expected["time_feature_nodes"].values())))
        templates.append(copy.deepcopy(expected["wasm_clock_registry_node"]))
        templates.extend(
            {
                "identity": row["identity"],
                "features": row["features"],
                "links": None,
                "deps": row["time_edges"] + row["wasm_clock_edges"],
            }
            for row in expected["rebound_owner_nodes"].values()
        )
        templates.append(
            {
                "identity": expected["chrono_identity"],
                "features": expected["chrono_features"],
                "links": None,
                "deps": [],
            }
        )
        rows = {contract.canonical(row["identity"]): row for row in templates}
        for row in templates:
            for edge in row["deps"]:
                rows.setdefault(
                    contract.canonical(edge["dependency"]),
                    {
                        "identity": edge["dependency"],
                        "features": [],
                        "links": None,
                        "deps": [],
                    },
                )

        def fixture(root):
            def package_id(identity):
                prefix = (
                    ("path+file://" + str(root / identity["manifest"]))
                    if identity["source"] is None
                    else identity["source"]
                )
                return prefix + "#" + identity["name"] + "@" + identity["version"]

            packages, nodes, members = [], [], []
            for row in rows.values():
                value = row["identity"]
                identity = package_id(value)
                package_root = (
                    (root / value["manifest"]).parent
                    if value["manifest"]
                    else root / "registry" / (value["name"] + "-" + value["version"])
                )
                packages.append(
                    {
                        "id": identity,
                        "name": value["name"],
                        "version": value["version"],
                        "source": value["source"],
                        "links": row["links"],
                        "manifest_path": str(package_root / "Cargo.toml"),
                        "targets": [
                            {
                                "name": value["name"],
                                "kind": ["lib"],
                                "crate_types": ["lib"],
                                "src_path": str(package_root / "src/lib.rs"),
                                "edition": "2021",
                                "test": True,
                                "doctest": True,
                                "doc": True,
                            }
                        ],
                    }
                )
                nodes.append(
                    {
                        "id": identity,
                        "features": row["features"],
                        "deps": [
                            {
                                "name": edge["edge_name"],
                                "pkg": package_id(edge["dependency"]),
                                "dep_kinds": copy.deepcopy(edge["dep_kinds"]),
                            }
                            for edge in row["deps"]
                        ],
                    }
                )
                if value["source"] is None:
                    members.append(identity)
            return {
                "version": 1,
                "packages": packages,
                "resolve": {"nodes": nodes},
                "workspace_members": members,
            }

        first_root, second_root = Path("/owned/first"), Path("/owned/second")
        original = fixture(first_root)
        first = contract.normalize_graph(original, first_root, lock)
        self.assertEqual(
            first, contract.normalize_graph(fixture(second_root), second_root, lock)
        )
        changed = copy.deepcopy(original)
        next(node for node in changed["resolve"]["nodes"] if node["deps"])["deps"][0][
            "dep_kinds"
        ].append({"kind": "dev", "target": "cfg(windows)"})
        self.assertNotEqual(
            first["full_resolve_graph_sha256"],
            contract.normalize_graph(changed, first_root, lock)[
                "full_resolve_graph_sha256"
            ],
        )
        changed = copy.deepcopy(original)
        changed["packages"][0]["targets"][0]["kind"] = ["bin"]
        self.assertNotEqual(
            first["all_package_targets_sha256"],
            contract.normalize_graph(changed, first_root, lock)[
                "all_package_targets_sha256"
            ],
        )
        changed = copy.deepcopy(original)
        changed["packages"][0]["targets"][0]["src_path"] = "/unowned/lib.rs"
        with self.assertRaises(ValueError):
            contract.normalize_graph(changed, first_root, lock)
        next(package for package in original["packages"] if package["source"] is None)[
            "manifest_path"
        ] = "/unowned/Cargo.toml"
        with self.assertRaises(ValueError):
            contract.normalize_graph(original, first_root, lock)

    def test_bazel_original_full_bytes_must_remain_unchanged(self):
        before = (ROOT / "MODULE.bazel.lock").read_bytes()
        result = contract.bazel_lock_correspondence(before, before, self.spec)
        self.assertTrue(result["full_postimage_byte_identical"])
        for after in (before + b"\n", json.dumps(json.loads(before)).encode()):
            with self.assertRaises(ValueError):
                contract.bazel_lock_correspondence(before, after, self.spec)
        changed = json.loads(before)
        changed["registryFileHashes"]["https://unreviewed.invalid/MODULE.bazel"] = (
            "0" * 64
        )
        with self.assertRaises(ValueError):
            contract.bazel_lock_correspondence(
                before, json.dumps(changed).encode(), self.spec
            )

    def test_bazel_duplicate_keys_and_nonfinite_values_are_rejected(self):
        before = (ROOT / "MODULE.bazel.lock").read_bytes()
        invalid = (
            b'{"facts": {},"facts": {}}',
            b'{"facts": {"x": NaN}}',
            b'{"facts": {"x": Infinity}}',
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    contract.strict_json(raw)
                with self.assertRaises(ValueError):
                    contract.bazel_lock_correspondence(before, raw, self.spec)


if __name__ == "__main__":
    unittest.main()
