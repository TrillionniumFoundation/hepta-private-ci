"""All fixtures are synthetic; tests do not prove physical Laya execution."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".github/scripts"))

import hepta_neuron_materialize_weights as material
from hepta_neuron_freeze_dataset import freeze_dataset
from hepta_neuron_model_trials import InvalidTrial, read_json
from test_hepta_neuron_model_trials import fixture


class MaterializationTests(unittest.TestCase):
    def _catalog_and_cache(self, path):
        cache = path / "cache"
        cache.mkdir()
        content = {}
        for rel in material.REQUIRED:
            file = cache / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"synthetic-test-" + rel.encode())
            content[rel] = file
        weight = hashlib.sha256(content["model.safetensors"].read_bytes()).hexdigest()
        cat = {
            "repository": "local-fixture",
            "revision": "a" * 40,
            "variants": {
                "typed": {
                    "subfolder": "typed-decisions",
                    "model_id": "fixture-typed",
                    "weights_sha256": weight,
                }
            },
        }
        return cat, content

    def test_copy_is_explicit_offline_and_create_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog, files = self._catalog_and_cache(root)
            requests = []

            def fetch(repo, rel, rev, allow_net, cache):
                requests.append((repo, rel, rev, allow_net))
                return files[rel.removeprefix("typed-decisions/")]

            def inspect(cat, arm, dest):
                self.assertEqual(arm, "typed")
                for rel in material.REQUIRED:
                    self.assertTrue((dest / rel).is_file())
                return {
                    "weights_sha256": cat["variants"][arm]["weights_sha256"],
                    "artifact_tree_sha256": "f" * 64,
                }

            with (
                patch.object(material, "verify_catalog", side_effect=lambda c: c),
                patch.object(material, "inspect_local", side_effect=inspect),
            ):
                packet = material.materialize(
                    catalog, "typed", root / "model", fetcher=fetch
                )
                self.assertTrue(packet["local_weight_bytes_verified"])
                self.assertFalse(packet["promotion_authorized"])
                self.assertFalse(packet["network_permission_used"])
                self.assertEqual(len(requests), len(material.REQUIRED))
                self.assertTrue(
                    all(x[3] is False and x[2] == "a" * 40 for x in requests)
                )
                self.assertEqual(
                    (root / "model/model.safetensors").read_bytes(),
                    files["model.safetensors"].read_bytes(),
                )
                with self.assertRaisesRegex(InvalidTrial, "new absolute directory"):
                    material.materialize(
                        catalog, "typed", root / "model", fetcher=fetch
                    )

    def test_corrupt_bytes_cannot_finish_acquisition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog, files = self._catalog_and_cache(root)
            files["model.safetensors"].write_bytes(b"tampered")

            def fetch(repo, rel, rev, allow_net, cache):
                return files[rel.removeprefix("typed-decisions/")]

            with patch.object(material, "verify_catalog", side_effect=lambda c: c):
                with self.assertRaisesRegex(InvalidTrial, "digest mismatch"):
                    material.materialize(
                        catalog, "typed", root / "model", fetcher=fetch
                    )
            self.assertTrue((root / "model").is_dir())
            self.assertFalse((root / "model/rl_agent_config.json").exists())

    def test_artifact_destination_rejects_linked_ancestor_before_creating_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            inner = real / "inner"
            inner.mkdir()
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            catalog, _ = self._catalog_and_cache(root)
            dest = alias / "inner" / "new-model"
            with patch.object(material, "verify_catalog", side_effect=lambda c: c):
                with self.assertRaisesRegex(
                    InvalidTrial, "destination parent ancestry"
                ):
                    material.materialize(
                        catalog, "typed", dest, fetcher=lambda *args: None
                    )
            self.assertFalse(dest.exists())

    def test_laya_runner_rejects_linked_root_and_ancestor_before_model_io(self):
        from hepta_neuron_model_trials import MODEL_IDS, run_laya

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            physical = root / "physical"
            physical.mkdir()
            (physical / "child").mkdir()
            alias = root / "alias"
            alias.symlink_to(physical, target_is_directory=True)
            manifest = {
                "family": "decisions",
                "models": {
                    "laya": {
                        "model_id": MODEL_IDS["laya"],
                        "revision": "a" * 40,
                        "weights_sha256": "b" * 64,
                        "artifact_tree_sha256": "c" * 64,
                    }
                },
                "sdk_tree_sha256": "d" * 64,
            }
            for path in (alias, alias / "child"):
                with self.subTest(path=path):
                    with self.assertRaisesRegex(
                        InvalidTrial, "absolute, physical directory"
                    ):
                        run_laya(
                            manifest,
                            [],
                            "laya",
                            path,
                            "model.safetensors",
                            "cpu",
                            "d" * 64,
                        )

    def test_offline_hub_fetch_never_implies_network_permission(self):
        with patch.dict(sys.modules, {"huggingface_hub": MagicMock()}):
            module = sys.modules["huggingface_hub"]
            module.hf_hub_download.return_value = "/tmp/nonexistent/cache-file"
            result = material._hf_fetch(
                "org/repo", "typed-decisions/model.safetensors", "b" * 40, False, None
            )
            self.assertIsInstance(result, Path)
            module.hf_hub_download.assert_called_once_with(
                repo_id="org/repo",
                filename="typed-decisions/model.safetensors",
                revision="b" * 40,
                local_files_only=True,
                cache_dir=None,
            )


class DatasetFreezeTests(unittest.TestCase):
    def test_blind_export_revalidates_both_roles_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, rows, source, template = fixture(root, "heads")
            folder = root / "frozen"
            payload = freeze_dataset(template, source, folder)
            self.assertFalse(payload["promotion_authorized"])
            self.assertEqual(payload["observed_window_counts"]["future_2"], 1)
            self.assertEqual((folder / "manifest.json").exists(), True)
            result = [
                json.loads(x)
                for x in (folder / "blinded.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(rows), len(result))
            self.assertTrue(
                all("target_q24" not in x for x in result if x["split"] != "train")
            )
            self.assertTrue(
                all("target_q24" in x for x in result if x["split"] == "train")
            )
            self.assertTrue(
                "target_q24" in json.loads(source.read_text().splitlines()[-1])
            )
            self.assertNotIn("gold", (folder / "freeze-diagnostic.json").read_text())
            with self.assertRaisesRegex(InvalidTrial, "new absolute directory"):
                freeze_dataset(template, source, folder)

    def test_sealed_choice_labels_never_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, rows, source, template = fixture(root, "multilingual")
            out = root / "final"
            freeze_dataset(template, source, out)
            raw = (out / "blinded.jsonl").read_text()
            self.assertNotIn('"gold":', raw)
            self.assertNotIn('"is_ood":', raw)
            self.assertEqual(len(raw.splitlines()), len(rows))

    def test_tampered_seal_and_nonchronological_windows_block_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, rows, source, template = fixture(root, "decisions")
            rows[3]["observed_at_ms"] = 2000
            source.write_text("".join(json.dumps(r) + "\n" for r in rows))
            manifest.pop("dataset_sha256")
            manifest.pop("blind_dataset_sha256")
            template.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InvalidTrial, "time windows overlap"):
                freeze_dataset(template, source, root / "invalid")
            self.assertFalse((root / "invalid").exists())
            rows[3]["observed_at_ms"] = 4000
            source.write_text("".join(json.dumps(r) + "\n" for r in rows))
            manifest["dataset_sha256"] = "c" * 64
            template.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InvalidTrial, "conflicts with actual bytes"):
                freeze_dataset(template, source, root / "invalid")


if __name__ == "__main__":
    unittest.main()
