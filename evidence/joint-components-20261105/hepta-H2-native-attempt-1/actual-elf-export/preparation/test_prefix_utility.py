"""Three local byte-fixture controls for H2 partial-range archival only."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("h2_elf_export", ROOT / "export_h2_retained_images.py")
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)
CODE_SHA = hashlib.sha256((ROOT / "export_h2_retained_images.py").read_bytes()).hexdigest()


class PartialRangeControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="prefix-utility-", dir=ROOT)
        self.base = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, name="fixture", unequal=False):
        base = self.base / name
        evidence = base / "evidence"
        evidence.mkdir(parents=True)
        parent_raw = b"\x7fELF" + bytes(range(256)) * 256
        partial_raw = bytearray(parent_raw[:16384])
        if unequal:
            partial_raw[100] ^= 1
        partial_raw = bytes(partial_raw)
        parent, partial = evidence / "first.elf", evidence / "second-incomplete.elf"
        parent.write_bytes(parent_raw)
        partial.write_bytes(partial_raw)
        parent_sha, partial_sha = hashlib.sha256(parent_raw).hexdigest(), hashlib.sha256(partial_raw).hexdigest()
        info = partial.stat()
        version = ":".join(map(str, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)))
        release = base / "release.json"
        release.write_text(json.dumps(dict(job_id="utility-only", owned_processes_clear=True,
                                           failures=[], processes_killed=False)))
        mapping = b'{"utility_only":true,"native_credit":false}\n'
        row = dict(name="H2/elf/" + parent_sha + ".elf", source_path=str(parent), sha256=parent_sha,
                   bytes=len(parent_raw), aliases=[str(parent)], role="complete-live-daemon-image")
        reference = dict(name="H2/partial/" + partial_sha + ".prefix-reference.json", source_path=str(partial),
            aliases=[str(partial)], source_version=version, sha256=partial_sha, bytes=len(partial_raw),
            parent_sha256=parent_sha, offset=0, complete_executable=False,
            completed_process_binding=False, native_evidence_credit=False,
            expected_complete_bytes=len(parent_raw), original_scope="Utility bytes only; no native execution.")
        plan = dict(schema="hepta-actual-retained-elf-export-plan-v1", phase="H2", source_commit="0" * 40,
            source_tree="1" * 40, source_root=str(evidence), files=[row], partial_prefixes=[reference],
            total_elf_bytes=len(parent_raw), total_actual_input_bytes=len(parent_raw) + len(partial_raw),
            max_archive_bytes=len(parent_raw) + 64 * 1024 * 1024, part_bytes=EXPORT.PART_BYTES,
            archive_name="H2-actual-retained-elfs.tar.xz", output_directory=str(base / "output"),
            source_map=dict(bytes=len(mapping), sha256=hashlib.sha256(mapping).hexdigest(),
                            data_base64=base64.b64encode(mapping).decode()),
            release_prerequisite=dict(path=str(release), job_id="utility-only",
                                      sha256=hashlib.sha256(release.read_bytes()).hexdigest()),
            original_run_outcome={"result": "UTILITY_ONLY_NO_NATIVE_RUN"}, native_reexecution=False,
            capture_limits="Utility-only first-image bytes and incomplete prefix; no process binding.")
        path = base / "plan.json"
        path.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")
        return path, plan, parent_raw, partial_raw

    @staticmethod
    def run_export(path):
        with contextlib.redirect_stdout(io.StringIO()):
            return EXPORT.export(path, hashlib.sha256(path.read_bytes()).hexdigest(), CODE_SHA)

    def test_verified_range_reconstructs_partial_without_complete_credit(self):
        path, plan, parent_raw, partial_raw = self.fixture()
        result = self.run_export(path)
        self.assertEqual(result["unique_actual_elfs"], 1)
        self.assertEqual(result["partial_artifacts"], 1)
        self.assertEqual(result["partial_bytes_represented"], len(partial_raw))
        self.assertFalse(result["partial_executable_credit"])
        self.assertFalse(result["native_reexecution"])
        with tarfile.open(result["archive_path"], "r:xz") as archive:
            reference = json.loads(archive.extractfile(plan["partial_prefixes"][0]["name"]).read())
            data = archive.extractfile(reference["reconstruction"]["member"]).read()
            reconstructed = data[reference["reconstruction"]["offset"]:reference["reconstruction"]["bytes"]]
            self.assertEqual(data, parent_raw)
            self.assertEqual(reconstructed, partial_raw)
            self.assertEqual(hashlib.sha256(reconstructed).hexdigest(), reference["sha256"])
            self.assertFalse(reference["complete_executable"])
            self.assertFalse(reference["completed_process_binding"])
            self.assertFalse(reference["native_evidence_credit"])
            self.assertTrue(reference["byte_for_byte_comparison_completed"])
            self.assertEqual(reference["first_read_metadata"], reference["second_read_metadata"])

    def test_different_actual_partial_is_rejected_before_publication(self):
        path, plan, parent_raw, partial_raw = self.fixture(unequal=True)
        with self.assertRaisesRegex(ValueError, "does not equal"):
            self.run_export(path)
        output = Path(plan["output_directory"])
        self.assertFalse((output / "completion.json").exists())
        self.assertFalse((output / plan["archive_name"]).exists())
        self.assertEqual(Path(plan["files"][0]["source_path"]).read_bytes(), parent_raw)
        self.assertEqual(Path(plan["partial_prefixes"][0]["source_path"]).read_bytes(), partial_raw)

    def test_complete_credit_and_stale_partial_version_are_refused(self):
        for mode in ("complete_credit", "stale_version"):
            with self.subTest(mode=mode):
                path, plan, _, _ = self.fixture(name=mode)
                if mode == "complete_credit":
                    plan["partial_prefixes"][0]["completed_process_binding"] = True
                    expected = "cannot claim"
                else:
                    plan["partial_prefixes"][0]["source_version"] += "0"
                    expected = "observed file version"
                path.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")
                with self.assertRaisesRegex(ValueError, expected):
                    self.run_export(path)
                output = Path(plan["output_directory"])
                self.assertFalse((output / "completion.json").exists())
                self.assertFalse((output / plan["archive_name"]).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
