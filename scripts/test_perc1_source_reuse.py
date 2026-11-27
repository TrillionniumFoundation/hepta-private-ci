"""Negative controls for PERC source-reuse audit."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipIf
from unittest.mock import patch

from perc1_source_reuse import audit, read_manifest


def h(char):
    return char * 64


def manifest(t, d, c):
    return {
        "schema": "perc1.manifest.v1",
        "splits": {"train": t, "dev": d, "confirmation": c},
    }


def save(path, value):
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class SourceReuseTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.old = Path(tmp.name) / "old.json"
        self.new = Path(tmp.name) / "new.json"
        self.pin = save(self.old, manifest([h("1")], [h("2")], [h("3")]))

    def check(self, t, d, c):
        save(self.new, manifest(t, d, c))
        return audit(self.new, [(self.old, self.pin)])

    def test_previous_confirmation_as_new_confirmation_is_rejected(self):
        v = self.check([h("4")], [h("5")], [h("3")])
        self.assertEqual(v["status"], "HOLD_REUSED_SOURCE")
        self.assertEqual(v["overlap"][0]["prior_role"], "confirmation")

    def test_previous_confirmation_as_training_is_rejected(self):
        v = self.check([h("3")], [h("4")], [h("5")])
        self.assertEqual(v["overlap"][0]["candidate_role"], "train")

    def test_previous_training_as_confirmation_is_rejected(self):
        self.assertEqual(
            self.check([h("4")], [h("5")], [h("1")])["status"], "HOLD_REUSED_SOURCE"
        )

    def test_disjoint_never_means_independent_science(self):
        v = self.check([h("4")], [h("5")], [h("6")])
        self.assertEqual(v["status"], "PASS_GROUP_REUSE_CHECK_ONLY")
        for field in (
            "scientific_qualified",
            "origin_group_mapping_attested",
            "prior_registry_complete",
        ):
            self.assertFalse(v[field])

    def test_mutated_prior_fails_closed(self):
        self.old.write_bytes(self.old.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.check([h("4")], [h("5")], [h("6")])

    def test_duplicate_and_cross_split_rejected(self):
        save(self.new, manifest([h("4"), h("4")], [h("5")], [h("6")]))
        with self.assertRaisesRegex(ValueError, "duplicate group"):
            audit(self.new, [(self.old, self.pin)])
        save(self.new, manifest([h("4")], [h("4")], [h("6")]))
        with self.assertRaisesRegex(ValueError, "crosses split"):
            audit(self.new, [(self.old, self.pin)])

    def test_invalid_id_or_missing_prior_rejected(self):
        save(self.new, manifest([h("4")], [h("5")], ["fake-source-id"]))
        with self.assertRaisesRegex(ValueError, "64-hex"):
            audit(self.new, [(self.old, self.pin)])
        with self.assertRaisesRegex(ValueError, "missing prior"):
            audit(self.new, [])

    def test_duplicate_json_keys_rejected(self):
        self.new.write_text('{"schema":"perc1.manifest.v1","schema":"x","splits":{}}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            read_manifest(self.new)

    def test_duplicate_prior_path_rejected(self):
        save(self.new, manifest([h("4")], [h("5")], [h("6")]))
        with self.assertRaisesRegex(ValueError, "duplicate prior"):
            audit(self.new, [(self.old, self.pin), (self.old, self.pin)])

    def test_output_atomic_exclusive_create_and_no_clobber(self):
        save(self.new, manifest([h("4")], [h("5")], [h("6")]))
        output = self.new.with_name("receipt.json")
        from perc1_source_reuse import main

        args = [
            "perc1_source_reuse.py",
            "--candidate",
            str(self.new),
            "--prior",
            str(self.old),
            self.pin,
            "--output",
            str(output),
        ]
        with patch("sys.argv", args):
            self.assertEqual(main(), 0)
            first = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "refuse to overwrite"):
                main()
        self.assertEqual(output.read_bytes(), first)
        self.assertEqual(json.loads(first)["status"], "PASS_GROUP_REUSE_CHECK_ONLY")
        if os.name == "posix":
            self.assertEqual(output.stat().st_mode & 0o077, 0)

    @skipIf(os.name == "nt", "symlink creation requires Windows privileges")
    def test_dangling_output_symlink_fails_closed(self):
        save(self.new, manifest([h("4")], [h("5")], [h("6")]))
        output = self.new.with_name("receipt-link.json")
        target = self.new.with_name("unexpected-created.json")
        output.symlink_to(target)
        from perc1_source_reuse import main

        args = [
            "perc1_source_reuse.py",
            "--candidate",
            str(self.new),
            "--prior",
            str(self.old),
            self.pin,
            "--output",
            str(output),
        ]
        with patch("sys.argv", args):
            with self.assertRaisesRegex(ValueError, "refuse to overwrite"):
                main()
        self.assertFalse(target.exists())
