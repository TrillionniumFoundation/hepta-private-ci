"""Actual descriptor I/O in disposable fixtures; no live host enrollment."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from assimilation.discovery import DiscoveryError, DiscoveryScope, discover
from assimilation.discovery import reader
from assimilation.discovery.parsers import parse_packages, parse_unit


PACKAGE = b"Package: example-app\nStatus: install ok installed\nArchitecture: amd64\nVersion: 1.0-1\nDescription: ignored\n secret description\n"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write("etc/os-release", b'ID=debian\nVERSION_ID="13"\nPRETTY_NAME="not retained"\n')
        self.write("var/lib/dpkg/status", PACKAGE)
        self.write("etc/systemd/system/api.service", b"[Unit]\nAfter=db.service network.target\nRequires=db.service\n[Service]\nExecStart=/bin/false --secret=HIDDEN_SECRET\n")
        self.write("etc/systemd/system/db.service", b"[Unit]\nDescription=ignored\n[Service]\nExecStart=/bin/false\n")
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        st = os.fstat(self.fd)
        self.scope = DiscoveryScope(st.st_dev, st.st_ino, "1" * 64, "2" * 64, 10_000,
                                    ("etc/systemd/system/api.service", "etc/systemd/system/db.service"))

    def tearDown(self):
        os.close(self.fd)
        self.tmp.cleanup()

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def run_discovery(self, scope=None, clock=lambda: 1):
        return discover(self.fd, scope or self.scope, clock=clock)

    def assert_rejected(self, code, scope=None):
        with self.assertRaisesRegex(DiscoveryError, f"^{code}$"):
            self.run_discovery(scope)

    def test_real_file_inventory_and_graph(self):
        result = self.run_discovery()
        data = json.loads(result.payload)
        self.assertEqual(result.sha256, hashlib.sha256(result.payload).hexdigest())
        self.assertEqual(data["ordering"], ["db.service", "api.service"])
        self.assertEqual(data["unresolved_dependencies"], ["network.target"])
        self.assertEqual(data["installed_packages"], [{"name": "example-app", "architecture": "amd64", "version": "1.0-1", "selection": "install", "error_flag": "ok"}])
        self.assertEqual(data["coverage"], "selected_metadata_only")
        self.assertFalse(data["drop_ins_resolved"])
        self.assertFalse(data["runtime_authority"])
        self.assertFalse(data["activation"])
        self.assertEqual(len(data["sources"]), 4)
        self.assertNotIn(b"HIDDEN_SECRET", result.payload)
        self.assertNotIn(b"secret description", result.payload)
        self.assertNotIn(b"ExecStart", result.payload)

    def test_replay_and_unit_selection_permutation_are_canonical(self):
        first = self.run_discovery()
        self.assertEqual(first, self.run_discovery())
        self.assertEqual(first, self.run_discovery(replace(self.scope, unit_paths=tuple(reversed(self.scope.unit_paths)))))

    def test_no_file_mutation(self):
        before = {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.run_discovery()
        after = {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_scope_identity_and_expiry(self):
        self.assert_rejected("root_identity_mismatch", replace(self.scope, root_inode=self.scope.root_inode + 1))
        self.assert_rejected("expired_scope", replace(self.scope, expires_unix_ns=1))
        for digest in ("0" * 64, "arbitrary", None):
            self.assert_rejected("invalid_scope_digest", replace(self.scope, enrollment_receipt_digest=digest))

    def test_expiry_during_read_discards_candidate(self):
        ticks = iter([1, 1, 1, 1, 1, 10_001])
        with self.assertRaisesRegex(DiscoveryError, "expired_scope"):
            self.run_discovery(clock=lambda: next(ticks))

    def test_scope_paths_cannot_escape_or_scan_credentials(self):
        for path in ("/etc/shadow", "etc/shadow", "../outside.service", "etc/systemd/system/../shadow", "etc/systemd/system/a/b.service"):
            self.assert_rejected("path_outside_scope", replace(self.scope, unit_paths=(path,)))

    def test_duplicate_and_ambiguous_service_files_are_rejected(self):
        path = self.scope.unit_paths[0]
        self.assert_rejected("duplicate_or_excess_unit", replace(self.scope, unit_paths=(path, path)))
        self.assert_rejected("ambiguous_unit_override", replace(self.scope, unit_paths=(path, "usr/lib/systemd/system/api.service")))

    def test_final_symlink_is_not_followed(self):
        path = self.root / "etc/os-release"
        path.unlink()
        path.symlink_to("/etc/passwd")
        self.assert_rejected("filesystem_rejected")

    def test_vendor_os_release_requires_explicit_host_selection(self):
        self.write("usr/lib/os-release", b"ID=debian\nVERSION_ID=13\n")
        local = self.root / "etc/os-release"
        local.unlink()
        local.symlink_to("../usr/lib/os-release")
        self.assert_rejected("filesystem_rejected")
        result = self.run_discovery(replace(self.scope, os_release_path="usr/lib/os-release"))
        data = json.loads(result.payload)
        self.assertEqual(data["sources"][0]["path"], "usr/lib/os-release")
        self.assertEqual(data["scope"]["os_release_path"], "usr/lib/os-release")

    def test_os_release_selection_cannot_expand_path_scope(self):
        for path in ("etc/shadow", "../os-release", "/usr/lib/os-release"):
            self.assert_rejected("path_outside_scope", replace(self.scope, os_release_path=path))

    def test_ancestor_symlink_is_not_followed(self):
        (self.root / "var").rename(self.root / "real-var")
        (self.root / "var").symlink_to("real-var", target_is_directory=True)
        self.assert_rejected("filesystem_rejected")

    def test_hardlinked_file_is_rejected(self):
        os.link(self.root / "etc/os-release", self.root / "other")
        self.assert_rejected("unsupported_file")

    def test_fifo_is_rejected_without_waiting_for_writer(self):
        path = self.root / "etc/os-release"
        path.unlink()
        os.mkfifo(path)
        self.assert_rejected("unsupported_file")

    def test_non_directory_root_is_rejected(self):
        fd = os.open(self.root / "etc/os-release", os.O_RDONLY)
        try:
            with self.assertRaisesRegex(DiscoveryError, "root_identity_mismatch"):
                discover(fd, self.scope, clock=lambda: 1)
        finally:
            os.close(fd)

    def test_oversized_file_is_rejected_before_allocation(self):
        with (self.root / "var/lib/dpkg/status").open("wb") as stream:
            stream.truncate(2_097_153)
        self.assert_rejected("byte_limit")

    def test_changed_file_between_passes_is_rejected(self):
        original = reader._read_at
        calls = 0
        def changing(*args):
            nonlocal calls
            calls += 1
            if calls == 5:
                self.write("etc/os-release", b"ID=debian\nVERSION_ID=12\n")
            return original(*args)
        with patch.object(reader, "_read_at", side_effect=changing):
            self.assert_rejected("inventory_drift")

    def test_read_path_descriptor_replacement_is_rejected(self):
        original = os.read
        done = False
        def replace_while_reading(fd, count):
            nonlocal done
            data = original(fd, count)
            if not done:
                done = True
                self.write("etc/replacement", b"ID=debian\nVERSION_ID=13\n")
                os.replace(self.root / "etc/replacement", self.root / "etc/os-release")
            return data
        with patch.object(reader.os, "read", side_effect=replace_while_reading):
            self.assert_rejected("inventory_drift")

    def test_truncated_status_utf8_and_duplicate_field_reject(self):
        for payload, code in ((b"Package: example\n", "missing_package_field"),
                              (b"\xff", "invalid_utf8"),
                              (PACKAGE + b"Package: second\n", "duplicate_or_excess_package_field"),
                              (PACKAGE.replace(b"install ok installed", b"success"), "invalid_package_status")):
            self.write("var/lib/dpkg/status", payload)
            self.assert_rejected(code)

    def test_held_installed_package_is_not_misclassified(self):
        packages, count = parse_packages(PACKAGE.replace(b"install ok", b"hold ok"))
        self.assertEqual(count, 1)
        self.assertEqual(packages[0].selection, "hold")
        self.assertEqual(packages[0].name, "example-app")

    def test_reinstall_required_flag_is_preserved(self):
        packages, _ = parse_packages(PACKAGE.replace(b"install ok", b"install reinstreq"))
        self.assertEqual(packages[0].error_flag, "reinstreq")

    def test_uninstalled_record_count_is_explicit(self):
        packages, count = parse_packages(PACKAGE + b"\nPackage: removed-app\nStatus: deinstall ok config-files\n")
        self.assertEqual(len(packages), 1)
        self.assertEqual(count, 2)

    def test_duplicate_package_identity_is_rejected(self):
        self.write("var/lib/dpkg/status", PACKAGE + b"\n" + PACKAGE)
        self.assert_rejected("duplicate_package")

    def test_unit_empty_dependency_does_not_erase_prior_edge(self):
        unit = parse_unit("api.service", b"[Unit]\nAfter=db.service\nAfter=\nAfter = cache.service\n")
        self.assertEqual(unit.after, ("cache.service", "db.service"))

    def test_ordering_cycle_is_not_reported_as_healthy_order(self):
        self.write("etc/systemd/system/db.service", b"[Unit]\nAfter=api.service\n")
        data = json.loads(self.run_discovery().payload)
        self.assertEqual(data["ordering"], [])
        self.assertEqual(data["ordering_blocked"], ["api.service", "db.service"])

    def test_requires_cycle_is_not_mistaken_for_ordering_cycle(self):
        self.write("etc/systemd/system/api.service", b"[Unit]\nRequires=db.service\n")
        self.write("etc/systemd/system/db.service", b"[Unit]\nRequires=api.service\n")
        data = json.loads(self.run_discovery().payload)
        self.assertEqual(data["ordering_blocked"], [])
        self.assertEqual(data["ordering"], ["api.service", "db.service"])

    def test_unsupported_unit_syntax_is_not_guessed(self):
        for data, code in ((b"[Unit]\nAfter=%i.service\n", "unsupported_dependency"),
                           (b"[Unit]\nAfter=db.service \\\n cache.service\n", "unsupported_continuation"),
                           (b"", "masked_unit")):
            self.write("etc/systemd/system/api.service", data)
            self.assert_rejected(code)

    def test_bounds_and_control_characters(self):
        for data, code in ((b"Package: " + b"a" * 4097, "line_limit"), (b"Package: aa\x00", "control_character")):
            with self.assertRaisesRegex(DiscoveryError, code):
                parse_packages(data)
        with self.assertRaisesRegex(DiscoveryError, "package_limit"):
            parse_packages(b"Package: absent\nStatus: unknown ok not-installed\n\n" * 4097)

    def test_file_descriptors_are_closed_on_success_and_failure(self):
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(20):
            self.run_discovery()
            self.assert_rejected("root_identity_mismatch", replace(self.scope, root_inode=0))
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)


if __name__ == "__main__":
    unittest.main()
