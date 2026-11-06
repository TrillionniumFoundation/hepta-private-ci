"""Small synthetic bytes only; these controls award no native/capture credit."""
import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("reference_archive", ROOT / "archive_reference.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
CODE_SHA = M.digest((ROOT / "archive_reference.py").read_bytes())


class ReferenceArchiveByteControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reference-byte-fixture-", dir=ROOT)
        self.base = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self):
        root = self.base
        shared = b"\x7fELF" + b"shared synthetic image\0" * 137
        parent_only = b"\x7fELF" + b"parent only image\0" * 47
        new = b"\x7fELF" + b"new synthetic H4 bytes\0" * 83
        parent_members = {}
        parent_rows = []
        for raw in (shared, parent_only):
            hashed = M.digest(raw)
            name = "H3/elf/" + hashed + ".elf"
            parent_members[name] = raw
            parent_rows.append(dict(name=name, bytes=len(raw), sha256=hashed, role="complete-recorded-test-image"))
        parent_members["source-meta.json"] = b'{"fixture":true,"native_credit":false}\n'
        parent_index = dict(phase="H3", source_commit="3" * 40, source_tree="4" * 40,
            plan_sha256="d" * 64, exporter_sha256="c" * 64, files=parent_rows,
            embedded_metadata_files={"source-meta.json": dict(bytes=len(parent_members["source-meta.json"]),
                sha256=M.digest(parent_members["source-meta.json"]))},
            original_run_outcome=dict(result="UTILITY_ONLY_NATIVE_NOT_RUN"))
        index_raw = M.encoded(parent_index)
        parent_members["export-index.json"] = index_raw
        archive = root / "H3-fixture.tar.xz"
        with tarfile.open(archive, "w:xz", format=tarfile.USTAR_FORMAT, preset=3) as tar:
            for name, raw in parent_members.items():
                M.add_bytes(tar, name, raw)
        archive_raw = archive.read_bytes()
        parts = root / "parent-parts"
        parts.mkdir()
        part_name = archive.name + ".part-0000"
        (parts / part_name).write_bytes(archive_raw)
        completion = dict(status="COMPLETE", phase="H3", archive_path=str(archive),
            archive_bytes=len(archive_raw), archive_sha256=M.digest(archive_raw),
            archive_index_sha256=M.digest(index_raw),
            parts=[dict(index=0, offset=0, name=part_name, bytes=len(archive_raw), sha256=M.digest(archive_raw))])
        completion_path = root / "parent-completion.json"
        completion_raw = M.encoded(completion)
        completion_path.write_bytes(completion_raw)
        pin = dict(phase="H3", archive_bytes=len(archive_raw), archive_sha256=M.digest(archive_raw),
            index_bytes=len(index_raw), index_sha256=M.digest(index_raw), completion_sha256=M.digest(completion_raw),
            plan_sha256="d" * 64, exporter_sha256="c" * 64, source_commit="3" * 40, source_tree="4" * 40,
            images=2, image_bytes=len(shared) + len(parent_only), members=4)
        parent_spec = dict(pin, archive_path=str(archive), completion_path=str(completion_path))
        sources = root / "h4-retained"
        sources.mkdir()
        originals, planned = [], []
        for number, raw in enumerate((shared, new)):
            hashed = M.digest(raw)
            source = sources / (hashed + ".elf")
            source.write_bytes(raw)
            observed = dict(gate="UTILITY_ONLY", method="SYNTHETIC_BYTE_FIXTURE_NOT_CAPTURE", pid=1000 + number,
                start_ticks="1", retained_copy=str(source), source_commit="1" * 40, source_tree="2" * 40,
                selected=["H4-original-fixture-case-" + str(number)], external_binding_gate_passed=False)
            original = dict(sha256=hashed, bytes=len(raw), kind="test-image", retained_aliases=[str(source)],
                actual_paths=["/nonexecuted-fixture/" + str(number)], observations=[observed])
            originals.append(original)
            row = dict(name="H4/elf/" + hashed + ".elf", sha256=hashed, bytes=len(raw),
                source_path=str(source), aliases=original["retained_aliases"],
                original_actual_paths=original["actual_paths"], original_observations=original["observations"],
                representation="referenced-complete-image" if number == 0 else "embedded-complete-image")
            if number == 0:
                row["parent_reference"] = dict(archive_sha256=pin["archive_sha256"], archive_bytes=pin["archive_bytes"],
                    index_sha256=pin["index_sha256"], member="H3/elf/" + hashed + ".elf", bytes=len(raw), sha256=hashed)
            planned.append(row)
        inventory = dict(source_commit="1" * 40, source_tree="2" * 40, status="UTILITY_ONLY_NATIVE_NOT_RUN",
            images=originals, partial_artifacts=[], complete_image_unique_bytes=len(shared) + len(new),
            complete_retained_alias_count=2, unmatched_live_observations=[dict(pid=9999, matching_fd=None)],
            scope="Synthetic byte fixtures only; no actual native process or capture.")
        inventory_raw = M.encoded(inventory)
        release_path = root / "release.json"
        release_raw = M.encoded(dict(job_id="utility-only", owned_processes_clear=True, failures=[], processes_killed=False))
        release_path.write_bytes(release_raw)
        outcome = {key: value for key, value in inventory.items() if key not in ("images", "source_commit", "source_tree")}
        outcome.update(result=inventory["status"], native_job_id="utility-only")
        plan = dict(schema="hepta-H4-reference-archive-plan-v1", phase="H4", native_reexecution=False,
            part_bytes=M.PART_BYTES, transport_budget_seconds=900, source_commit="1" * 40, source_tree="2" * 40,
            source_root=str(sources), files=planned, parent=parent_spec,
            total_actual_elf_bytes=len(shared) + len(new), embedded_elf_bytes=len(new), referenced_elf_bytes=len(shared),
            max_archive_bytes=len(new) + 64 * M.BLOCK, archive_name="H4-actual-retained-image-references.tar.xz",
            output_directory=str(root / "child"), source_map=dict(bytes=len(inventory_raw), sha256=M.digest(inventory_raw),
                data_base64=base64.b64encode(inventory_raw).decode()),
            release_prerequisite=dict(job_id="utility-only", path=str(release_path), sha256=M.digest(release_raw)),
            original_run_outcome=outcome, capture_limits="Synthetic byte utility only; no native/capture credit.")
        path = root / "plan.json"
        path.write_bytes(M.encoded(plan))
        return dict(plan=plan, path=path, pin=pin, parent=archive, parent_completion=completion_path,
                    parent_parts=parts, shared=shared, new=new)

    def run_export(self, fixture):
        fixture["path"].write_bytes(M.encoded(fixture["plan"]))
        with mock.patch.object(M, "PINNED_PARENT", fixture["pin"]), contextlib.redirect_stdout(io.StringIO()):
            return M.export(fixture["path"], M.digest(fixture["path"].read_bytes()), CODE_SHA)

    def run_consumer(self, fixture, result):
        completion = Path(fixture["plan"]["output_directory"]) / "completion.json"
        with mock.patch.object(M, "PINNED_PARENT", fixture["pin"]):
            return M.consume(fixture["parent"], fixture["parent_completion"], fixture["parent_parts"],
                Path(result["archive_path"]), completion, completion.parent, M.digest(completion.read_bytes()), CODE_SHA)

    def assert_no_complete(self, fixture):
        output = Path(fixture["plan"]["output_directory"])
        self.assertFalse((output / "completion.json").exists())
        self.assertFalse((output / fixture["plan"]["archive_name"]).exists())

    def test_complete_reference_and_new_payload_require_both_actual_packages(self):
        f = self.fixture()
        result = self.run_export(f)
        self.assertEqual(result["status"], "COMPLETE_WITH_REFERENCED_PARENT")
        self.assertEqual((result["unique_actual_elfs"], result["unique_embedded_elfs"], result["unique_referenced_elfs"]), (2, 1, 1))
        with tarfile.open(result["archive_path"], "r:xz") as tar:
            names = tar.getnames()
            self.assertNotIn(f["plan"]["files"][0]["name"], names)
            self.assertEqual(tar.extractfile(f["plan"]["files"][1]["name"]).read(), f["new"])
            index = json.loads(tar.extractfile("export-index.json").read())
        self.assertEqual([row["original_observations"] for row in index["files"]],
                         [row["original_observations"] for row in f["plan"]["files"]])
        self.assertTrue(all(row["first_read_metadata"] == row["second_read_metadata"] for row in index["files"]))
        consumed = self.run_consumer(f, result)
        self.assertEqual(consumed["status"], "VERIFIED_COMPLETE_BYTE_CLOSURE")
        self.assertFalse(consumed["native_qualification_awarded"])
        self.assertFalse(consumed["capture_gaps_filled"])
        self.assertEqual(consumed["original_native_outcome"]["unmatched_live_observations"], [dict(pid=9999, matching_fd=None)])
        self.assertEqual([row["sha256"] for row in consumed["complete_logical_views"]],
                         [M.digest(f["shared"]), M.digest(f["new"])])

    def test_changed_or_missing_parent_rejects_before_any_child_publication(self):
        f = self.fixture()
        original = f["parent"].read_bytes()
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    f["parent"].unlink()
                else:
                    f["parent"].write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.run_export(f)
                self.assert_no_complete(f)
                f["parent"].write_bytes(original)

    def test_referenced_h4_source_is_actually_hashed_not_assumed_from_parent(self):
        f = self.fixture()
        source = Path(f["plan"]["files"][0]["source_path"])
        raw = source.read_bytes()
        source.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, "stable byte/hash"):
            self.run_export(f)
        self.assert_no_complete(f)

    def test_reference_source_changes_before_second_actual_read_fail_closed(self):
        f = self.fixture()
        source = Path(f["plan"]["files"][0]["source_path"])
        original = M.actual_hash
        changed = []

        def altered(path, maximum, exact=None, expected_metadata=None):
            if Path(path) == source and expected_metadata is not None:
                raw = source.read_bytes()
                source.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                changed.append(True)
            return original(path, maximum, exact, expected_metadata)

        with mock.patch.object(M, "actual_hash", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "source path/inode changed"):
                self.run_export(f)
        self.assertEqual(changed, [True])
        self.assert_no_complete(f)

    def test_partial_or_transitive_reference_cannot_become_complete(self):
        f = self.fixture()
        good = copy.deepcopy(f["plan"])
        for kind in ("partial-inventory", "partial-member", "second-parent"):
            with self.subTest(kind=kind):
                f["plan"] = copy.deepcopy(good)
                if kind == "partial-inventory":
                    inventory = json.loads(base64.b64decode(f["plan"]["source_map"]["data_base64"]))
                    inventory["partial_artifacts"] = [dict(bytes=8, complete_executable=False)]
                    raw = M.encoded(inventory)
                    f["plan"]["source_map"] = dict(bytes=len(raw), sha256=M.digest(raw), data_base64=base64.b64encode(raw).decode())
                elif kind == "partial-member":
                    f["plan"]["files"][0]["parent_reference"]["member"] = "H3/partial/not-complete"
                else:
                    f["plan"]["parent"]["parents"] = [dict(phase="H2")]
                with self.assertRaises(ValueError):
                    self.run_export(f)
                self.assert_no_complete(f)

    def test_h4_observation_or_alias_substitution_is_rejected(self):
        f = self.fixture()
        f["plan"]["files"][0]["original_observations"] = [dict(case="borrowed H3 capture")]
        with self.assertRaisesRegex(ValueError, "H4 actual observation/alias binding differs"):
            self.run_export(f)
        self.assert_no_complete(f)

    def test_consumer_refuses_missing_changed_parent_and_incomplete_parts(self):
        f = self.fixture()
        result = self.run_export(f)
        parent_raw = f["parent"].read_bytes()
        part = next(f["parent_parts"].iterdir())
        part_raw = part.read_bytes()
        child_part = Path(f["plan"]["output_directory"]) / result["parts"][0]["name"]
        child_raw = child_part.read_bytes()
        for kind in ("missing-parent", "changed-parent", "missing-parent-part", "changed-parent-part", "missing-child-part"):
            with self.subTest(kind=kind):
                if kind == "missing-parent": f["parent"].unlink()
                elif kind == "changed-parent": f["parent"].write_bytes(parent_raw[:-1] + bytes([parent_raw[-1] ^ 1]))
                elif kind == "missing-parent-part": part.unlink()
                elif kind == "changed-parent-part": part.write_bytes(part_raw[:-1] + bytes([part_raw[-1] ^ 1]))
                else: child_part.unlink()
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.run_consumer(f, result)
                f["parent"].write_bytes(parent_raw)
                part.write_bytes(part_raw)
                child_part.write_bytes(child_raw)

    def test_existing_child_output_is_not_overwritten(self):
        f = self.fixture()
        self.run_export(f)
        output = Path(f["plan"]["output_directory"])
        before = {p.name: M.digest(p.read_bytes()) for p in output.iterdir()}
        with self.assertRaisesRegex(ValueError, "fresh canonical output"):
            self.run_export(f)
        self.assertEqual(before, {p.name: M.digest(p.read_bytes()) for p in output.iterdir()})


if __name__ == "__main__":
    unittest.main(verbosity=2)
