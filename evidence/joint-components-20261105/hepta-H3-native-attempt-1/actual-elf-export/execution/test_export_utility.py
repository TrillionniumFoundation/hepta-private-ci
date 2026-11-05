"""Local byte-fixture controls only; no native/runtime qualification credit."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("retained_elf_export", ROOT / "export_h3_retained_images.py")
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)
CODE_SHA = hashlib.sha256((ROOT / "export_h3_retained_images.py").read_bytes()).hexdigest()


class ExportUtilityControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="elf-export-utility-", dir=ROOT)
        self.base = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, name="fixture", payload=b"small utility-only payload"):
        base = self.base / name
        source_root = base / "evidence"
        source_root.mkdir(parents=True)
        source = source_root / "retained.elf"
        raw = b"\x7fELF" + payload
        source.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        release = base / "release.json"
        release.write_text(json.dumps(dict(job_id="utility-only", owned_processes_clear=True,
                                           failures=[], processes_killed=False)))
        mapping = b'{"utility_fixture":true,"native_credit":false}\n'
        plan = dict(schema="hepta-actual-retained-elf-export-plan-v1", phase="H3",
            source_commit="0" * 40, source_tree="1" * 40, source_root=str(source_root),
            files=[dict(name="H3/elf/" + sha + ".elf", source_path=str(source), sha256=sha,
                        bytes=len(raw), aliases=[str(source), str(source_root / "unread-alias.elf")])],
            total_elf_bytes=len(raw), max_archive_bytes=len(raw) + 64 * 1024 * 1024,
            part_bytes=EXPORT.PART_BYTES, archive_name="H3-actual-retained-elfs.tar.xz",
            output_directory=str(base / "output"),
            source_map=dict(bytes=len(mapping), sha256=hashlib.sha256(mapping).hexdigest(),
                            data_base64=base64.b64encode(mapping).decode()),
            release_prerequisite=dict(path=str(release), job_id="utility-only",
                                      sha256=hashlib.sha256(release.read_bytes()).hexdigest()),
            original_run_outcome={"result": "UTILITY_ONLY_NO_NATIVE_RUN"},
            capture_limits="Synthetic local byte fixture; no process execution or capture.", native_reexecution=False)
        path = base / "plan.json"
        self.write_plan(path, plan)
        return path, plan, source, raw

    @staticmethod
    def write_plan(path, plan):
        path.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")

    @staticmethod
    def run_export(path):
        with contextlib.redirect_stdout(io.StringIO()):
            return EXPORT.export(path, hashlib.sha256(path.read_bytes()).hexdigest(), CODE_SHA)

    def test_roundtrip_two_parts_and_real_fsync_before_completion(self):
        path, plan, source, raw = self.fixture(payload=random.Random(17).randbytes(EXPORT.PART_BYTES + 131072))
        events = []
        real_fsync, real_link = os.fsync, os.link

        def fsync(descriptor):
            events.append(("fsync", os.readlink("/proc/self/fd/" + str(descriptor)),
                           stat.S_ISDIR(os.fstat(descriptor).st_mode)))
            return real_fsync(descriptor)

        def link(src, dst, **kwargs):
            events.append(("link", str(dst), False))
            return real_link(src, dst, **kwargs)

        with mock.patch.object(EXPORT.os, "fsync", side_effect=fsync), mock.patch.object(EXPORT.os, "link", side_effect=link):
            result = self.run_export(path)
        output = Path(plan["output_directory"])
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(len(result["parts"]), 2)
        self.assertFalse(result["native_reexecution"])
        self.assertFalse(result["unselected_aliases_reopened"])
        self.assertEqual(source.read_bytes(), raw)
        archive = Path(result["archive_path"])
        combined = b"".join((output / row["name"]).read_bytes() for row in result["parts"])
        self.assertEqual(combined, archive.read_bytes())
        with tarfile.open(archive, "r:xz") as stream:
            self.assertEqual(stream.extractfile(plan["files"][0]["name"]).read(), raw)
        completion_link = events.index(("link", str(output / "completion.json"), False))
        publication_links = []
        for name in [plan["archive_name"], *[row["name"] for row in result["parts"]]]:
            linked = events.index(("link", str(output / name), False))
            synced = events.index(("fsync", str(output / (name + ".partial")), False))
            self.assertLess(synced, linked)
            publication_links.append(linked)
        completion_fsync = events.index(("fsync", str(output / "completion.json.partial"), False))
        self.assertLess(completion_fsync, completion_link)
        self.assertTrue(any(max(publication_links) < index < completion_link
                            for index, event in enumerate(events) if event == ("fsync", str(output), True)))
        self.assertEqual(events[-1], ("fsync", str(output), True))
        self.assertGreater(len(events) - 1, completion_link)

    def test_wrong_source_hash_never_publishes_final_archive_or_completion(self):
        path, plan, source, raw = self.fixture()
        plan["files"][0]["sha256"] = "f" * 64
        plan["files"][0]["name"] = "H3/elf/" + "f" * 64 + ".elf"
        self.write_plan(path, plan)
        with self.assertRaisesRegex(ValueError, "stable byte/hash"):
            self.run_export(path)
        output = Path(plan["output_directory"])
        self.assertFalse((output / "completion.json").exists())
        self.assertFalse((output / plan["archive_name"]).exists())
        self.assertEqual(source.read_bytes(), raw)

    def test_existing_output_is_never_overwritten(self):
        path, plan, source, raw = self.fixture()
        self.run_export(path)
        output = Path(plan["output_directory"])
        before = {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in output.iterdir()}
        with self.assertRaisesRegex(ValueError, "fresh canonical output"):
            self.run_export(path)
        after = {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in output.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(source.read_bytes(), raw)

    def test_symlink_hardlink_and_fifo_sources_are_refused(self):
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                path, plan, source, raw = self.fixture(name=kind)
                other = source.with_name("actual.elf")
                source.rename(other)
                if kind == "symlink":
                    source.symlink_to(other)
                elif kind == "hardlink":
                    os.link(other, source)
                else:
                    os.mkfifo(source)
                with self.assertRaises((OSError, ValueError)):
                    self.run_export(path)
                output = Path(plan["output_directory"])
                self.assertFalse((output / "completion.json").exists())
                self.assertFalse((output / plan["archive_name"]).exists())
                self.assertEqual(other.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
