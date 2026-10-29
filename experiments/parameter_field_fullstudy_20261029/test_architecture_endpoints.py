"""Synthetic C seal, barrier, hard-emission and paired-grid engineering tests."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from . import architecture_endpoints as endpoints
from .architecture_state import checkpoint_bytes, digest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


class ArchitectureEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / "stage_C"
        self.plan = endpoints.ArchitecturePlan()
        self.freeze = {"registered_commit": "a" * 40}
        self.binding = {**self.freeze, "source_freeze_sha256": "1" * 64, "protocol_sha256": "2" * 64,
                        "hcsn_reference_commit": endpoints.REFERENCE_COMMIT, "runtime": {"synthetic": True}}

    def population(self):
        warmstarts, paths, artifacts, warmhash = [], [], [], {}
        before = {"counts": {}, "cpu_seconds": 0., "wall_seconds": 0.}
        for kind, seeds in (("development", (701, 702)), ("evaluation", endpoints.SEEDS), ("paths", endpoints.SEEDS)):
            for seed in seeds:
                for mode in endpoints.MODES:
                    for policy in (("baseline", "field") if kind == "paths" else (None,)):
                        config = {"hidden": 32, "noise_scale": .15, "mode": mode, "seed": seed,
                                  "architecture": "fullstudy-hcsn-temporal-v1", "reference_commit": endpoints.REFERENCE_COMMIT}
                        state = {"schema": "hepta.fullstudy.C.training-state.1", "model_config": config,
                                 "model": {"weight": torch.tensor([float(seed)])}, "gradients": {"weight": None},
                                 "parameter_names": ["weight"], "requires_grad": [True]}
                        meta = {"config": config, "seed": seed, "mode": mode, "plan_sha256": digest(self.plan.to_dict()),
                                "binding": self.binding, "parameter_sha256": "3" * 64, "work_before": before,
                                "work_after": {"counts": {"synthetic_steps": 96 if policy else 400}, "cpu_seconds": 1., "wall_seconds": 2.}}
                        if policy:
                            meta.update(schema="hepta.fullstudy.C.endpoint.1", policy=policy, clock=96, schedule=8000,
                                        warmstart_state_sha256=warmhash[(seed, mode)])
                        else:
                            meta.update(schema="hepta.fullstudy.C.warmstart.1", role=kind, warmup_steps=400,
                                        optimizer_state_carried=True, gradient_seen=["weight"], changed_parameters=["weight"])
                            warmhash[(seed, mode)] = digest(state)
                        path = self.stage / f"{kind}/{mode}-{seed}-{policy}.pt.gz"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(checkpoint_bytes(state, meta))
                        artifact = {"path": path.relative_to(self.stage).as_posix(), "bytes": path.stat().st_size,
                                    "sha256": endpoints.file_hash(path)}
                        artifacts.append(artifact)
                        row = {"seed": seed, "mode": mode, "checkpoint": artifact, "state_sha256": digest(state)}
                        row.update({"policy": policy} if policy else {"role": kind})
                        (paths if policy else warmstarts).append(row)
        seal = {"schema": "hepta.fullstudy.C.complete-seal.1", "complete": True, "training_complete": True,
                "new_endpoint_roles_opened": [], "plan": self.plan.to_dict(), "binding": self.binding,
                "warmstarts": warmstarts, "paths": paths, "audit_count": 4, "literal_tensor_checkpoints": 52,
                "physical_gradient_microsteps": 57536, "scientific_gradient_microsteps": 57152,
                "replay_gradient_microsteps": 384, "artifacts": artifacts,
                "work": {"counts": {key + ".scheduled_gradient_microsteps": value for key, value in
                         {"warmup": 8000, "bank": 46080, "evaluation": 3072, "replay_audit": 384}.items()}}}
        write(self.stage / "COMPLETE.json", seal)
        return seal

    def collect(self):
        return endpoints.collect_checkpoints(self.root, self.plan, self.freeze, "1" * 64, "2" * 64, {"synthetic": True})

    def test_all_48_checkpoints_are_required_before_final_access(self):
        seal = self.population()
        inventory = self.collect()
        self.assertEqual(len(inventory["entries"]), 48)
        source = self.root / "SOURCE_ALLOCATION.json"
        write(source, {"synthetic": True})
        with patch.object(endpoints.sources, "load_new_roles", return_value="synthetic corpus") as loader:
            with self.assertRaisesRegex(ValueError, "subset"):
                endpoints.load_endpoint_corpus(self.root, {**inventory, "entries": inventory["entries"][:-1]},
                                                source, self.freeze, "1" * 64)
            loader.assert_not_called()
            corpus, access = endpoints.load_endpoint_corpus(self.root, inventory, source, self.freeze, "1" * 64)
        self.assertEqual(corpus, "synthetic corpus")
        self.assertEqual(loader.call_args.args[2], ["final_task", "final_clean"])
        endpoints.sources._barrier(source, ["final_task", "final_clean"], **access)
        checkpoint = json.loads(Path(access["checkpoint_manifest_path"]).read_text())
        self.assertEqual({row["id"] for row in checkpoint["checkpoints"]}, set(endpoints.expected_ids()))
        seal["paths"].pop()
        write(self.stage / "COMPLETE.json", seal)
        with self.assertRaisesRegex(ValueError, "Incomplete C"):
            self.collect()

    def test_tampered_bytes_duplicate_and_wrong_own_warmstart_are_rejected(self):
        seal = self.population()
        original = json.loads(json.dumps(seal))
        seal["paths"][-1] = seal["paths"][0]
        write(self.stage / "COMPLETE.json", seal)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.collect()
        write(self.stage / "COMPLETE.json", original)
        entry = original["paths"][0]["checkpoint"]
        target = self.stage / entry["path"]
        record = endpoints.read_checkpoint(target)
        record["metadata"]["warmstart_state_sha256"] = "9" * 64
        target.write_bytes(checkpoint_bytes(record["state"], record["metadata"]))
        entry.update(bytes=target.stat().st_size, sha256=endpoints.file_hash(target))
        next(row for row in original["artifacts"] if row["path"] == entry["path"]).update(entry)
        write(self.stage / "COMPLETE.json", original)
        with self.assertRaisesRegex(ValueError, "own warmstart differs"):
            self.collect()
        target.write_bytes(target.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ValueError, "literal evidence bytes"):
            self.collect()

    def test_same_emissions_two_observers_action_zero_and_lossless_96_grid(self):
        batch = SimpleNamespace(source_ids=[("toy:a", "toy:b")], target=SimpleNamespace(pixels=None, labels=None))
        predicted = SimpleNamespace(image_logits=torch.zeros(1, 1, 28, 56), token_ids=[None])
        observed = []

        def observer(name, pixels, captions, targets, labels):
            observed.append((pixels.clone(), list(captions)))
            return [{"utility": -.1 if name == "reward" else -.2}]

        with patch.object(endpoints, "output", return_value=predicted) as forward, \
                patch.object(endpoints, "render_tokens", return_value="synthetic caption"), \
                patch.object(endpoints, "observe_tensors", side_effect=observer):
            score = endpoints.hard_panel(None, [("clean", batch, 17)], {"reward": "reward", "audit": "audit"},
                                         self.plan, endpoints.Work(), lambda: None)
        self.assertEqual(forward.call_args.args[3:5], (("couple",), False))
        self.assertTrue(torch.equal(observed[0][0], observed[1][0]))
        self.assertEqual(observed[0][1], observed[1][1])
        self.assertLess(score["values"]["audit"][0], -.2)
        rows = []
        for identity, (seed, mode, method, schedule) in endpoints.expected_ids().items():
            for role, source_role in endpoints.ROLES.items():
                path = self.root / (identity + "-" + role + ".npz")
                meta = endpoints.save_score(path, score)
                rows.append({"id": identity + "-" + role, "seed": seed, "architecture": mode, "method": method,
                             "schedule_id": schedule, "role": role, "source_role": source_role,
                             "own_warmstart_id": f"{mode}-seed-{seed}-frozen", "path": path.name,
                             "bytes": meta["bytes"], "sha256": meta["file_sha256"], "rows": 1, "costs": {}})
        manifest = self.root / "ENDPOINTS.json"
        payload = {"schema": endpoints.SCHEMA, "complete": True, "phase": "C", "training_path_count": 32,
                   "own_warmstart_count": 16, "observers": ["reward", "audit"], "records": rows}
        write(manifest, payload)
        decoded = endpoints.load_records(manifest, endpoints.file_hash(manifest))
        self.assertEqual(len(decoded), 96)
        np.testing.assert_array_equal(decoded[0]["values"]["audit"], [-.202])
        payload["records"].pop()
        write(manifest, payload)
        with self.assertRaisesRegex(ValueError, "96-record"):
            endpoints.load_records(manifest)


if __name__ == "__main__":
    unittest.main()
