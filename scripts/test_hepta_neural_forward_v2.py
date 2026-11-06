#!/usr/bin/env python3
"""Caller contract mechanisms; these controls never execute Torch or a model."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


BOOT = module("hepta_neural_forward_bootstrap_v2")
PARENT = module("hepta_neural_study_forward_v2")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": sha(raw)}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        self.chain = self.root / "chain"
        manifest = {
            "profile": BOOT.PROFILE,
            "chain_commit": BOOT.CHAIN_COMMIT,
            "chain_tree": BOOT.CHAIN_TREE,
            "files": {},
        }
        sources = {}
        # Synthetic source bytes test the complete admission mechanism. They
        # are never imported, executed, or called a qualified Chain source.
        for relative in BOOT.RUNTIME_PATHS:
            raw = ("synthetic source: " + relative).encode()
            sources[relative] = pin(self.chain / relative, raw)["sha256"]
            manifest["files"][relative] = {"size": len(raw), "sha256": sha(raw)}
        caller = {}
        for name in BOOT.CALLER_NAMES:
            caller[name] = pin(self.scripts / name, (SCRIPTS / name).read_bytes())[
                "sha256"
            ]
        self.entry = self.scripts / "hepta_neural_forward_v2.py"
        profiles = self.root / "codex-rs/hepta-learning-artifacts/profiles"
        manifest_pin = pin(profiles / BOOT.MANIFEST_NAME, encoded(manifest))
        self.addCleanup(patch.stopall)
        patch.object(
            BOOT, "__file__", str(self.scripts / "hepta_neural_forward_bootstrap_v2.py")
        ).start()
        patch.object(BOOT, "MANIFEST_SHA256", manifest_pin["sha256"]).start()
        complete = {
            str(self.chain / relative): digest for relative, digest in sources.items()
        }
        complete.update(
            {str(self.scripts / name): digest for name, digest in caller.items()}
        )
        plan = (
            ROOT
            / "codex-rs/hepta-infer-worker-host/fixtures/material-runtime-bridge-v1-plan.json"
        ).read_bytes()
        self.config = {
            "schema": BOOT.SCHEMA,
            "source_sha256": caller[self.entry.name],
            "chain": str(self.chain),
            "chain_commit": BOOT.CHAIN_COMMIT,
            "chain_tree": BOOT.CHAIN_TREE,
            "execution_source_profile": BOOT.PROFILE,
            "sources": sources,
            "caller": {"schema": BOOT.CALLER_SCHEMA, "sources": caller},
            "runtime_snapshot": {
                "path": str(self.root / "not-admitted-runtime"),
                "sha256": "1" * 64,
            },
            "source_pins": pin(self.root / "source-pins.json", encoded(complete)),
            "unused_bytecode_prefix": str(self.root / "unused"),
            "materials": str(self.root / "no-model"),
            "parent": {},
            "worker_plan": {},
            "material_plan": pin(self.root / "historical-plan.json", plan),
            "bridge_profile": BOOT.BRIDGE_PROFILE,
            "tasks": {},
            "output": str(self.root / "not-created"),
            "owner_pid": os.getpid(),
            "deadline_monotonic_ns": 1,
            "budget": {"wall_seconds": 600, "rss_bytes": 8 * 1024**3},
            "phase_id": "component",
            "model": "parent",
            "window_id": "not-an-observation",
        }
        self.complete = complete

    def test_complete_fifteen_sources_are_rechecked_after_first_admission(self):
        self.assertEqual(BOOT.project_sources(self.config, self.entry), self.complete)
        changed = self.chain / BOOT.RUNTIME_PATHS[0]
        changed.write_bytes(changed.read_bytes() + b"tamper")
        with self.assertRaises(ValueError):
            BOOT.project_sources(self.config, self.entry)
        self.assertFalse(Path(self.config["output"]).exists())

    def test_each_omitted_source_is_refused_after_request_self_rehash(self):
        for path in self.complete:
            with self.subTest(path=path):
                changed = copy.deepcopy(self.config)
                supplied = {k: v for k, v in self.complete.items() if k != path}
                changed["source_pins"] = pin(
                    self.root / "missing.json", encoded(supplied)
                )
                with self.assertRaises(ValueError):
                    BOOT.project_sources(changed, self.entry)

    def test_manifest_source_and_caller_rosters_are_closed(self):
        for field in ("sources", "caller"):
            changed = copy.deepcopy(self.config)
            if field == "sources":
                changed[field]["scripts/extra.py"] = "1" * 64
            else:
                changed[field]["sources"]["extra.py"] = "1" * 64
            with self.assertRaises(ValueError):
                BOOT.project_sources(changed, self.entry)
        changed = copy.deepcopy(self.config)
        changed["additional"] = None
        with self.assertRaises(ValueError):
            BOOT.project_sources(changed, self.entry)

    def test_current_identity_and_original_budget_are_not_request_authority(self):
        for field, value in (
            ("chain_commit", "0" * 40),
            ("chain_tree", "0" * 40),
            ("execution_source_profile", "legacy"),
            ("budget", {"wall_seconds": 601, "rss_bytes": 8 * 1024**3}),
            ("bridge_profile", "legacy"),
        ):
            changed = copy.deepcopy(self.config)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                BOOT.project_sources(changed, self.entry)

    def test_material_bytes_cannot_be_rebound_to_a_new_self_consistent_pin(self):
        changed = copy.deepcopy(self.config)
        changed["material_plan"] = pin(self.root / "different-plan.json", b"{}")
        with self.assertRaises(ValueError):
            BOOT.project_sources(changed, self.entry)
        Path(self.config["material_plan"]["path"]).write_bytes(b"{}")
        with self.assertRaises(ValueError):
            BOOT.project_sources(self.config, self.entry)

    def test_other_origin_and_symlink_caller_are_refused(self):
        other = self.root / "other" / self.entry.name
        pin(other, self.entry.read_bytes())
        with self.assertRaises(ValueError):
            BOOT.project_sources(self.config, other)
        self.entry.unlink()
        self.entry.symlink_to(other)
        with self.assertRaises((ValueError, OSError)):
            BOOT.project_sources(self.config, self.entry)

    def test_parent_checks_independent_caller_manifest_before_executing_bootstrap(self):
        profiles = self.root / "codex-rs/hepta-learning-artifacts/profiles"
        original = (
            ROOT
            / "codex-rs/hepta-learning-artifacts/profiles"
            / PARENT.CALLER_MANIFEST_NAME
        )
        pin(profiles / PARENT.CALLER_MANIFEST_NAME, original.read_bytes())
        patch.object(
            PARENT, "__file__", str(self.scripts / "hepta_neural_study_forward_v2.py")
        ).start()
        name = "hepta_neural_forward_bootstrap_v2"
        prior = sys.modules.pop(name, None)
        if prior is not None:
            self.addCleanup(lambda: sys.modules.__setitem__(name, prior))
        self.addCleanup(lambda: sys.modules.pop(name, None))
        loaded, pins = PARENT.load_caller()
        self.assertEqual(loaded.CHAIN_COMMIT, BOOT.CHAIN_COMMIT)
        self.assertEqual(pins, self.config["caller"]["sources"])
        sys.modules.pop(name)
        canary = self.root / "must-not-execute"
        path = self.scripts / (name + ".py")
        path.write_text(
            path.read_text()
            + "\nfrom pathlib import Path\nPath("
            + repr(str(canary))
            + ").touch()\n"
        )
        manifest = json.loads(original.read_bytes())
        manifest["files"][name + ".py"] = {
            "size": path.stat().st_size,
            "sha256": sha(path.read_bytes()),
        }
        pin(profiles / PARENT.CALLER_MANIFEST_NAME, encoded(manifest))
        with self.assertRaises(ValueError):
            PARENT.load_caller()
        self.assertFalse(canary.exists())


class ReadyTests(unittest.TestCase):
    def setUp(self):
        self.pins = {
            "/not-executed/" + Path(path).name: sha(path.encode())
            for path in BOOT.RUNTIME_PATHS
        }
        self.pins.update(
            {"/not-executed/" + name: sha(name.encode()) for name in BOOT.CALLER_NAMES}
        )
        self.args = SimpleNamespace(runtime_source_pins=self.pins)
        self.parent = {
            "adapter": "a",
            "file_sha256": "b",
            "contract": "c",
            "generation": 1,
        }
        self.plan = {
            "inherited_sources": {"source": "pin"},
            "worker_source": "worker",
            "runtime_snapshot_sha256": "snapshot",
            "actions": [{"action_id": "yes", "completion": "yes"}],
        }
        self.config = {"runtime_snapshot": {"sha256": "snapshot"}}
        self.ready = {
            "schema": "hepta-smollm-neural-read-ready-material-bridge-v1",
            "actual_loaded_parent": "a",
            "file_sha256": "b",
            "contract": "c",
            "generation": 1,
            "backbone": "component",
            "tokenizer": "component",
            "source_pins": {"source": "pin"},
            "worker_source": "worker",
            "runtime_snapshot_sha256": "snapshot",
            "actions": self.plan["actions"],
            "observed_rss_bytes": 1,
            "authority": {
                "installation_authorized": False,
                "selection_authorized": False,
                "independent_accepted": False,
                "prospective_accepted": False,
                "public_reward_eligible": False,
                "hepta_final_use": False,
            },
            "material_runtime_bridge": copy.deepcopy(BOOT.EXPECTED_BRIDGE),
            "runtime_source_set_sha256": sha(
                encoded({Path(p).name: h for p, h in self.pins.items()})
            ),
        }

    def verify(self, value):
        BOOT.validate_ready(value, self.parent, self.plan, self.args, self.config)

    def test_bridge_ready_is_closed_and_has_no_legacy_fallback(self):
        self.verify(self.ready)
        for key, value in (
            ("schema", "hepta-smollm-neural-read-worker-v2"),
            ("material_runtime_bridge", None),
            ("unknown", None),
        ):
            changed = copy.deepcopy(self.ready)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(changed)

    def test_all_dual_identity_fields_and_full_fifteen_commitment_are_required(self):
        for key in self.ready["material_runtime_bridge"]:
            changed = copy.deepcopy(self.ready)
            changed["material_runtime_bridge"][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(changed)
        changed = copy.deepcopy(self.ready)
        reduced = {
            Path(p).name: h
            for p, h in self.pins.items()
            if Path(p).name not in BOOT.CALLER_NAMES
        }
        changed["runtime_source_set_sha256"] = sha(encoded(reduced))
        with self.assertRaises(ValueError):
            self.verify(changed)

    def test_original_parent_snapshot_actions_and_denied_authority_checks_remain(self):
        for key in (
            "actual_loaded_parent",
            "file_sha256",
            "contract",
            "generation",
            "source_pins",
            "worker_source",
            "runtime_snapshot_sha256",
            "actions",
            "authority",
        ):
            changed = copy.deepcopy(self.ready)
            changed[key] = None
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(changed)

    def test_second_origin_alias_cannot_replace_a_source_in_ready_commitment(self):
        removed = next(iter(self.pins))
        value = self.pins.pop(removed)
        another = next(iter(self.pins))
        self.pins["/alias/" + Path(another).name] = value
        with self.assertRaises(ValueError):
            self.verify(self.ready)

    def test_ready_single_descriptor_bounds_and_special_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "ready.json"
            raw = encoded(self.ready)
            path.write_bytes(raw)
            self.assertEqual(BOOT.read_ready(path), raw)
            path.write_bytes(b"x" * (128 * 1024 + 1))
            with self.assertRaises(ValueError):
                BOOT.read_ready(path)
            path.unlink()
            target = Path(root) / "target"
            target.write_bytes(raw)
            path.symlink_to(target)
            with self.assertRaises(OSError):
                BOOT.read_ready(path)
            path.unlink()
            os.mkfifo(path)
            with self.assertRaises(ValueError):
                BOOT.read_ready(path)


if __name__ == "__main__":
    unittest.main()
