"""Real checkpoint bytes and independent SQLite connections; no pretrained model."""

from dataclasses import asdict
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import torch
from safetensors.torch import save

from parametric_owner import Frontier, ParametricOwner
from tensor_contract import sha256, tensor_layout


def checkpoint(directory, roots, *, scope="scope-a", marker=0, nonfinite=False):
    directory.mkdir()
    state = {
        "layer.lora_A.weight": torch.full(
            (2, 2), float("nan") if nonfinite else float(marker)
        )
    }
    weights = save(state)
    config = b'{"r":2,"target_modules":["q_proj","v_proj"]}'
    manifest = {
        "schema": "hepta.memory-lora-candidate.v2",
        "base_identity": "a" * 64,
        "scope": scope,
        "roots": list(roots),
        "tensor_layout": tensor_layout(state),
        "adapter_sha256": sha256(weights),
        "config_sha256": sha256(config),
        "training": {"marker": marker},
        "model_install_authority": False,
        "production_accepted": False,
    }
    data = json.dumps(manifest, sort_keys=True).encode()
    (directory / "lineage.json").write_bytes(data)
    (directory / "adapter_config.json").write_bytes(config)
    (directory / "adapter_model.safetensors").write_bytes(weights)
    return sha256(data)


def cas_worker(database, directory, manifest, parent, ready, start, results):
    owner = ParametricOwner(database)
    ready.put(True)
    start.wait(20)
    try:
        owner.activate(
            "memory",
            directory,
            manifest,
            scope="scope-a",
            expected_current=parent,
            generation=1,
            parent_manifest_sha256=parent,
            provider=lambda: Frontier("scope-a"),
            allowed_roots={"1" * 64},
        )
        results.put("accepted")
    except ValueError as error:
        results.put(str(error))


class ParametricOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "owner.sqlite"
        self.owner = ParametricOwner(self.database)
        self.view = Frontier("scope-a")
        self.directory = self.root / "initial"
        self.digest = checkpoint(self.directory, {"1" * 64})
        self.initial = self.activate(self.directory, self.digest)

    def activate(
        self, directory, digest, *, parent=None, generation=0, roots=("1" * 64,)
    ):
        return self.owner.activate(
            "memory",
            directory,
            digest,
            scope="scope-a",
            expected_current=parent,
            generation=generation,
            parent_manifest_sha256=parent,
            provider=lambda: self.view,
            allowed_roots=roots,
        )

    def invoke(self, callback, **kwargs):
        return self.owner.invoke(
            "memory", "scope-a", lambda: self.view, callback, **kwargs
        )

    def test_restart_retains_pointer_and_only_passes_metadata(self):
        restarted = ParametricOwner(self.database)
        self.assertEqual(restarted.current("memory", "scope-a"), self.initial)
        result = restarted.invoke("memory", "scope-a", lambda: self.view, asdict)
        self.assertEqual(result, asdict(self.initial))
        self.assertIsNone(restarted.current("memory", "scope-b"))
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            self.owner.invoke("memory", "scope-b", lambda: self.view, callback)
        callback.assert_not_called()

    def test_independent_processes_cannot_both_win_cas(self):
        candidates = []
        for index in (1, 2):
            directory = self.root / f"candidate-{index}"
            candidates.append(
                (directory, checkpoint(directory, {"1" * 64}, marker=index))
            )
        ctx = multiprocessing.get_context("spawn")
        ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
        processes = [
            ctx.Process(
                target=cas_worker,
                args=(
                    str(self.database),
                    str(path),
                    digest,
                    self.digest,
                    ready,
                    start,
                    results,
                ),
            )
            for path, digest in candidates
        ]
        for process in processes:
            process.start()
        for _ in processes:
            self.assertTrue(ready.get(timeout=30))
        start.set()
        observed = [results.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(30)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(
            sorted(observed), ["accepted", "active version CAS or generation mismatch"]
        )
        self.assertEqual(self.owner.current("memory", "scope-a").generation, 1)

    def test_rejected_ancestor_frontier_survives_restart_and_clean_replay(self):
        self.view = Frontier("scope-a", 2, ("1" * 64,))
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            self.invoke(callback)
        callback.assert_not_called()
        self.owner = ParametricOwner(self.database)
        for view in (Frontier("scope-a", 1), Frontier("scope-a", 2)):
            self.view = view
            with self.assertRaisesRegex(ValueError, "rollback or same-epoch fork"):
                self.invoke(callback)
        self.view = Frontier("scope-a", 2, ("1" * 64,))
        clean = self.root / "clean"
        clean_digest = checkpoint(clean, {"2" * 64}, marker=3)
        recovered = self.activate(
            clean, clean_digest, parent=self.digest, generation=1, roots={"2" * 64}
        )
        self.assertEqual(self.invoke(lambda active: active), recovered)
        self.assertEqual(recovered.roots, ("2" * 64,))

    def test_query_revocation_rejects_before_callback_and_is_latched(self):
        self.view = Frontier("scope-a", 1, ("3" * 64,))
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            self.invoke(callback, query_roots=("3" * 64,))
        callback.assert_not_called()
        self.owner = ParametricOwner(self.database)
        self.view = Frontier("scope-a")
        with self.assertRaisesRegex(ValueError, "rollback"):
            self.invoke(callback)
        callback.assert_not_called()

    def test_frontier_change_during_callback_discards_result(self):
        def forward(cell):
            self.view = Frontier("scope-a", 3, ("1" * 64,))
            return "must not escape"

        with self.assertRaisesRegex(ValueError, "frontier or active version changed"):
            self.invoke(forward)
        self.owner = ParametricOwner(self.database)
        self.view = Frontier("scope-a", 2)
        with self.assertRaisesRegex(ValueError, "rollback"):
            self.invoke(Mock())

    def test_cas_change_during_callback_discards_result(self):
        new_dir = self.root / "next"
        new_digest = checkpoint(new_dir, {"1" * 64}, marker=1)

        def forward(cell):
            other = ParametricOwner(self.database)
            other.activate(
                "memory",
                new_dir,
                new_digest,
                scope="scope-a",
                expected_current=self.digest,
                generation=1,
                parent_manifest_sha256=self.digest,
                provider=lambda: self.view,
                allowed_roots={"1" * 64},
            )
            return "stale"

        with self.assertRaisesRegex(ValueError, "active version changed"):
            self.invoke(forward)
        self.assertEqual(
            self.owner.current("memory", "scope-a").manifest_sha256, new_digest
        )

    def test_checkpoint_mutation_before_and_during_callback_is_rejected(self):
        weights = self.directory / "adapter_model.safetensors"
        original = weights.read_bytes()
        weights.write_bytes(original + b"changed")
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "content binding"):
            self.invoke(callback)
        callback.assert_not_called()
        weights.write_bytes(original)

        def forward(cell):
            weights.write_bytes(original + b"changed again")
            return "must not escape"

        with self.assertRaisesRegex(ValueError, "content binding"):
            self.invoke(forward)

    def test_parent_generation_scope_allowed_roots_and_nonfinite_are_enforced(self):
        candidate = self.root / "next"
        digest = checkpoint(candidate, {"2" * 64}, marker=1)
        for changes in (
            {"parent": "f" * 64, "generation": 1, "roots": {"2" * 64}},
            {"parent": self.digest, "generation": 0, "roots": {"2" * 64}},
            {"parent": self.digest, "generation": 1, "roots": {"1" * 64}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.activate(candidate, digest, **changes)
            self.assertEqual(self.owner.current("memory", "scope-a"), self.initial)
        bad = self.root / "nonfinite"
        bad_digest = checkpoint(bad, {"1" * 64}, nonfinite=True)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            self.activate(bad, bad_digest, parent=self.digest, generation=1)
        foreign = self.root / "foreign"
        foreign_digest = checkpoint(foreign, {"1" * 64}, scope="scope-b")
        with self.assertRaisesRegex(ValueError, "scope"):
            self.activate(foreign, foreign_digest, parent=self.digest, generation=1)
        manifest = candidate / "lineage.json"
        overflow = manifest.read_bytes().replace(b'"marker": 1', b'"marker": 1e999')
        manifest.write_bytes(overflow)
        with self.assertRaisesRegex(ValueError, "Out of range float"):
            self.activate(
                candidate,
                sha256(overflow),
                parent=self.digest,
                generation=1,
                roots={"2" * 64},
            )

    def test_failed_activation_latches_frontier_and_same_digest_cas_uses_generation(
        self,
    ):
        self.activate(self.directory, self.digest, parent=self.digest, generation=1)
        with self.assertRaisesRegex(ValueError, "CAS or generation"):
            self.activate(self.directory, self.digest, parent=self.digest, generation=1)
        self.view = Frontier("scope-a", 4)
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            self.activate(self.directory, "f" * 64, parent=self.digest, generation=2)
        self.owner = ParametricOwner(self.database)
        self.view = Frontier("scope-a", 3)
        with self.assertRaisesRegex(ValueError, "rollback"):
            self.invoke(Mock())


if __name__ == "__main__":
    unittest.main()
