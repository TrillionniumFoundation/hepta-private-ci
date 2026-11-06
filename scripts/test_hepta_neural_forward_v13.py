"""V13 fixed-path and Ready controls; synthetic inputs never run a model."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DIRECTORY = "scripts/hepta_neural_forward_v13"
PROFILES = ROOT / "codex-rs/hepta-learning-artifacts/profiles"


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


BOOT = module(
    ROOT / DIRECTORY / "hepta_neural_forward_bootstrap_v2.py", "v13_fixture_bootstrap"
)
PARENT = module(SCRIPTS / "hepta_neural_study_forward_v3.py", "v13_fixture_parent")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return dict(path=str(path), sha256=sha(raw))


class ProjectionFixture:
    def __init__(self, owner):
        temporary = tempfile.TemporaryDirectory()
        owner.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.scripts = self.root / "scripts"
        self.callers = self.root / DIRECTORY
        self.chain = self.root / "chain"
        self.callers.mkdir(parents=True)
        manifest = dict(
            profile=BOOT.PROFILE,
            chain_commit=BOOT.CHAIN_COMMIT,
            chain_tree=BOOT.CHAIN_TREE,
            files={},
        )
        sources = {}
        for relative in BOOT.RUNTIME_PATHS:
            raw = ("synthetic source never imported: " + relative).encode()
            sources[relative] = pin(self.chain / relative, raw)["sha256"]
            manifest["files"][relative] = dict(size=len(raw), sha256=sha(raw))
        caller = {}
        for name in BOOT.CALLER_NAMES:
            caller[name] = pin(
                self.callers / name, (ROOT / DIRECTORY / name).read_bytes()
            )["sha256"]
        self.entry = self.callers / BOOT.CALLER_NAMES[1]
        profiles = self.root / "codex-rs/hepta-learning-artifacts/profiles"
        manifest_pin = pin(profiles / BOOT.MANIFEST_NAME, encoded(manifest))
        owner.enterContext(
            patch.object(BOOT, "__file__", str(self.callers / BOOT.CALLER_NAMES[0]))
        )
        owner.enterContext(
            patch.object(BOOT, "MANIFEST_SHA256", manifest_pin["sha256"])
        )
        owner.enterContext(
            patch.object(
                PARENT,
                "__file__",
                str(self.scripts / "hepta_neural_study_forward_v3.py"),
            )
        )
        pin(
            profiles / PARENT.CALLER_MANIFEST_NAME,
            (PROFILES / PARENT.CALLER_MANIFEST_NAME).read_bytes(),
        )
        self.complete = {
            str(self.chain / relative): digest for relative, digest in sources.items()
        }
        self.complete.update(
            {str(self.callers / name): digest for name, digest in caller.items()}
        )
        plan = (
            ROOT
            / "codex-rs/hepta-infer-worker-host/fixtures/material-runtime-bridge-v1-plan.json"
        ).read_bytes()
        self.config = dict(
            schema=BOOT.SCHEMA,
            source_sha256=caller[self.entry.name],
            chain=str(self.chain),
            chain_commit=BOOT.CHAIN_COMMIT,
            chain_tree=BOOT.CHAIN_TREE,
            execution_source_profile=BOOT.PROFILE,
            sources=sources,
            caller=dict(schema=BOOT.CALLER_SCHEMA, directory=DIRECTORY, sources=caller),
            runtime_snapshot=dict(
                path=str(self.root / "not-admitted-snapshot"), sha256="1" * 64
            ),
            source_pins=pin(self.root / "source-pins.json", encoded(self.complete)),
            unused_bytecode_prefix=str(self.root / "unused"),
            materials=str(self.root / "no-model"),
            parent={},
            worker_plan={},
            material_plan=pin(self.root / "material-plan.json", plan),
            bridge_profile=BOOT.BRIDGE_PROFILE,
            tasks={},
            output=str(self.root / "not-created"),
            owner_pid=os.getpid(),
            deadline_monotonic_ns=1,
            budget=dict(wall_seconds=600, rss_bytes=8 * 1024**3),
            phase_id="component",
            model="parent",
            window_id="not-an-observation",
        )


class ProjectionControls(unittest.TestCase):
    def setUp(self):
        self.fixture = ProjectionFixture(self)

    def verify(self, config=None, entry=None):
        return BOOT.project_sources(
            config or self.fixture.config, entry or self.fixture.entry
        )

    def test_fixed_nested_source_set_rechecks_every_byte(self):
        self.assertEqual(self.verify(), self.fixture.complete)
        self.assertEqual(len(self.fixture.complete), 15)
        path = self.fixture.chain / BOOT.RUNTIME_PATHS[0]
        path.write_bytes(path.read_bytes() + b"tamper")
        with self.assertRaises(ValueError):
            self.verify()
        self.assertFalse(Path(self.fixture.config["output"]).exists())

    def test_each_missing_source_or_extra_caller_is_refused(self):
        for path in self.fixture.complete:
            value = copy.deepcopy(self.fixture.config)
            value["source_pins"] = pin(
                self.fixture.root / "reduced.json",
                encoded({p: h for p, h in self.fixture.complete.items() if p != path}),
            )
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify(value)
        value = copy.deepcopy(self.fixture.config)
        value["caller"]["sources"]["other.py"] = "1" * 64
        with self.assertRaises(ValueError):
            self.verify(value)

    def test_profile_commit_tree_schema_and_directory_are_one_closed_tuple(self):
        for field, replacement in (
            ("execution_source_profile", "hepta-integrated-chain-execution-v12"),
            ("chain_commit", "cad4c18fe146b7d742ac7fa8872044cd4136c22b"),
            ("chain_tree", "1e753c4641f6108f50b356182f8b4e81fa941e31"),
            ("schema", "hepta-neural-positive-forward-v2"),
            ("budget", dict(wall_seconds=601, rss_bytes=8 * 1024**3)),
        ):
            value = copy.deepcopy(self.fixture.config)
            value[field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(value)
        for replacement in ("scripts", "other/hepta_neural_forward_v13", None):
            value = copy.deepcopy(self.fixture.config)
            value["caller"]["directory"] = replacement
            with self.subTest(directory=replacement), self.assertRaises(ValueError):
                self.verify(value)

    def test_same_basename_in_other_directory_and_symlink_refuse(self):
        other = self.fixture.root / "other" / self.fixture.entry.name
        pin(other, self.fixture.entry.read_bytes())
        with self.assertRaises(ValueError):
            self.verify(entry=other)
        with patch.object(BOOT, "__file__", str(other.with_name(BOOT.CALLER_NAMES[0]))):
            with self.assertRaisesRegex(ValueError, "exact V13 caller directory"):
                BOOT.repository_root()
        self.fixture.entry.unlink()
        self.fixture.entry.symlink_to(other)
        with self.assertRaises((ValueError, OSError)):
            self.verify()

    def test_mixed_v12_callers_and_self_rehashed_manifest_never_execute(self):
        for name in BOOT.CALLER_NAMES:
            target = self.fixture.callers / name
            original = target.read_bytes()
            target.write_bytes((SCRIPTS / name).read_bytes())
            try:
                with (
                    self.subTest(name=name),
                    self.assertRaisesRegex(ValueError, "pinned source"),
                ):
                    PARENT.load_caller()
            finally:
                target.write_bytes(original)
        profiles = self.fixture.root / "codex-rs/hepta-learning-artifacts/profiles"
        manifest_path = profiles / PARENT.CALLER_MANIFEST_NAME
        value = json.loads(manifest_path.read_bytes())
        canary = self.fixture.root / "must-not-execute"
        target = self.fixture.callers / BOOT.CALLER_NAMES[0]
        target.write_bytes(
            target.read_bytes()
            + (
                "\nfrom pathlib import Path\nPath(" + repr(str(canary)) + ").touch()\n"
            ).encode()
        )
        value["files"][target.name] = dict(
            size=target.stat().st_size, sha256=sha(target.read_bytes())
        )
        manifest_path.write_bytes(encoded(value))
        with self.assertRaisesRegex(ValueError, "pinned source"):
            PARENT.load_caller()
        self.assertFalse(canary.exists())

    def test_cwd_sys_path_and_preloaded_names_do_not_select_the_callers(self):
        shadow = self.fixture.root / "shadow"
        shadow.mkdir()
        canary = shadow / "executed"
        for name in (*BOOT.CALLER_NAMES, "hepta_neural_study_forward_v3.py"):
            (shadow / name).write_text(
                "from pathlib import Path\nPath(" + repr(str(canary)) + ").touch()\n"
            )
        fake = ModuleType("hepta_neural_forward_bootstrap_v13")
        fake.PROFILE = "shadow"
        previous = Path.cwd()
        try:
            os.chdir(shadow)
            with (
                patch.object(sys, "path", [str(shadow), *sys.path]),
                patch.dict(sys.modules, {fake.__name__: fake}),
            ):
                loaded, pins = PARENT.load_caller()
        finally:
            os.chdir(previous)
        self.assertEqual(loaded.PROFILE, BOOT.PROFILE)
        self.assertEqual(pins, self.fixture.config["caller"]["sources"])
        self.assertEqual(Path(loaded.__file__).parent, self.fixture.callers)
        self.assertFalse(canary.exists())

    def test_parent_module_and_observer_shadow_refuse_before_execution(self):
        canary = self.fixture.root / "not-imported"
        path = self.fixture.root / "module.py"
        pin(
            path,
            (
                "from pathlib import Path\nPath(" + repr(str(canary)) + ").touch()\n"
            ).encode(),
        )
        fake = ModuleType("hepta_ci_exec")
        with patch.dict(sys.modules, {"hepta_ci_exec": fake}):
            with self.assertRaisesRegex(ValueError, "preloaded source module"):
                PARENT.load_exact_module("hepta_ci_exec", path, sha(path.read_bytes()))
        with self.assertRaisesRegex(ValueError, "pinned source"):
            PARENT.load_exact_module("never_loaded_v13_control", path, "0" * 64)
        with patch.dict(sys.modules, {"llm_runtime_exit_worker_observation": fake}):
            with self.assertRaisesRegex(ValueError, "preloaded historical observer"):
                PARENT.load_observer(self.fixture.chain)
        self.assertFalse(canary.exists())


class ReadyControls(unittest.TestCase):
    def setUp(self):
        import test_hepta_neural_forward_v2 as original

        self.fixture = original.ReadyTests()
        self.fixture.setUp()
        self.ready = copy.deepcopy(self.fixture.ready)
        self.pins = dict(self.fixture.pins)
        for name in BOOT.CALLER_NAMES:
            self.pins["/not-executed/" + name] = sha(
                (ROOT / DIRECTORY / name).read_bytes()
            )
        self.args = SimpleNamespace(runtime_source_pins=self.pins)
        self.ready["runtime_source_set_sha256"] = sha(
            encoded({Path(p).name: h for p, h in self.pins.items()})
        )

    def verify(self, ready):
        BOOT.validate_ready(
            ready,
            self.fixture.parent,
            self.fixture.plan,
            self.args,
            self.fixture.config,
        )

    def test_each_ready_field_is_required_and_unknown_fields_refuse(self):
        self.verify(self.ready)
        for field in self.ready:
            value = copy.deepcopy(self.ready)
            del value[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(value)
        with self.assertRaises(ValueError):
            self.verify(dict(self.ready, unknown=None))

    def test_v12_caller_commitment_and_material_identity_cannot_be_mixed(self):
        value = copy.deepcopy(self.ready)
        old_pins = {Path(p).name: h for p, h in self.pins.items()}
        for name in BOOT.CALLER_NAMES:
            old_pins[name] = sha((SCRIPTS / name).read_bytes())
        value["runtime_source_set_sha256"] = sha(encoded(old_pins))
        with self.assertRaises(ValueError):
            self.verify(value)
        for field in self.ready["material_runtime_bridge"]:
            value = copy.deepcopy(self.ready)
            value["material_runtime_bridge"][field] = "wrong"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(value)


if __name__ == "__main__":
    unittest.main()
