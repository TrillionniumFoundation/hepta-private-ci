"""Rebind artifact digests after adversarial changes to test semantic validation."""

import importlib
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import hepta_ui_native_aggregate as aggregate
import hepta_ui_native_evidence as evidence

# Production wrappers patch CLI entry points; keep other unittest modules isolated.
_aggregate, _workflow, _required = (
    aggregate.aggregate,
    evidence.WORKFLOW,
    evidence.REQUIRED,
)
qualified = importlib.import_module("hepta_ui_native_qualification_aggregate")
aggregate.aggregate, evidence.WORKFLOW, evidence.REQUIRED = (
    _aggregate,
    _workflow,
    _required,
)
fixtures = importlib.import_module("test_hepta_ui_native_aggregate")
supply_chain = importlib.import_module("hepta_ui_native_supply_chain")

APPLICATION_LOCK = '''version = 4
[[package]]
name = "demo"
version = "1.2.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
'''
OWNER_LOCK = '''version = 4
[[package]]
name = "owner"
version = "1.0.0"
'''


class SupplyChainAggregateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AggregateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.prepare_source_repository()
        self.implementation = "7" * 40
        self.supply_roots = []
        for profile in evidence.qualification_matrix()["include"]:
            bundle = self.fixture.root / (
                f"ui-native-qualification-{profile['runner']}-{profile['kind']}-"
                f"{self.fixture.candidate}-attempt-1"
            )
            root = bundle / "native-evidence/supply-chain"
            root.mkdir()
            self.supply_roots.append(root)
            package = aggregate.read_json(
                bundle / "native-package/package-receipt.json"
            )
            source = self.fixture.subjects[profile["kind"]]
            locks, components = self.inventories[profile["kind"]]
            receipt_path = bundle / "native-evidence/qualification.json"
            receipt = aggregate.read_json(receipt_path)
            receipt["dependencyLocks"] = locks
            self.write(receipt_path, receipt)
            platform = profile["os"].lower()
            properties = {
                "hepta:candidate-sha": self.fixture.candidate,
                "hepta:base-sha": self.fixture.base,
                "hepta:implementation-source-sha": self.implementation,
                "hepta:subject-source-sha": source["sourceSha"],
                "hepta:subject-source-tree": source["sourceTreeSha"],
                "hepta:source-kind": profile["kind"],
                "hepta:platform": platform,
                "hepta:production-qualified": "false",
                "hepta:release-authorized": "false",
            }
            sbom = {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {
                    "component": {
                        "hashes": [
                            {"alg": "SHA-256", "content": package["archiveSha256"]}
                        ],
                        "properties": [
                            {"name": key, "value": value}
                            for key, value in properties.items()
                        ],
                    },
                    "properties": [
                        {"name": "hepta:application-lock-sha256", "value": locks["apps/hepta-native/Cargo.lock"]},
                        {"name": "hepta:owner-lock-sha256", "value": locks["codex-rs/Cargo.lock"]},
                    ],
                },
                "components": components,
            }
            provenance = {
                "_type": "https://in-toto.io/Statement/v1",
                "predicateType": "https://slsa.dev/provenance/v1",
                "subject": [
                    {
                        "name": package["archive"],
                        "digest": {"sha256": package["archiveSha256"]},
                    }
                ],
                "predicate": {
                    "buildDefinition": {
                        "externalParameters": {
                            "candidateSha": self.fixture.candidate,
                            "baseSha": self.fixture.base,
                            "implementationSourceSha": self.implementation,
                            "subjectSourceSha": source["sourceSha"],
                            "subjectSourceTree": source["sourceTreeSha"],
                            "sourceKind": profile["kind"],
                            "platform": platform,
                        },
                        "internalParameters": {"runId": "101", "runAttempt": "1"},
                    }
                },
            }
            manifest = {
                "schema": "hepta.ui-native-supply-chain.v1",
                "candidateSha": self.fixture.candidate,
                "baseSha": self.fixture.base,
                "implementationSourceSha": self.implementation,
                **source,
                "sourceKind": profile["kind"],
                "platform": platform,
                "packageArchive": package["archive"],
                "packageSha256": package["archiveSha256"],
                "applicationCargoLockSha256": locks["apps/hepta-native/Cargo.lock"],
                "ownerCargoLockSha256": locks["codex-rs/Cargo.lock"],
                **dict.fromkeys(
                    (
                        "productionSigningObserved",
                        "physicalHostAcceptance",
                        "productionQualified",
                        "deploymentQualified",
                        "releaseAuthorized",
                    ),
                    False,
                ),
            }
            self.write(root / "sbom.cdx.json", sbom)
            self.write(root / "provenance.intoto.json", provenance)
            self.write(root / "supply-chain.json", manifest)
            self.rebind(root)

    def prepare_source_repository(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repository = Path(temp.name)

        def git(*args):
            return subprocess.check_output(
                ["git", *args], cwd=self.repository, text=True, stderr=subprocess.DEVNULL
            ).strip()

        git("init", "--quiet")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        for relative, content in (
            ("apps/hepta-native/Cargo.lock", APPLICATION_LOCK),
            ("codex-rs/Cargo.lock", OWNER_LOCK),
        ):
            path = self.repository / relative
            path.parent.mkdir(parents=True)
            path.write_text(content)
        git("add", ".")
        git("commit", "--quiet", "-m", "common source")
        common = git("rev-parse", "HEAD")
        application = self.repository / "apps/hepta-native/Cargo.lock"
        application.write_text(APPLICATION_LOCK + '''
[[package]]
name = "git-demo"
version = "2.0.0"
source = "git+https://example.invalid/dependency#aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
''')
        git("add", ".")
        git("commit", "--quiet", "-m", "candidate application dependency")
        candidate = git("rev-parse", "HEAD")
        git("checkout", "--quiet", "--detach", common)
        (self.repository / "codex-rs/Cargo.lock").write_text(
            OWNER_LOCK.replace('version = "1.0.0"', 'version = "1.1.0"')
        )
        git("add", ".")
        git("commit", "--quiet", "-m", "base owner dependency")
        base = git("rev-parse", "HEAD")
        subjects = aggregate.deterministic_subjects(self.repository, candidate, base)
        old_candidate = self.fixture.candidate
        replacements = {
            self.fixture.candidate: candidate,
            self.fixture.base: base,
            self.fixture.subjects["head"]["sourceTreeSha"]: subjects["head"]["sourceTreeSha"],
            self.fixture.subjects["merge"]["sourceSha"]: subjects["merge"]["sourceSha"],
            self.fixture.subjects["merge"]["sourceTreeSha"]: subjects["merge"]["sourceTreeSha"],
        }

        def replace(value):
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        for path in self.fixture.root.rglob("*.json"):
            self.write(path, replace(aggregate.read_json(path)))
        for bundle in self.fixture.root.iterdir():
            bundle.rename(bundle.with_name(bundle.name.replace(old_candidate, candidate)))
        self.fixture.candidate, self.fixture.base, self.fixture.subjects = candidate, base, subjects
        self.inventories = {}
        for kind, subject in subjects.items():
            locks, components = {}, []
            for relative, label in qualified.LOCK_PATHS.items():
                blob = subprocess.check_output(
                    ["git", "show", f"{subject['sourceSha']}:{relative}"], cwd=self.repository
                )
                locks[relative] = evidence.sha256(blob)
                path = self.repository / "snapshot" / kind / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
                components.extend(supply_chain.cargo_components(path, label))
            components.sort(key=lambda item: (item["name"], item["version"], item["bom-ref"]))
            self.inventories[kind] = locks, components

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def rebind(self, root):
        manifest = aggregate.read_json(root / "supply-chain.json")
        for key, name in (
            ("sbom", "sbom.cdx.json"),
            ("provenance", "provenance.intoto.json"),
        ):
            manifest[key] = {"path": name, "sha256": aggregate.file_digest(root / name)}
        self.write(root / "supply-chain.json", manifest)
        receipt_path = root.parent / "qualification.json"
        receipt = aggregate.read_json(receipt_path)
        receipt["supplyChain"] = {
            "manifestSha256": aggregate.file_digest(root / "supply-chain.json"),
            "sbomSha256": manifest["sbom"]["sha256"],
            "provenanceSha256": manifest["provenance"]["sha256"],
        }
        self.write(receipt_path, receipt)

    def run_aggregate(self):
        f = self.fixture
        return qualified.aggregate_with_supply_chain(
            f.root,
            candidate=f.candidate,
            base=f.base,
            workflow_sha=f.workflow,
            workflow_digest="1" * 64,
            run_id="101",
            attempt="1",
            subjects=f.subjects,
            implementation=self.implementation,
            repository=self.repository,
        )

    def mutate(self, name, change):
        root = self.supply_roots[0]
        path = root / name
        value = aggregate.read_json(path)
        change(value)
        self.write(path, value)
        self.rebind(root)

    def test_bound_six_subject_supply_chain_passes(self):
        result = self.run_aggregate()
        self.assertEqual(result["implementationSourceSha"], self.implementation)
        self.assertTrue(result["sbomGenerated"])

    def test_missing_deleted_or_substituted_dependencies_reject_even_with_new_hashes(self):
        root = self.supply_roots[0]
        path = root / "sbom.cdx.json"
        original = aggregate.read_json(path)
        mutations = (
            ("missing inventory", lambda value: value.pop("components")),
            ("empty inventory", lambda value: value.update(components=[])),
            ("deleted dependency", lambda value: value["components"].pop()),
            ("duplicate dependency", lambda value: value["components"].append(copy.deepcopy(value["components"][0]))),
            ("version substitution", lambda value: value["components"][0].update(version="9.9.9")),
            ("reference substitution", lambda value: value["components"][0].update({"bom-ref": "pkg:cargo/other@1?lock=owner"})),
            ("purl substitution", lambda value: value["components"][0].update(purl="pkg:cargo/other@1")),
            ("checksum substitution", lambda value: value["components"][0].update(hashes=[{"alg": "SHA-256", "content": "0" * 64}])),
            ("origin substitution", lambda value: value["components"][0]["properties"][1].update(value="registry+https://example.invalid/other")),
            ("owner substitution", lambda value: value["components"][0]["properties"][0].update(value="owner")),
            ("foreign subject", lambda value: value.update(components=copy.deepcopy(self.inventories["merge"][1]))),
        )
        for label, change in mutations:
            with self.subTest(label=label):
                value = copy.deepcopy(original)
                change(value)
                self.write(path, value)
                self.rebind(root)
                with self.assertRaisesRegex(ValueError, "SBOM dependency inventory"):
                    self.run_aggregate()

    def test_consistently_rehashed_foreign_lock_claims_reject(self):
        for root in self.supply_roots:
            manifest_path = root / "supply-chain.json"
            manifest = aggregate.read_json(manifest_path)
            if manifest["sourceKind"] != "head":
                continue
            manifest["applicationCargoLockSha256"] = "0" * 64
            self.write(manifest_path, manifest)
            sbom_path = root / "sbom.cdx.json"
            sbom = aggregate.read_json(sbom_path)
            sbom["metadata"]["properties"][0]["value"] = "0" * 64
            self.write(sbom_path, sbom)
            receipt_path = root.parent / "qualification.json"
            receipt = aggregate.read_json(receipt_path)
            receipt["dependencyLocks"]["apps/hepta-native/Cargo.lock"] = "0" * 64
            self.write(receipt_path, receipt)
            self.rebind(root)
        with self.assertRaisesRegex(ValueError, "SBOM dependency inventory"):
            self.run_aggregate()

    def test_modified_working_tree_locks_do_not_replace_exact_subject_blobs(self):
        for relative in qualified.LOCK_PATHS:
            (self.repository / relative).write_text("malicious working tree substitution")
        self.assertTrue(self.run_aggregate()["sbomGenerated"])

    def test_foreign_frozen_implementation_rejects_even_with_new_hashes(self):
        self.mutate(
            "supply-chain.json",
            lambda value: value.update(implementationSourceSha="8" * 40),
        )
        with self.assertRaisesRegex(ValueError, "frozen implementation"):
            self.run_aggregate()

    def test_foreign_package_rejects_even_with_new_hashes(self):
        self.mutate(
            "supply-chain.json", lambda value: value.update(packageSha256="9" * 64)
        )
        with self.assertRaisesRegex(ValueError, "retained package"):
            self.run_aggregate()

    def test_foreign_run_provenance_rejects_even_with_new_hashes(self):
        self.mutate(
            "provenance.intoto.json",
            lambda value: value["predicate"]["buildDefinition"][
                "internalParameters"
            ].update(runAttempt="2"),
        )
        with self.assertRaisesRegex(ValueError, "run identity"):
            self.run_aggregate()

    def test_foreign_sbom_package_rejects_even_with_new_hashes(self):
        self.mutate(
            "sbom.cdx.json",
            lambda value: value["metadata"]["component"].update(
                hashes=[{"alg": "SHA-256", "content": "0" * 64}]
            ),
        )
        with self.assertRaisesRegex(ValueError, "SBOM package"):
            self.run_aggregate()


if __name__ == "__main__":
    unittest.main()
