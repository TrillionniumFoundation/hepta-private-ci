"""Artificial fixtures for strict relocation and honest historical chronology."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from . import analysis_audit
from .analysis_tests import fixture
from .portable_replay import (CHRONOLOGY_ERROR, LogRelocation, RESULTS_SUFFIX,
                              compare_tree, isolated_audit, member_path, recorded_order,
                              verify_members)


class PortableReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hcsn-portable-fixture-")
        self.base = Path(self.temp.name)
        self.root = self.base/"restored"
        self.name = "study001/meter/example.json.log"
        self.log = self.root/self.name
        self.log.parent.mkdir(parents=True)
        self.log.write_bytes(b"published log\n")
        self.sha = hashlib.sha256(self.log.read_bytes()).hexdigest()
        self.index = {self.name: dict(path=self.name, bytes=self.log.stat().st_size, sha256=self.sha)}
        self.old = self.base/"old_repository"
        self.receipt = dict(cwd=str(self.old), log_path=str(self.old/str(RESULTS_SUFFIX)/self.name), log_sha256=self.sha)

    def tearDown(self):
        self.temp.cleanup()

    def test_absolute_and_relative_logs_map_only_to_new_tree(self):
        resolver = LogRelocation(self.root, self.index)
        self.assertFalse(self.old.exists())
        self.assertEqual(resolver.add(self.receipt, self.name), self.log)
        relative = dict(self.receipt, log_path=str(RESULTS_SUFFIX/self.name))
        self.assertEqual(resolver.add(relative, self.name), self.log)
        self.assertEqual(resolver.path(relative["log_path"]), self.log)

    def test_prefix_lookalike_other_job_and_parent_paths_are_rejected(self):
        resolver = LogRelocation(self.root, self.index)
        for path in (str(self.old)+"_lookalike/"+str(RESULTS_SUFFIX/self.name),
                     str(self.old/str(RESULTS_SUFFIX)/"study001/meter/another.json.log"),
                     str(self.old/str(RESULTS_SUFFIX)/"study001/meter/../meter/example.json.log"),
                     "/etc/passwd"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolver.add(dict(self.receipt, log_path=path), self.name)

    def test_hash_mismatch_is_rejected_even_when_old_log_exists(self):
        old = Path(self.receipt["log_path"])
        old.parent.mkdir(parents=True)
        old.write_bytes(b"published log\n")
        self.log.write_bytes(b"tampered relocated log\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            LogRelocation(self.root, self.index).add(self.receipt, self.name)

    def test_symlink_escape_is_rejected(self):
        outside = self.base/"outside.log"
        outside.write_bytes(b"published log\n")
        self.log.unlink()
        self.log.symlink_to(outside)
        with self.assertRaises(ValueError):
            member_path(self.root, self.name)

    def test_manifest_member_mutation_is_rejected(self):
        path = self.base/"manifest.json"
        path.write_text(json.dumps(dict(schema="hcsn-evidence-bundle.v1", members=list(self.index.values()))))
        _, index = verify_members(self.root, path)
        self.assertEqual(index, self.index)
        self.log.write_bytes(b"changed\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            verify_members(self.root, path)

    def test_recorded_load_order_is_distinct_from_filesystem_order(self):
        meter = dict(started_at_utc="1970-01-01T00:00:00+00:00", ended_at_utc="1970-01-01T00:00:05+00:00")
        access = [dict(split=s, unix_seconds=t) for t, s in enumerate(("train", "val", "test"), 1)]
        self.assertTrue(recorded_order(access, meter))
        bad = copy.deepcopy(access)
        bad[0]["split"] = "test"
        self.assertFalse(recorded_order(bad, meter))
        access[-1]["unix_seconds"] = 6
        self.assertFalse(recorded_order(access, meter))

    def test_relocated_audit_keeps_mtime_failure_and_does_not_patch_global_module(self):
        source = self.base/"source"
        source.mkdir()
        study = self.base/"fixture_root/study001"
        protocol, _ = fixture(study, source)
        meter_path = study/"meter/fixture.json"
        meter = json.loads(meter_path.read_text())
        name = "study001/meter/fixture.json.log"
        meter.update(cwd=str(self.old), log_path=str(self.old/str(RESULTS_SUFFIX)/name))
        meter_path.write_text(json.dumps(meter))
        log = study/"meter/fixture.json.log"
        index = {name: dict(path=name, bytes=log.stat().st_size, sha256=meter["log_sha256"])}
        resolver = LogRelocation(study.parent, index)
        resolver.add(meter, name)
        module = isolated_audit(resolver)
        module.PACKAGE = source
        selection = study/"runs/fixture/selection.json"
        access = json.loads((study/"runs/fixture/access.json").read_text())
        later = max(row["unix_seconds"] for row in access)+100
        os.utime(selection, (later, later))  # Simulate new restoration mtime, not a bypass.
        result = module.audit_job(study, analysis_audit.registered_jobs(study, protocol)[0])
        self.assertEqual(result["errors"], [CHRONOLOGY_ERROR])
        self.assertFalse(result["audit_ok"])
        self.assertIs(analysis_audit.Path, Path)
        self.assertEqual(selection.stat().st_mtime, later)

    def test_numeric_comparison_rejects_changed_results_and_boolean_coercion(self):
        self.assertEqual(compare_tree({"x": [1., 2.]}, {"x": [1., 2.]})["numbers"], 2)
        with self.assertRaises(ValueError):
            compare_tree({"x": .2}, {"x": .3})
        with self.assertRaises(ValueError):
            compare_tree({"gate": True}, {"gate": 1})


if __name__ == "__main__":
    unittest.main()
