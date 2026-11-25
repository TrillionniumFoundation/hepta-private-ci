"""Bounded, synthetic contract controls; never a resolver or native result."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

import hepta_chrono_lock_contract_v1 as contract


ROOT = Path(__file__).resolve().parent.parent


class ChronoLockContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(
            (ROOT / "scripts/hepta_chrono_leaf_lock_inputs_v1.json").read_bytes()
        )
        cls.before = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())
        cls.bindings = contract.source_bindings(cls.spec, ROOT)

    def proposed_lock(self):
        value = copy.deepcopy(self.before)
        for row in value["package"]:
            key = (row["name"], row["version"], row.get("source"))
            if row["name"] in contract.OWNERS:
                row["dependencies"] = sorted(
                    (set(row["dependencies"]) - {"chrono"}) | {"time"}
                )
            elif key in contract.PRETTYPLEASE_CONSUMERS:
                row["dependencies"] = sorted(
                    "prettyplease " + contract.PRETTYPLEASE_CONSUMERS[key]
                    if dependency == "prettyplease"
                    else dependency
                    for dependency in row["dependencies"]
                )
        value["package"].append(
            copy.deepcopy(self.spec["prettyplease_alignment"]["new_lock_record"])
        )
        return value

    def test_complete_five_manifest_and_prettyplease_correspondence(self):
        result = contract.lock_rebinding(
            self.before, self.proposed_lock(), self.bindings, self.spec
        )
        self.assertEqual(
            {row["name"] for row in result["changed_workspace_records"]},
            contract.OWNERS,
        )
        self.assertEqual(len(result["prettyplease_reference_changes"]), 5)
        self.assertEqual(
            result["candidate_package_count"], result["original_package_count"] + 1
        )

    def test_registry_checksum_version_and_unrelated_dependency_drift_are_rejected(
        self,
    ):
        for field, value in [
            ("checksum", "0" * 64),
            ("version", "0.18.4"),
            ("dependencies", ["unreviewed-dependency"]),
        ]:
            with self.subTest(field=field):
                after = self.proposed_lock()
                next(row for row in after["package"] if row["name"] == "cookie")[
                    field
                ] = value
                with self.assertRaises(ValueError):
                    contract.lock_rebinding(
                        self.before, after, self.bindings, self.spec
                    )

    def test_missing_duplicate_and_unsupported_package_identities_are_rejected(self):
        for operation in ("missing", "duplicate", "extra"):
            with self.subTest(operation=operation):
                after = self.proposed_lock()
                if operation == "missing":
                    after["package"].pop(0)
                elif operation == "duplicate":
                    after["package"].append(copy.deepcopy(after["package"][0]))
                else:
                    after["package"].append({"name": "unreviewed", "version": "0.0.0"})
                with self.assertRaises(ValueError):
                    contract.lock_rebinding(
                        self.before, after, self.bindings, self.spec
                    )

    def test_old_prettyplease_consumers_and_all_five_chrono_removals_are_required(self):
        for name, version, dependency in [
            ("bindgen", "0.73.2", "prettyplease 0.2.37"),
            ("bindgen", "0.72.1", "prettyplease 0.3.0"),
            ("codex-agent-identity", "0.0.0", "chrono"),
        ]:
            with self.subTest(name=name, version=version):
                after = self.proposed_lock()
                row = next(
                    row
                    for row in after["package"]
                    if row["name"] == name and row["version"] == version
                )
                if name == "codex-agent-identity":
                    row["dependencies"].append(dependency)
                else:
                    row["dependencies"] = [
                        dependency if item.startswith("prettyplease ") else item
                        for item in row["dependencies"]
                    ]
                with self.assertRaises(ValueError):
                    contract.lock_rebinding(
                        self.before, after, self.bindings, self.spec
                    )

    def test_actual_source_manifest_hash_alone_does_not_authorize_other_changes(self):
        with tempfile.TemporaryDirectory(
            prefix="chrono-manifest-contract-"
        ) as directory:
            root = Path(directory)
            spec = copy.deepcopy(self.spec)
            for row in spec["manifest_rebindings"]:
                destination = root / row["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / row["path"]).read_bytes())
            row = spec["manifest_rebindings"][0]
            path = root / row["path"]
            raw = path.read_bytes() + b"\n[features]\nunreviewed = []\n"
            path.write_bytes(raw)
            row["after_sha256"] = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                contract.source_bindings(spec, root)

    def normalized_graph(self):
        value = copy.deepcopy(self.spec["expected_graph"])
        value["workspace_member_manifests"] = self.spec["workspace_member_manifests"]
        time = next(
            row for row in self.proposed_lock()["package"] if row["name"] == "time"
        )
        for name, node in value["rebound_owner_nodes"].items():
            node["chrono_edges"] = 0
            node["time_edges"] = [
                {
                    "edge_name": "time",
                    "dep_kinds": [{"kind": None, "target": None}],
                    "dependency": {
                        "name": "time",
                        "version": time["version"],
                        "source": time["source"],
                        "checksum": time["checksum"],
                        "manifest": None,
                    },
                }
            ]
        return value

    def test_graph_gate_rejects_wrong_roster_target_feature_checksum_and_alignment(
        self,
    ):
        actual = self.normalized_graph()
        with mock.patch.object(contract, "normalize_graph", return_value=actual):
            contract.graph_rebinding(
                {}, self.spec, ROOT, self.proposed_lock(), self.bindings
            )
        mutations = (
            lambda value: value.update(full_resolve_graph_sha256="0" * 64),
            lambda value: value["workspace_member_manifests"].pop(),
            lambda value: value["chrono_reverse_edges"].pop(),
            lambda value: value["chrono_reverse_edges"][0]["dep_kinds"].append(
                {"kind": "dev", "target": "cfg(windows)"}
            ),
            lambda value: value["chrono_reverse_edges"][0]["dependent_features"].append(
                "unreviewed"
            ),
            lambda value: value["chrono_reverse_edges"][0]["dependency"].update(
                checksum="0" * 64
            ),
            lambda value: value["prettyplease_alignment"]["bindgen@0.73.2"][
                "deps"
            ].pop(),
            lambda value: value["rebound_owner_nodes"]["codex-agent-identity"][
                "time_edges"
            ][0]["dep_kinds"].append({"kind": "dev", "target": None}),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                changed = copy.deepcopy(actual)
                mutation(changed)
                with mock.patch.object(
                    contract, "normalize_graph", return_value=changed
                ):
                    with self.assertRaises(ValueError):
                        contract.graph_rebinding(
                            {}, self.spec, ROOT, self.proposed_lock(), self.bindings
                        )

    def test_normalizer_removes_only_owned_root_and_retains_edge_conditions(self):
        lock = self.proposed_lock()
        expected = self.spec["expected_graph"]
        templates = copy.deepcopy(list(expected["prettyplease_alignment"].values()))
        templates.extend(
            {
                "identity": row["identity"],
                "features": row["features"],
                "links": None,
                "deps": [],
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
                packages.append(
                    {
                        "id": identity,
                        "name": value["name"],
                        "version": value["version"],
                        "source": value["source"],
                        "links": row["links"],
                        "manifest_path": str(root / value["manifest"])
                        if value["manifest"]
                        else "/registry/Cargo.toml",
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
        next(package for package in original["packages"] if package["source"] is None)[
            "manifest_path"
        ] = "/unowned/Cargo.toml"
        with self.assertRaises(ValueError):
            contract.normalize_graph(original, first_root, lock)

    def test_bazel_only_accepts_one_exact_new_fact(self):
        before = json.loads((ROOT / "MODULE.bazel.lock").read_bytes())
        after = copy.deepcopy(before)
        after["facts"][contract.CRATE_FACTS]["prettyplease_0.3.0"] = json.dumps(
            self.spec["prettyplease_alignment"]["new_bazel_fact"]
        )
        contract.bazel_lock_correspondence(before, after, self.spec)
        after["registryFileHashes"]["https://unreviewed.invalid/MODULE.bazel"] = (
            "0" * 64
        )
        with self.assertRaises(ValueError):
            contract.bazel_lock_correspondence(before, after, self.spec)

    def test_bazel_duplicate_keys_cannot_hide_a_different_fact(self):
        before = json.loads((ROOT / "MODULE.bazel.lock").read_bytes())
        after = copy.deepcopy(before)
        raw = json.dumps(self.spec["prettyplease_alignment"]["new_bazel_fact"])
        after["facts"][contract.CRATE_FACTS]["prettyplease_0.3.0"] = (
            '{"dependencies": [],' + raw[1:]
        )
        with self.assertRaises(ValueError):
            contract.bazel_lock_correspondence(before, after, self.spec)


if __name__ == "__main__":
    unittest.main()
