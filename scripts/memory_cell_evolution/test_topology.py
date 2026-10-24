"""Real owner admission with tiny tensor fixtures; no model fit or generation."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from evolution_common import canonical, digest, retain, transaction
from topology_contract import empty_policy
from topology_owner import ActualOwners
from topology_store import TopologyStore

SCRIPTS = Path(__file__).resolve().parents[1]


class TopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners = ActualOwners(SCRIPTS)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.roots = sorted(digest("source-" + str(i)) for i in range(4))
        self.view = dict(scope="topology-tests", epoch=4, roots=self.roots, revoked=[])
        self.store = TopologyStore(
            self.root / "topology",
            self.view["scope"],
            lambda: deepcopy(self.view),
            self.owners,
        )
        self.original = self.fixture("initial", self.roots)
        self.store.prepare(
            "boot",
            "bootstrap",
            expected_generation=0,
            inputs=[],
            candidates=[self.candidate("parent", self.original, self.roots)],
        )
        self.store.commit("boot")

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, name, roots):
        directory = self.root / name
        directory.mkdir()
        header = canonical(
            {"adapter.a": {"dtype": "F32", "shape": [1, 2], "data_offsets": [0, 8]}}
        )
        header += b" " * (-len(header) % 8)
        tensor = struct.pack("<Q", len(header)) + header + struct.pack("<ff", 0.25, 0.5)
        (directory / "adapter_model.safetensors").write_bytes(tensor)
        config = canonical({"fixture_only": True})
        (directory / "adapter_config.json").write_bytes(config)
        lineage = dict(
            schema="hepta.memory-lora-candidate.v2",
            base_identity=digest("tiny-structural-fixture"),
            scope=self.view["scope"],
            roots=roots,
            tensor_layout={"adapter.a": {"shape": [1, 2], "dtype": "torch.float32"}},
            adapter_sha256=hashlib.sha256(tensor).hexdigest(),
            config_sha256=hashlib.sha256(config).hexdigest(),
            training=dict(
                initialization="frozen_base",
                inherited_roots=[],
                learned_parent_manifest_sha256=None,
                source_digests=roots,
                fixture_not_training=True,
            ),
            model_install_authority=False,
            production_accepted=False,
        )
        retain(directory / "lineage.json", lineage)
        return directory

    def candidate(self, name, directory, support, derivation="clean_replay"):
        return dict(
            cell_id=name,
            role="semantic",
            directory=str(directory),
            manifest_sha256=hashlib.sha256(
                (directory / "lineage.json").read_bytes()
            ).hexdigest(),
            support_roots=support,
            derivation=derivation,
        )

    def split(self):
        candidates = [
            self.candidate("left", self.original, self.roots[:2], "reuse"),
            self.candidate("right", self.original, self.roots[2:], "reuse"),
        ]
        self.store.prepare(
            "split",
            "split",
            expected_generation=1,
            inputs=["parent"],
            candidates=candidates,
        )
        return self.store.commit("split")

    def test_real_owner_split_merge_rollback_generations(self):
        self.split()
        self.assertEqual(self.store.snapshot()["generation"], 2)
        self.assertEqual(set(self.store.snapshot()["cells"]), {"left", "right"})
        self.assertEqual(
            self.store.invoke("left", self.roots[:1], lambda active: active.cell_id),
            "left",
        )
        with self.assertRaisesRegex(ValueError, "not live"):
            self.store.invoke("parent", self.roots[:1], lambda active: active)
        fresh = self.fixture("merged", self.roots)
        self.store.prepare(
            "merge",
            "merge",
            expected_generation=2,
            inputs=["left", "right"],
            candidates=[self.candidate("parent", fresh, self.roots)],
        )
        merged = self.store.commit("merge")
        self.assertEqual(self.store.snapshot()["cells"]["parent"]["version"], 1)
        self.assertEqual(self.store.commit("merge"), merged)
        rolled = self.store.rollback("rollback", 2, expected_generation=3)
        self.assertEqual(rolled["generation"], 4)
        self.assertEqual(
            {c: v["version"] for c, v in self.store.snapshot()["cells"].items()},
            {"left": 1, "right": 1},
        )
        reopened = TopologyStore(
            self.store.root,
            self.view["scope"],
            lambda: deepcopy(self.view),
            self.owners,
        )
        self.assertEqual(reopened.snapshot(), self.store.snapshot())

    def test_prepared_partial_failure_never_changes_live_population(self):
        initial = self.store.snapshot()
        wrong = self.candidate("right", self.original, self.roots[2:], "reuse")
        wrong["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "manifest digest"):
            self.store.prepare(
                "partial",
                "split",
                expected_generation=1,
                inputs=["parent"],
                candidates=[
                    self.candidate("left", self.original, self.roots[:2], "reuse"),
                    wrong,
                ],
            )
        self.assertEqual(self.store.snapshot(), initial)
        self.assertEqual(
            self.store.invoke("parent", self.roots[:1], lambda active: active.cell_id),
            "parent",
        )
        self.store.abort("partial")
        with self.assertRaisesRegex(ValueError, "prepared"):
            self.store.commit("partial")

    def test_withdrawal_reaches_both_inherited_children_and_rollback(self):
        self.split()
        withdrawn = self.roots[0]
        self.view.update(epoch=5, roots=self.roots[1:], revoked=[withdrawn])
        calls = []
        for name, root in (("left", self.roots[1]), ("right", self.roots[2])):
            with self.assertRaisesRegex(ValueError, "(support|ancestor)"):
                self.store.invoke(name, [root], lambda active: calls.append(active))
        self.assertEqual(calls, [])
        with self.assertRaisesRegex(ValueError, "(support|withdrawn|current)"):
            self.store.rollback("unsafe-rollback", 1, expected_generation=2)
        clean_left = self.fixture("clean-left", self.roots[1:2])
        clean_right = self.fixture("clean-right", self.roots[2:])
        self.store.prepare(
            "clean",
            "refresh",
            expected_generation=2,
            inputs=["left", "right"],
            candidates=[
                self.candidate("left", clean_left, self.roots[1:2]),
                self.candidate("right", clean_right, self.roots[2:]),
            ],
        )
        self.store.commit("clean")
        self.assertEqual(
            self.store.invoke(
                "right", self.roots[2:3], lambda active: list(active.roots)
            ),
            self.roots[2:],
        )

    def test_frontier_cannot_roll_back_after_failed_admission(self):
        old = deepcopy(self.view)
        self.view.update(epoch=5, roots=self.roots[1:], revoked=self.roots[:1])
        with self.assertRaises(ValueError):
            self.store.invoke("parent", self.roots[:1], lambda active: active)
        self.view = old
        with self.assertRaisesRegex(ValueError, "rollback"):
            self.store.invoke("parent", self.roots[1:2], lambda active: active)

    def test_inflight_rewire_suppresses_answer_and_preserves_model_call(self):
        calls = []

        def reader(active):
            calls.append(active.cell_id)
            self.store.prepare(
                "rewire", "rewire", expected_generation=1, inputs=[], candidates=[]
            )
            self.store.commit("rewire")
            return "raw answer"

        with self.assertRaisesRegex(ValueError, "in-flight"):
            self.store.invoke("parent", self.roots[:1], reader)
        self.assertEqual(calls, ["parent"])

    def test_stale_prepare_and_tampered_checkpoint_reject(self):
        self.store.prepare(
            "rewire", "rewire", expected_generation=1, inputs=[], candidates=[]
        )
        self.view.update(epoch=5, roots=self.roots + [digest("arriving-source")])
        with self.assertRaisesRegex(ValueError, "frontier"):
            self.store.commit("rewire")
        self.store.abort("rewire")
        version = self.store.snapshot()["cells"]["parent"]
        (Path(version["directory"]) / "adapter_model.safetensors").write_bytes(
            b"corrupt"
        )
        with self.assertRaisesRegex(ValueError, "tensor"):
            self.store.invoke(
                "parent", self.roots[:1], lambda active: "must not execute"
            )


if __name__ == "__main__":
    unittest.main()
