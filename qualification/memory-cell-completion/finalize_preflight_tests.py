"""Small synthetic integrity tests; no training, model evaluation or native tests."""

import io
import json
import lzma
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_transport import MAX_PAX_HEADER, NATIVE_PREFIX, canonical, identity, verify_transport
from finalize_preflight import PACKAGES, REQUIRED, preflight
from source_freeze import ADAPTER, FORMAL_FREEZE, PACKER, SOURCE_BINDING, git, verify_after


class Evidence:
    def __init__(self, root, commit="a" * 40, tree="b" * 40):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.manifest = root / "TRANSPORT.json"
        self.commit, self.tree = commit, tree
        ordinary = ["just", "test", "--locked"]
        for package in PACKAGES:
            ordinary.extend(["-p", package])
        self.commands = [ordinary, ["just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd",
            "--run-ignored", "only", "-E", "test(memory_cell_) & test(actual_) & test(v9)"]]
        self.files = {name: canonical({"schema": "synthetic-integrity-only", "quality_gate_passed": False})
                      for name in REQUIRED}
        self.files.update({"generated.patch": b"", "execution.log": b"synthetic command transcript\n",
                           "commands/01.log": b"first command\n", "commands/02.log": b"second command\n",
                           "migration.artifacts/payload:1": b"exact colon-containing bytes\0\xff"})
        self.files["pax-path/" + "long" * 35 + ":1"] = b"ordinary local PAX path\n"
        self.verify_request = {"schema": "hepta.memory.v9.verification-request.v1", "mode": "formal",
                               "attempt": "synthetic-integrity-only", "tests_before_final_fix_and_format": True}

    def build(self, *, omitted=None, extra=(), replacement=None, tail=b"", corrupt_member=None,
              receipt_change=None, compressed_tail=b"", tar_prefix=b""):
        receipt = {"schema": "hepta.memory.v9.product-ci-receipt.v1", "passed": True,
            "source_commit": self.commit, "source_tree": self.tree, "request": self.verify_request,
            "tests_before_final_fix_and_format": True, "initial_tracked_changes": "",
            "final_tracked_changes": "", "missing_required_receipts": [],
            "files": {name: identity(data) for name, data in self.files.items()}, "executions": [
                {"command": command, "exit_code": 0, "raw_output_path": f"commands/{index:02}.log",
                 "raw_output": identity(self.files[f"commands/{index:02}.log"])}
                for index, command in enumerate(self.commands, 1)]}
        if receipt_change:
            receipt_change(receipt)
        receipt_raw = canonical(receipt)
        (self.root / "receipt.json").write_bytes(receipt_raw)
        entries = {NATIVE_PREFIX + name: data for name, data in self.files.items()}
        entries[NATIVE_PREFIX + "receipt.json"] = receipt_raw
        entries["preparation/V9_PREPARATION.json"] = b"{}\n"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, data in [*sorted(entries.items()), *extra]:
                if name == omitted:
                    continue
                member = tarfile.TarInfo(name)
                member.size = len(data)
                if name == corrupt_member:
                    data = bytes([data[0] ^ 1]) + data[1:]
                if replacement and name == replacement[0]:
                    member.type, member.linkname, member.size = replacement[1], "../outside", 0
                archive.addfile(member, io.BytesIO(data))
        payload = lzma.compress(tar_prefix + buffer.getvalue() + tail) + compressed_tail
        archive_pin = {"path": "memory-v9-evidence.tar.xz", **identity(payload)}
        index = {"schema": "hepta.memory.v9.portable-evidence.v1", "files": {
            name: identity(data) for name, data in entries.items()}, "nonregular_entries": {},
            "archive": archive_pin, "original_file_names_preserved": True, "symlinks_followed": False,
            "model_or_measurement_bytes_changed": False}
        index_raw = canonical(index)
        (self.root / "INDEX.json").write_bytes(index_raw)
        chunks = []
        (self.root / "chunks").mkdir(exist_ok=True)
        for number, offset in enumerate(range(0, len(payload), 128)):
            name, data = f"chunks/{number:04}.part", payload[offset:offset + 128]
            (self.root / name).write_bytes(data)
            chunks.append({"path": name, "offset": offset, **identity(data)})
        manifest = {"schema": "hepta.memory.completion.transport.v1",
            "source": {"commit": self.commit, "tree": self.tree, "run_id": 123, "job_id": 456},
            "archive": archive_pin, "index": {"path": "INDEX.json", **identity(index_raw)},
            "receipt": {"path": "receipt.json", **identity(receipt_raw)}, "chunks": chunks}
        self.manifest.write_bytes(canonical(manifest))
        return manifest


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-completion-gate-")
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Evidence(Path(self.temporary.name))

    def test_exact_stream_preserves_colons_empty_files_and_negative_scientific_outcomes(self):
        self.evidence.build()
        _, receipt, audit = verify_transport(self.evidence.manifest)
        self.assertEqual(receipt["files"]["generated.patch"], identity(b""))
        self.assertEqual(audit["verified_regular_files"], len(self.evidence.files) + 2)
        self.assertEqual(audit["extracted_files"], 0)

    def test_corrupted_or_missing_chunk_is_rejected(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                manifest = self.evidence.build()
                path = self.evidence.root / manifest["chunks"][0]["path"]
                if missing:
                    path.unlink()
                else:
                    data = bytearray(path.read_bytes())
                    data[0] ^= 1
                    path.write_bytes(data)
                with self.assertRaises((ValueError, OSError)):
                    verify_transport(self.evidence.manifest)

    def test_missing_member_and_duplicate_member_are_rejected(self):
        name = NATIVE_PREFIX + "migration-process.json"
        for options in ({"omitted": name}, {"extra": [(name, self.evidence.files["migration-process.json"])]}):
            with self.subTest(options=list(options)):
                self.evidence.build(**options)
                with self.assertRaises(ValueError):
                    verify_transport(self.evidence.manifest)

    def test_escaping_absolute_and_noncanonical_member_paths_are_rejected(self):
        for path in ("../outside", "/absolute", NATIVE_PREFIX + "a/../b", NATIVE_PREFIX + "a//b"):
            with self.subTest(path=path):
                self.evidence.build(extra=[(path, b"data")])
                with self.assertRaises(ValueError):
                    verify_transport(self.evidence.manifest)

    def test_links_and_special_tar_members_are_rejected(self):
        name = NATIVE_PREFIX + "migration-process.json"
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind):
                self.evidence.build(replacement=(name, kind))
                with self.assertRaises(ValueError):
                    verify_transport(self.evidence.manifest)

    def test_symlinked_chunk_is_rejected(self):
        manifest = self.evidence.build()
        path = self.evidence.root / manifest["chunks"][0]["path"]
        other = path.with_name("original")
        path.rename(other)
        path.symlink_to(other.name)
        with self.assertRaises(ValueError):
            verify_transport(self.evidence.manifest)

    def test_duplicate_json_offset_gap_and_chunk_path_escape_are_rejected(self):
        for change in ("duplicate", "offset", "escape"):
            with self.subTest(change=change):
                manifest = self.evidence.build()
                if change == "duplicate":
                    self.evidence.manifest.write_bytes(b'{"schema":"a","schema":"b"}')
                else:
                    manifest["chunks"][0]["offset" if change == "offset" else "path"] = 1 if change == "offset" else "../outside"
                    self.evidence.manifest.write_bytes(canonical(manifest))
                with self.assertRaises(ValueError):
                    verify_transport(self.evidence.manifest)

    def test_unlisted_nonzero_tar_tail_is_rejected(self):
        self.evidence.build(tail=b"unlisted payload")
        with self.assertRaises(ValueError):
            verify_transport(self.evidence.manifest)

    def test_member_corruption_is_rejected_even_when_transport_hashes_match(self):
        self.evidence.build(corrupt_member=NATIVE_PREFIX + "migration-process.json")
        with self.assertRaisesRegex(ValueError, "member digest"):
            verify_transport(self.evidence.manifest)

    def test_xz_trailing_data_is_rejected_even_when_transport_hashes_match(self):
        self.evidence.build(compressed_tail=b"unexpected compressed trailer")
        with self.assertRaisesRegex(ValueError, "trailing compressed"):
            verify_transport(self.evidence.manifest)

    def test_pax_metadata_bounds_reject_before_unbounded_processing(self):
        header = tarfile.TarInfo("PaxHeader")
        header.type, header.size = tarfile.XHDTYPE, MAX_PAX_HEADER + 1
        oversized = header.tobuf(format=tarfile.PAX_FORMAT)
        header.size = 0
        nested = header.tobuf(format=tarfile.PAX_FORMAT) * 2
        sparse = tarfile.TarInfo("sparse")
        sparse.pax_headers = {"GNU.sparse.major": "1", "GNU.sparse.minor": "0"}
        for prefix, error in ((oversized, "PAX metadata length exceeds"), (nested, "nested PAX"),
                              (sparse.tobuf(format=tarfile.PAX_FORMAT), "sparse PAX")):
            with self.subTest(error=error):
                # Tiny archives declare dangerous metadata; no large body is created.
                self.evidence.build(tar_prefix=prefix)
                with self.assertRaisesRegex(ValueError, error):
                    verify_transport(self.evidence.manifest)


class SourceAndReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-completion-source-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        git(self.repo, "config", "user.name", "Integrity Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        source = ADAPTER + "tensor_cell.py"
        self.write(source, b"value = 1\n")
        self.write(PACKER, b"# frozen packer fixture\n")
        frozen = {source: identity((self.repo / source).read_bytes())}
        self.write(FORMAL_FREEZE, canonical({"schema": "hepta.memory.adapter-freeze.v1",
                                           "source_files": {"tensor_cell.py": frozen[source]}}))
        temporary_evidence = Evidence(self.repo / "proof")
        self.write("qualification/memory-cell-v9/VERIFY_REQUEST.json", canonical(temporary_evidence.verify_request))
        self.commit()
        origin, tree = self.head(), git(self.repo, "rev-parse", "HEAD^{tree}").decode().strip()
        self.write(SOURCE_BINDING, canonical({"all_frozen_files_match_committed_blobs": True,
            "files": frozen, "remote_source_commit": origin, "remote_source_tree": tree}))
        self.commit()
        self.evidence = Evidence(self.repo / "proof", self.head(), git(self.repo, "rev-parse", "HEAD^{tree}").decode().strip())
        self.request = self.repo / "qualification/memory-cell-v9/FINALIZE_REQUEST.json"
        self.build()

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def commit(self):
        git(self.repo, "add", "--", "qualification")
        git(self.repo, "commit", "-q", "-m", "integrity fixture")

    def head(self):
        return git(self.repo, "rev-parse", "HEAD").decode().strip()

    def build(self):
        manifest = self.evidence.build()
        self.request.write_bytes(canonical({"schema": "hepta.memory.v9.finalize-request.v1",
            "tested_commit": self.evidence.commit, "verification_receipt": {
                "path": "proof/receipt.json", **{key: manifest["receipt"][key] for key in ("bytes", "sha256")}}}))

    def run_gate(self, freezes=()):
        return preflight(self.repo, self.evidence.manifest, self.request, list(freezes))

    def test_exact_source_and_full_raw_inventory_pass_then_after_freeze_passes(self):
        result = self.run_gate()
        self.assertTrue(result["passed"])
        self.assertFalse(result["adapter_native_integration_claimed"])
        self.assertEqual(set(result["native_evidence"]["required_raw_reports"]), set(REQUIRED))
        self.assertFalse(verify_after(self.repo, result)["native_ci_coverage_claimed"])

    def test_missing_required_report_fails_even_with_consistent_archive(self):
        del self.evidence.files["fresh-reader/receipt.json"]
        self.build()
        with self.assertRaisesRegex(ValueError, "required raw report missing"):
            self.run_gate()

    def test_wrong_native_commit_or_packer_source_is_rejected(self):
        request = json.loads(self.request.read_bytes())
        request["tested_commit"] = "f" * 40
        self.request.write_bytes(canonical(request))
        with self.assertRaisesRegex(ValueError, "another tested commit"):
            self.run_gate()
        self.build()
        self.write(PACKER, b"# changed packer\n")
        with self.assertRaisesRegex(ValueError, "packer differs"):
            self.run_gate()

    def test_wrong_command_log_identity_is_rejected(self):
        manifest = self.evidence.build(receipt_change=lambda value: value["executions"][0].update(
            raw_output=identity(b"another command's output")))
        request = json.loads(self.request.read_bytes())
        request["verification_receipt"].update({key: manifest["receipt"][key] for key in ("bytes", "sha256")})
        self.request.write_bytes(canonical(request))
        with self.assertRaisesRegex(ValueError, "command log inventory"):
            self.run_gate()

    def test_wrong_tested_tree_is_rejected(self):
        self.evidence.tree = "c" * 40
        self.build()
        with self.assertRaisesRegex(ValueError, "tested tree mismatch"):
            self.run_gate()

    def test_later_adapter_document_is_frozen_without_claiming_native_coverage(self):
        self.write(ADAPTER + "README.md", b"later independent research documentation\n")
        self.commit()
        result = self.run_gate()
        self.assertIn(ADAPTER + "README.md", result["sources"]["adapter"]["files"])
        self.write(ADAPTER + "README.md", b"changed after preflight\n")
        with self.assertRaises(ValueError):
            verify_after(self.repo, result)

    def test_longrun_requires_its_own_source_freeze(self):
        worker = ADAPTER + "longrun/worker.py"
        self.write(worker, b"# independently tested longrun\n")
        freeze = ADAPTER + "evidence/longrun-01/FREEZE.json"
        self.write(freeze, canonical({"schema": "hepta.memory.adapter-longrun-freeze.v1",
            "source_files": {"/original/workspace/" + worker: identity((self.repo / worker).read_bytes())}}))
        self.commit()
        with self.assertRaisesRegex(ValueError, "separately retained FREEZE"):
            self.run_gate()
        result = self.run_gate([freeze])
        self.assertFalse(result["sources"]["adapter"]["source_freezes"][-1]["native_ci_coverage_claimed"])

    def test_cli_failure_writes_failed_gate_receipt(self):
        self.evidence.manifest.write_bytes(b'{"broken":true}')
        output = self.repo / "failed-preflight.json"
        result = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).with_name("finalize_preflight.py")),
            "--repo", str(self.repo), "--request", str(self.request), "--transport", str(self.evidence.manifest),
            "--output", str(output)], capture_output=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr.decode())
        self.assertFalse(json.loads(output.read_bytes())["passed"])


if __name__ == "__main__":
    unittest.main()
