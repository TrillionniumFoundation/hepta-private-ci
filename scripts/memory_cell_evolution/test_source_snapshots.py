"""Pure file-snapshot controls; these do not load a model or activate an owner."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import edge_policy
from evolution_common import canonical, digest, file_digest
import longitudinal_runtime
import topology_owner


class OwnerBoundaryReached(RuntimeError):
    """Stop immediately before the real parameter-owner constructor."""


@contextmanager
def replace_after_first_read(watched, replacement):
    """Replace the path after a real read closes, leaving its descriptor intact."""
    real_open = Path.open
    events = []

    @contextmanager
    def opened(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        selected = Path(path) == watched and mode == "rb"
        with real_open(path, *args, **kwargs) as stream:
            yield stream
        if selected and not events:
            os.replace(replacement, watched)
            events.append("replaced-after-read")

    with patch.object(Path, "open", opened):
        yield events


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source_root = "a" * 64
        self.parent_pin = "b" * 64

    def candidate(self, derivation, *, valid=True):
        source = self.root / ("candidate-" + derivation)
        source.mkdir()
        training = dict(
            initialization="frozen_base",
            inherited_roots=[],
            learned_parent_manifest_sha256=None,
            source_digests=[self.source_root],
        )
        parents = []
        if derivation == "inherit":
            parents = [dict(roots=[self.source_root], manifest_sha256=self.parent_pin)]
            training["learned_parent_manifest_sha256"] = (
                self.parent_pin if valid else "c" * 64
            )
        elif not valid:
            training["initialization"] = "unmeasured"
        lineage = dict(roots=[self.source_root], training=training)
        (source / "lineage.json").write_bytes(canonical(lineage))
        # The control stops at the owner constructor; these bytes are not weights.
        (source / "adapter_model.safetensors").write_bytes(b"owner-boundary-only")
        (source / "adapter_config.json").write_bytes(b"{}")
        candidate = dict(
            directory=str(source),
            manifest_sha256=file_digest(source / "lineage.json"),
            support_roots=[self.source_root],
            parents=parents,
            derivation=derivation,
            previous=None,
            cell_id="cell",
            role="semantic",
            version=0,
        )
        frontier = dict(scope="fixture", epoch=0, roots=[self.source_root], revoked=[])
        return candidate, frontier, lineage

    def boundary_owner(self):
        calls = []

        def stop(database):
            calls.append(str(database))
            raise OwnerBoundaryReached("real owner was not constructed")

        owners = object.__new__(topology_owner.ActualOwners)
        owners.Owner = stop
        return owners, calls

    def assert_stage_replacement_rejected(self, derivation):
        candidate, frontier, invalid = self.candidate(derivation, valid=False)
        watched = Path(candidate["directory"]) / "lineage.json"
        valid = json.loads(canonical(invalid))
        if derivation == "inherit":
            valid["training"]["learned_parent_manifest_sha256"] = self.parent_pin
        else:
            valid["training"]["initialization"] = "frozen_base"
        replacement = self.root / "replacement.json"
        replacement.write_bytes(canonical(valid))
        owners, calls = self.boundary_owner()
        error = None
        with replace_after_first_read(watched, replacement) as events:
            try:
                owners.stage(candidate, frontier, self.root / "staged")
            except (ValueError, OwnerBoundaryReached) as exc:
                error = exc
        self.assertEqual(events, ["replaced-after-read"])
        self.assertEqual(watched.read_bytes(), canonical(valid))
        self.assertIsInstance(
            error, ValueError, f"metadata reached owner boundary: {calls!r}"
        )
        self.assertEqual(str(error), "candidate manifest digest")
        self.assertEqual(calls, [])

    def test_clean_replay_replacement_is_rejected_before_owner(self):
        self.assert_stage_replacement_rejected("clean_replay")

    def test_inherit_replacement_is_rejected_before_owner(self):
        self.assert_stage_replacement_rejected("inherit")

    def test_unchanged_metadata_reaches_original_owner_boundary(self):
        for derivation in ("clean_replay", "inherit"):
            with self.subTest(derivation=derivation):
                candidate, frontier, _ = self.candidate(derivation)
                owners, calls = self.boundary_owner()
                with self.assertRaisesRegex(
                    OwnerBoundaryReached, "real owner was not constructed"
                ):
                    owners.stage(
                        candidate, frontier, self.root / ("staged-" + derivation)
                    )
                self.assertEqual(len(calls), 1)

    def test_wrong_pin_preserves_streaming_rejection_before_capture(self):
        candidate, frontier, _ = self.candidate("clean_replay")
        candidate["manifest_sha256"] = "d" * 64
        owners, calls = self.boundary_owner()
        # Existing streaming hashing must reject before read_bytes allocates.
        with patch.object(Path, "read_bytes", side_effect=AssertionError("late read")):
            with self.assertRaisesRegex(ValueError, "candidate manifest digest"):
                owners.stage(candidate, frontier, self.root / "staged")
        self.assertEqual(calls, [])

    def policy_files(self):
        directory = self.root / "policy"
        directory.mkdir()
        router = b"router-loader-boundary-only-A"
        (directory / "router.bin").write_bytes(router)
        value = dict(
            targets=["next"],
            final_outputs_used=False,
            source_sha256="e" * 64,
            router_sha256=hashlib.sha256(router).hexdigest(),
            ancestry_roots=[self.source_root],
        )
        (directory / "policy.json").write_bytes(canonical(value))
        return directory, value

    @contextmanager
    def router_boundary(self, value, *, after_load=None, expert_ids=("next",)):
        calls = []
        module = types.ModuleType("learned_router")

        def load_router(path, *, expected_sha256):
            calls.append(dict(path=str(path), expected_sha256=expected_sha256))
            if after_load is not None:
                after_load()
            return types.SimpleNamespace(
                expert_ids=expert_ids, source_sha256=value["source_sha256"]
            )

        module.load_router = load_router
        with patch.dict(sys.modules, {"learned_router": module}):
            with patch.object(sys, "path", list(sys.path)):
                yield calls

    def make_policy(self, directory):
        return edge_policy.EdgePolicy(
            "learned-next-cell",
            ["next"],
            learned_directory=directory,
            scripts=self.root,
        )

    def test_constructor_binds_bytes_used_for_router_metadata(self):
        directory, value = self.policy_files()
        original = canonical(value)
        changed = value | dict(ancestry_roots=["f" * 64], source_sha256="f" * 64)
        replacement = self.root / "policy-replacement.json"
        replacement.write_bytes(canonical(changed))

        def replace_during_load():
            os.replace(replacement, directory / "policy.json")

        with self.router_boundary(value, after_load=replace_during_load) as calls:
            policy = self.make_policy(directory)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["expected_sha256"], value["router_sha256"])
        self.assertEqual((directory / "policy.json").read_bytes(), canonical(changed))
        self.assertEqual(policy.binding["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(policy.binding["ancestry_roots"], [self.source_root])
        with self.assertRaisesRegex(ValueError, "edge policy changed after freeze"):
            policy.check()

    def test_check_rejects_policy_replaced_between_hash_and_parse(self):
        directory, value = self.policy_files()
        with self.router_boundary(value):
            policy = self.make_policy(directory)
        changed_router = b"router-loader-boundary-only-B"
        (directory / "router.bin").write_bytes(changed_router)
        changed = value | dict(router_sha256=hashlib.sha256(changed_router).hexdigest())
        replacement = self.root / "policy-replacement.json"
        replacement.write_bytes(canonical(changed))
        error = None
        with replace_after_first_read(directory / "policy.json", replacement) as events:
            try:
                policy.check()
            except ValueError as exc:
                error = exc
        self.assertEqual(events, ["replaced-after-read"])
        self.assertEqual((directory / "policy.json").read_bytes(), canonical(changed))
        self.assertIsInstance(error, ValueError)
        self.assertEqual(str(error), "edge policy changed after freeze")

    def test_unchanged_policy_and_router_keep_their_binding(self):
        directory, value = self.policy_files()
        with self.router_boundary(value) as calls:
            policy = self.make_policy(directory)
        policy.check()
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            policy.binding["sha256"], file_digest(directory / "policy.json")
        )
        self.assertEqual(policy.binding["ancestry_roots"], [self.source_root])

    def test_weight_change_keeps_existing_rejection(self):
        directory, value = self.policy_files()
        with self.router_boundary(value):
            policy = self.make_policy(directory)
        (directory / "router.bin").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "edge weights changed after freeze"):
            policy.check()

    def test_original_constructor_metadata_guards_remain(self):
        directory, value = self.policy_files()
        for change in (dict(targets=["other"]), dict(final_outputs_used=True)):
            with self.subTest(change=change):
                (directory / "policy.json").write_bytes(canonical(value | change))
                with self.router_boundary(value) as calls:
                    with self.assertRaisesRegex(ValueError, "frozen next-cell policy"):
                        self.make_policy(directory)
                self.assertEqual(calls, [])
        (directory / "policy.json").write_bytes(canonical(value))
        for expert_ids, source in (
            (("other",), value["source_sha256"]),
            (("next",), "f" * 64),
        ):
            with self.subTest(expert_ids=expert_ids, source=source):
                with self.router_boundary(
                    value | dict(source_sha256=source), expert_ids=expert_ids
                ) as calls:
                    with self.assertRaisesRegex(
                        ValueError, "router/state-source binding"
                    ):
                        self.make_policy(directory)
                self.assertEqual(len(calls), 1)


class SourceCaptureTests(unittest.TestCase):
    """Test only captured source copies, with no model or subprocess invocation."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.driver = self.root / "driver"
        self.model = self.root / "model-inventory"
        self.output = self.root / "output"
        for directory in (self.repo, self.driver, self.model, self.output):
            directory.mkdir()
        self.baseline_name = "scripts/memory_cell_fixture/source.py"
        self.driver_name = "driver_fixture.py"
        self.baseline_source = self.repo / self.baseline_name
        self.baseline_source.parent.mkdir(parents=True)
        self.baseline_source.write_bytes(b"baseline original bytes\n")
        (self.driver / self.driver_name).write_bytes(b"driver original bytes\n")
        for name in longitudinal_runtime.BASE_FILES:
            (self.model / name).write_bytes(name.encode())
        inventory = {
            name: dict(
                bytes=(self.model / name).stat().st_size,
                sha256=file_digest(self.model / name),
            )
            for name in longitudinal_runtime.BASE_FILES
        }
        self.inventory_pin = digest(inventory)

    def pin(self, replace_group=None):
        captured = {}

        def source_boundary(repo):
            self.assertEqual(repo, self.repo)
            source = dict(
                baseline="metadata-only-fixture",
                repository_files={
                    self.baseline_name: file_digest(self.baseline_source)
                },
                local_files={
                    self.driver_name: file_digest(self.driver / self.driver_name)
                },
            )
            captured.update(source)
            if replace_group is not None:
                target = (
                    self.baseline_source
                    if replace_group == "baseline"
                    else self.driver / self.driver_name
                )
                replacement = self.root / "replacement-source.py"
                replacement.write_bytes(b"changed after source pin\n")
                os.replace(replacement, target)
            return source

        with (
            patch.object(longitudinal_runtime, "source_identity", source_boundary),
            patch.object(
                longitudinal_runtime, "__file__", str(self.driver / "runtime.py")
            ),
            patch.object(longitudinal_runtime, "BASE_IDENTITY", self.inventory_pin),
            patch.object(
                longitudinal_runtime.importlib.metadata,
                "distributions",
                return_value=[],
            ),
        ):
            result = longitudinal_runtime.pin_start(
                self.repo, self.model, self.output, {"fixture": True}, "1" * 64
            )
        return result, captured

    def test_driver_copy_change_rejected_before_start_receipt(self):
        with self.assertRaisesRegex(ValueError, "source capture race"):
            self.pin("driver")
        self.assertFalse((self.output / "start.json").exists())
        target = self.output / "source-snapshot" / "driver" / self.driver_name
        self.assertEqual(target.read_bytes(), b"changed after source pin\n")

    def test_baseline_copy_change_rejected_before_start_receipt(self):
        with self.assertRaisesRegex(ValueError, "source capture race"):
            self.pin("baseline")
        self.assertFalse((self.output / "start.json").exists())
        target = self.output / "source-snapshot" / "baseline" / self.baseline_name
        self.assertEqual(target.read_bytes(), b"changed after source pin\n")

    def test_matching_copies_keep_original_start_record(self):
        result, captured = self.pin()
        self.assertEqual(result, captured)
        start = json.loads((self.output / "start.json").read_bytes())
        self.assertEqual(start["source_identity_sha256"], digest(captured))
        self.assertFalse(start["model_invocation_started"])
        for group, entries in (
            ("driver", captured["local_files"]),
            ("baseline", captured["repository_files"]),
        ):
            for name, expected in entries.items():
                self.assertEqual(
                    file_digest(self.output / "source-snapshot" / group / name),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
