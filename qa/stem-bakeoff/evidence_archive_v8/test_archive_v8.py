"""Small temporary-file qualification; no actual research roots are inspected."""

import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from archive_pack_v8 import capacity, measure, pack
from archive_plan_v8 import ArchiveError, canonical, digest, make_plan, relative_name, validate_plan
from archive_verify_v8 import verify_archive


def deterministic_gzip(value):
    out = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=out, mode="wb", compresslevel=6, mtime=0) as stream:
        stream.write(value)
    return out.getvalue()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-archive-v8-", dir=Path(__file__).parent)
        self.base = Path(self.temp.name)
        self.root = self.base / "evidence"
        self.root.mkdir()
        self.payload = b"unique complete evidence marker\x00" * 200
        (self.root / "a.bin").write_bytes(self.payload)
        (self.root / "duplicate.bin").write_bytes(self.payload)
        (self.root / "empty.bin").write_bytes(b"")
        (self.root / "interrupted.partial").write_bytes(b"honest partial output")
        (self.root / "seal.json").write_bytes(canonical({"status": "sealed fixture"}))
        sub = self.root / ("unicode-\u8bc1\u636e-" + "x" * 90)
        sub.mkdir()
        (sub / "record.json").write_bytes(canonical({"record": "complete"}))
        source = self.root / "published.py"
        source.write_bytes(b"print('published source fixture')\n")
        (self.root / "research-private-key.pem").write_bytes(b"never archive this sentinel")
        (self.root / "model.safetensors").write_bytes(b"rebuildable encoder fixture")
        cache = self.root / "temporary" / ".git"
        cache.mkdir(parents=True)
        (cache / "objects").write_bytes(b"not archive content")
        self.config = {"schema": "hepta.evidence-archive-roots.v8", "workspace": str(self.base),
            "roots": [{"label": "evidence", "path": str(self.root), "status": "sealed",
                       "purpose": "small synthetic preservation qualification",
                       "pins": {name: digest((self.root / name).read_bytes()) for name in (
                           "a.bin", "duplicate.bin", "empty.bin", "interrupted.partial", "seal.json",
                           sub.relative_to(self.root).as_posix() + "/record.json")},
                       "source_references": {"published.py": {
                           "repository": "https://github.com/TrillionniumFoundation/hepta-private-ci",
                           "commit": "a" * 40, "path": "qualification/published.py", "sha256": digest(source.read_bytes())}}}],
            "prerequisite_archives": [{"name": "earlier fixture archive", "bytes": 1, "sha256": "b" * 64,
                                       "location": "external prerequisite; synthetic fixture only"}]}
        self.roots_file = self.base / "roots.json"
        self.plan_file = self.base / "approved-plan.json"

    def tearDown(self):
        self.temp.cleanup()

    def plan(self):
        raw = canonical(self.config)
        self.roots_file.write_bytes(raw)
        result = make_plan(self.roots_file, digest(raw), self.plan_file)
        self.plan_sha = result["plan_sha256"]
        return json.loads(self.plan_file.read_bytes())

    def build(self, name="complete.tar.gz"):
        output = self.base / name
        receipt = pack(self.plan_file, self.plan_sha, output, 2 << 20, reserve=0)
        return output, receipt

    def test_full_determinism_hardlinks_long_paths_and_independent_verification_without_sources(self):
        plan = self.plan()
        estimate = measure(self.plan_file, self.plan_sha)
        first, receipt = self.build()
        second, _ = self.build("second.tar.gz")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(digest(first.read_bytes()), estimate["predicted_archive_sha256"])
        self.assertEqual(first.stat().st_size, estimate["compressed_bytes"])
        self.assertEqual(first.read_bytes()[4:8], b"\0" * 4)
        self.assertEqual(plan["hardlinks"], 1)
        self.assertEqual(len(plan["excluded"]), 4)
        with tarfile.open(first, "r:gz") as archive:
            members = archive.getmembers()
            self.assertEqual(members[0].name, "MANIFEST.json")
            duplicate = archive.getmember("evidence/duplicate.bin")
            self.assertTrue(duplicate.islnk())
            self.assertEqual(duplicate.linkname, "evidence/a.bin")
            self.assertEqual(archive.extractfile(duplicate).read(), self.payload)
            self.assertIn("evidence/interrupted.partial", archive.getnames())
            self.assertNotIn("evidence/published.py", archive.getnames())
        shutil.rmtree(self.root)
        check = verify_archive(first, self.plan_file, self.plan_sha, receipt["verification"]["archive_sha256"])
        self.assertEqual(check["members"], len(plan["members"]))
        self.assertEqual(check["archive_logical_members"], len(members))
        self.assertEqual(check["regular_evidence_members"] + check["hardlinks"], check["evidence_members"])
        self.assertFalse(check["source_directories_required"])

    def test_tail_body_mutation_truncation_and_extra_gzip_are_rejected(self):
        self.plan()
        original, _ = self.build()
        raw = original.read_bytes()
        body = gzip.decompress(raw)
        changed = body.replace(self.payload, b"X" + self.payload[1:], 1)
        self.assertNotEqual(changed, body)
        variations = {"content": deterministic_gzip(changed), "truncated": raw[:-7],
                      "extra-member": raw + deterministic_gzip(b""), "extra-tar": deterministic_gzip(body + b"x")}
        for name, data in variations.items():
            with self.subTest(name=name):
                path = self.base / (name + ".tar.gz")
                path.write_bytes(data)
                with self.assertRaises((ArchiveError, ValueError, EOFError)):
                    verify_archive(path, self.plan_file, self.plan_sha)

    def test_mutated_input_and_new_unapproved_file_reject_before_final_publication(self):
        self.plan()
        path = self.root / "a.bin"
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ArchiveError, "inventory changed"):
            self.build()
        self.assertFalse((self.base / "complete.tar.gz").exists())
        (self.root / "new.json").write_bytes(b"unapproved")
        with self.assertRaises(ArchiveError):
            measure(self.plan_file, self.plan_sha)

    def test_budget_failure_retains_partial_and_no_final_archive(self):
        self.plan()
        output = self.base / "limited.tar.gz"
        with self.assertRaisesRegex(ArchiveError, "output budget"):
            pack(self.plan_file, self.plan_sha, output, maximum=12, reserve=0)
        self.assertFalse(output.exists())
        self.assertTrue(output.with_name(output.name + ".partial").exists())
        failure = json.loads(output.with_name(output.name + ".failure.json").read_bytes())
        self.assertEqual(failure["status"], "FAILED")
        self.assertTrue(failure["partial_retained"])

    def test_external_pin_live_root_and_source_reference_mismatch_reject(self):
        self.config["roots"][0]["pins"]["seal.json"] = "0" * 64
        with self.assertRaisesRegex(ArchiveError, "external root pin"):
            self.plan()
        self.config["roots"][0]["status"] = "running"
        with self.assertRaisesRegex(ArchiveError, "live/unsealed"):
            self.plan()
        self.config["roots"][0]["status"] = "sealed"
        (self.root / "published.py").write_bytes(b"changed after Git publication")
        with self.assertRaisesRegex(ArchiveError, "published source reference differs"):
            self.plan()

    def test_symlink_and_whole_git_root_are_not_archived(self):
        (self.root / "linked").symlink_to(self.root / "a.bin")
        with self.assertRaisesRegex(ArchiveError, "symlink"):
            self.plan()
        (self.root / "linked").unlink()
        (self.root / ".git").write_text("gitdir: forbidden fixture")
        with self.assertRaisesRegex(ArchiveError, "whole Git"):
            self.plan()

    def test_raw_evidence_cannot_be_skipped_via_git_reference(self):
        reference = self.config["roots"][0]["source_references"]["published.py"]
        self.config["roots"][0]["source_references"]["seal.json"] = {
            **reference, "path": "qa/evidence/seal.json", "sha256": digest((self.root / "seal.json").read_bytes())}
        with self.assertRaisesRegex(ArchiveError, "raw evidence cannot"):
            self.plan()

    def test_seal_label_without_complete_historical_file_pins_cannot_reseal_changed_raw(self):
        complete = self.config["roots"][0]["pins"].copy()
        self.config["roots"][0]["pins"] = {"seal.json": complete["seal.json"]}
        with self.assertRaisesRegex(ArchiveError, "every retained file"):
            self.plan()
        self.config["roots"][0]["pins"] = complete
        (self.root / "a.bin").write_bytes(b"raw changed but old seal preserved")
        with self.assertRaisesRegex(ArchiveError, "external root pin differs"):
            self.plan()

    def test_explicit_interrupted_root_is_inventoried_without_claiming_a_prior_seal(self):
        self.config["roots"][0].update(status="interrupted", pins={})
        plan = self.plan()
        self.assertEqual(plan["configuration"]["roots"][0]["status"], "interrupted")
        self.assertTrue(all(len(row["sha256"]) == 64 for row in plan["members"]))
        _, receipt = self.build()
        self.assertFalse(receipt["scientific_verdict_from_archive"])

    def test_mutation_during_independent_verification_cannot_be_finalized(self):
        self.plan()
        def verify_then_change(*args, **kwargs):
            result = verify_archive(*args, **kwargs)
            (self.root / "a.bin").write_bytes(b"changed while verifier was running")
            return result
        with patch("archive_pack_v8.verify_archive", side_effect=verify_then_change):
            with self.assertRaisesRegex(ArchiveError, "inventory changed"):
                self.build()
        self.assertFalse((self.base / "complete.tar.gz").exists())
        self.assertTrue((self.base / "complete.tar.gz.partial").exists())

    def test_receipt_publication_failure_preserves_archive_without_pass_commit_marker(self):
        self.plan()
        real_link = os.link
        def fail_receipt(source, destination):
            if str(destination).endswith(".receipt.json"):
                raise OSError("synthetic receipt publication interruption")
            return real_link(source, destination)
        with patch("archive_pack_v8.os.link", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "receipt publication interruption"):
                self.build()
        output = self.base / "complete.tar.gz"
        self.assertTrue(output.exists())
        self.assertFalse((self.base / "complete.tar.gz.receipt.json").exists())
        self.assertTrue((self.base / "complete.tar.gz.receipt.json.partial").exists())
        failure = json.loads((self.base / "complete.tar.gz.failure.json").read_bytes())
        self.assertEqual(failure["status"], "FAILED")
        self.assertTrue(failure["final_archive_exists"])
        self.assertEqual(verify_archive(output, self.plan_file, self.plan_sha)["status"], "PASS")

    def test_unsafe_hardlinks_and_bad_external_manifest_hash_reject(self):
        with self.assertRaises(ArchiveError):
            relative_name(".")
        plan = self.plan()
        with self.assertRaisesRegex(ArchiveError, "external JSON identity"):
            validate_plan(self.plan_file, "0" * 64)
        row = next(r for r in plan["members"] if r["link_to"] is not None)
        for target in ("../escape", "evidence/later", row["member"]):
            row["link_to"] = target
            raw = canonical(plan)
            altered = self.base / "altered-plan.json"
            altered.write_bytes(raw)
            with self.assertRaisesRegex(ArchiveError, "earlier identical"):
                validate_plan(altered, digest(raw))

    def test_capacity_uses_effective_uid_and_retains_explicit_reserve(self):
        current = capacity(self.base)
        stat = os.statvfs(self.base)
        self.assertGreaterEqual(current["f_bfree_bytes"], current["f_bavail_bytes"])
        self.assertEqual(current["effective_free_bytes"], current["f_bfree_bytes"] if os.geteuid() == 0 else current["f_bavail_bytes"])
        self.plan()
        with self.assertRaisesRegex(ArchiveError, "free space and reserve"):
            pack(self.plan_file, self.plan_sha, self.base / "reserve.tar.gz", 1 << 20, reserve=stat.f_blocks * stat.f_frsize + 1)
        self.assertFalse((self.base / "reserve.tar.gz.partial").exists())

    def test_all_new_outputs_reject_raw_roots_outside_workspace_and_input_collision(self):
        raw = canonical(self.config)
        self.roots_file.write_bytes(raw)
        before = self.roots_file.read_bytes()
        with tempfile.TemporaryDirectory(prefix="outside-approved-", dir=Path(__file__).parent) as outside:
            for path in (self.root / "new-plan.json", Path(outside) / "new-plan.json", self.roots_file):
                with self.assertRaises(ArchiveError):
                    make_plan(self.roots_file, digest(raw), path)
                if path != self.roots_file:
                    self.assertFalse(path.exists())
            self.assertEqual(self.roots_file.read_bytes(), before)
            self.plan()
            for path in (self.root / "new.tar.gz", Path(outside) / "new.tar.gz", self.plan_file):
                with self.assertRaises(ArchiveError):
                    pack(self.plan_file, self.plan_sha, path, 1 << 20, reserve=0)
                if path != self.plan_file:
                    self.assertFalse(path.exists())

    def test_actual_late_source_changes_reject_plan_and_measure_without_touching_real_tools(self):
        self.plan()
        for phase in ("plan", "measure"):
            with self.subTest(phase=phase):
                isolated = self.base / ("isolated-tools-" + phase)
                isolated.mkdir()
                for name in ("archive_plan_v8.py", "archive_pack_v8.py", "archive_verify_v8.py", "archive_cli_v8.py"):
                    shutil.copyfile(Path(__file__).with_name(name), isolated / name)
                code = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import archive_plan_v8 as plan
import archive_pack_v8 as pack
root, phase, roots_file, roots_sha, plan_file, plan_sha, new_plan = sys.argv[1:]
module, target = (plan, "scan") if phase == "plan" else (pack, "write_stream")
original = getattr(module, target)
def change_after_work(*args, **kwargs):
    value = original(*args, **kwargs)
    source = Path(root)/"archive_cli_v8.py"
    source.write_bytes(source.read_bytes()+b"\\n# synthetic concurrent source change\\n")
    return value
setattr(module, target, change_after_work)
try:
    if phase == "plan":
        plan.make_plan(roots_file, roots_sha, new_plan)
    else:
        pack.measure(plan_file, plan_sha)
except plan.ArchiveError as error:
    assert "source changed" in str(error), str(error)
else:
    raise AssertionError("late source changes were accepted")
'''
                result = subprocess.run([sys.executable, "-c", code, str(isolated), phase, str(self.roots_file),
                    digest(self.roots_file.read_bytes()), str(self.plan_file), self.plan_sha, str(self.base / "new-plan.json")],
                    capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((self.base / "new-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
