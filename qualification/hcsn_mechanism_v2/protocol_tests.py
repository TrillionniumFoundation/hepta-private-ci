"""Phase ownership and source-drift tests on isolated temporary fixtures."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import protocol


class ProtocolTests(unittest.TestCase):
    def _binding_fixture(self, root):
        output, registry = root / "output", root / "registry"
        output.mkdir()
        registry.mkdir()
        manifest_path = root / "manifest.json"
        protocol.save(manifest_path, {"toy": True})
        plan = {
            "seeds": [7],
            **{stage: {"tasks": ["toy"]} for stage in protocol.STAGES},
        }
        entries = []
        for stage in protocol.STAGES:
            for task, seed in protocol.cases(plan, stage):
                relative = f"fit/{stage}/{task}-{seed}.json"
                path = output / relative
                path.parent.mkdir(parents=True)
                protocol.save(path, {"weight": 1})
                entries.append(
                    {
                        "stage": stage,
                        "task": task,
                        "seed": seed,
                        "path": relative,
                        "sha256": protocol.sha(path),
                    }
                )
        selected = {
            "phase": "fit",
            "manifest_sha256": protocol.sha(manifest_path),
            "cases": entries,
        }
        manifest = {"registry": str(registry), "allocation_key": "toy", "plan": plan}
        return output, registry, manifest_path, manifest, selected

    def test_source_drift_and_unregistered_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "qualification/hcsn_mechanism_v2/toy.py"
            path.parent.mkdir(parents=True)
            raw = b"x = 1\n"
            path.write_bytes(raw)
            source = {
                "publication_status": "published",
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "files": [
                    {
                        "path": str(path.relative_to(root)),
                        "mode": "100644",
                        "size": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "git_blob": hashlib.sha1(b"blob 6\0" + raw).hexdigest(),
                    }
                ],
            }
            protocol.validate_source(source, root)
            path.write_bytes(b"x = 2\n")
            with self.assertRaises(ValueError):
                protocol.validate_source(source, root)
            path.write_bytes(raw)
            (path.parent / "unregistered.py").write_text("y=2\n")
            with self.assertRaises(ValueError):
                protocol.validate_source(source, root)

    def test_registry_prevents_same_phase_with_another_output_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            protocol.save(manifest_path, {"toy": True})
            registry = root / "registry"
            registry.mkdir()
            manifest = {"registry": str(registry), "allocation_key": "toy"}
            with patch.object(protocol, "verify", return_value=manifest):
                protocol.claim_phase(manifest_path, root / "first", "fit")
                with self.assertRaises(FileExistsError):
                    protocol.claim_phase(manifest_path, root / "second", "fit")

    def test_changed_fit_record_cannot_unlock_final(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, registry, manifest_path, manifest, selected = self._binding_fixture(
                root
            )
            protocol.save(output / "selection.json", selected)
            selection_sha = protocol.sha(output / "selection.json")
            fitted = output / selected["cases"][0]["path"]
            fitted.write_text('{"weight": 2}\n')
            with patch.object(protocol, "verify", return_value=manifest):
                with self.assertRaises(ValueError):
                    protocol.claim_phase(manifest_path, output, "final", selection_sha)
            self.assertFalse((registry / "toy.final.consumed.json").exists())

    def test_omitted_fit_record_cannot_unlock_final(self):
        with tempfile.TemporaryDirectory() as directory:
            output, registry, path, manifest, selected = self._binding_fixture(
                Path(directory)
            )
            selected["cases"].pop()
            protocol.save(output / "selection.json", selected)
            with patch.object(protocol, "verify", return_value=manifest):
                with self.assertRaisesRegex(ValueError, "every expected fitted case"):
                    protocol.claim_phase(
                        path, output, "final", protocol.sha(output / "selection.json")
                    )
            self.assertFalse((registry / "toy.final.consumed.json").exists())

    def test_embedded_plan_edit_cannot_preserve_binding_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = {"namespace": "toy-independent", "budget": 4}
            source = {"source_commit": "a" * 40}
            key = hashlib.sha256(plan["namespace"].encode()).hexdigest()
            allocation = {
                "namespace": plan["namespace"],
                "plan_sha256": "raw-plan-sha",
                "source_manifest_sha256": "raw-source-sha",
                "source_commit": "a" * 40,
                "plan_object_sha256": protocol.object_sha(plan),
                "source_object_sha256": protocol.object_sha(source),
            }
            protocol.save(root / f"{key}.allocation.json", allocation)
            manifest = {
                **allocation,
                "plan": plan,
                "source": source,
                "registry": str(root),
                "allocation_key": key,
                "source_root": str(protocol.ROOT),
                "runtime": {"toy": True},
            }
            plan["budget"] = 8
            path = root / "manifest.json"
            protocol.save(path, manifest)
            with (
                patch.object(protocol, "validate_plan"),
                patch.object(protocol, "validate_source"),
                patch.object(protocol, "runtime", return_value={"toy": True}),
            ):
                with self.assertRaisesRegex(ValueError, "allocation binding changed"):
                    protocol.verify(path)


if __name__ == "__main__":
    unittest.main()
