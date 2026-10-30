"""Context-reconstructed synthetic provenance tests; no actual RAW access."""

import copy
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
from operational.parameter_field_recovery04 import durable_archive as archive
from operational.parameter_field_recovery06 import ancestry


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else ancestry.canonical(value))
    return archive.descriptor(path)


def tagged(value):
    if isinstance(value, dict):
        return ["dict", [[["str", key], tagged(item)] for key, item in sorted(value.items())]]
    return ["int", str(value)] if type(value) is int else ["str", value]


class Fixture:
    def __init__(self, base, fault=None):
        self.base = Path(base)
        self.old, self.ops = self.base / "fullstudy_execution04_durable_raw", self.base / "fullstudy_execution04_ops"
        self.source, self.fresh = self.base / "fullstudy_git", self.base / "fullstudy_execution06_durable_raw"
        protocol = write(self.source / "science/PROTOCOL.json", {"synthetic": True})
        self.protocol_sha = protocol["sha256"]
        kernel = write(self.source / "science/kernel.py", b"# synthetic source; never executed\n")
        original = write(self.source / "science/ORIGINAL_A_FREEZE.json", {
            "registered_commit": "c" * 40, "source_files": {"science/kernel.py": kernel["sha256"]}})
        self.parent_sha = original["sha256"]
        parent = {"path": original["path"], "sha256": self.parent_sha, "registered_commit": "c" * 40,
                  "source_root": str(self.source), "protocol_sha256": self.protocol_sha}
        profile = write(self.source / "operations/PROFILE.json", {"raw_root": str(self.old)})
        runtime = write(self.base / "runtime/IMPORT.json", {"synthetic": True})
        asset = write(self.base / "assets_original/fixture.bin", b"synthetic input identity")
        assets = {"pinned_files": {"fixture.bin": asset["sha256"]}, "original_archive_sha256": "d" * 64}
        restoration = write(self.base / "assets_original/RESTORATION.json", {
            "archive_sha256": assets["original_archive_sha256"], "all_pinned_bytes_verified": True})
        freeze = write(self.ops / "registrations/initial/A_SOURCE_FREEZE.json", {
            "execution_episode": ancestry.SOURCE_EPISODE, "source_git_root": str(self.source),
            "allowed_phases": ["A"], "attempt_id": "attempt02", "registered_commit": ancestry.SOURCE_COMMIT,
            "protocol_sha256": self.protocol_sha, "operational_amendment_sha256": profile["sha256"],
            "scientific_parent": parent, "source_files": {"science/kernel.py": kernel["sha256"]},
            "artifacts": {runtime["path"]: runtime["sha256"], profile["path"]: profile["sha256"]}})
        config = write(self.ops / "registrations/initial/PIPELINE_CONFIG.json", {
            "execution_episode": ancestry.SOURCE_EPISODE, "raw_root": str(self.old), "ops_root": str(self.ops),
            "source_root": str(self.source), "source_commit": ancestry.SOURCE_COMMIT,
            "descriptors": {"amendment": profile, "runtime_receipt": runtime}})
        self.expected = {"registered_commit": ancestry.SOURCE_COMMIT, "source_freeze_sha256": freeze["sha256"],
            "profile_sha256": profile["sha256"], "protocol_sha256": self.protocol_sha,
            "runtime_sha256": "f" * 64, "runtime_receipt_sha256": runtime["sha256"], "assets": assets}
        binding = {"study_id": ancestry.STUDY, "protocol_sha256": self.protocol_sha,
                   "source_freeze_sha256": freeze["sha256"], "runtime_sha256": "f" * 64}
        for index, (name, cursor) in enumerate(ancestry.stage_inventory().items()):
            data = b"synthetic closed artifact " + name.encode()
            if cursor is not None:
                schedule, kind, clock = cursor
                local = {**binding, "runtime_sha256": "0" * 64} if fault == "runtime" and index == 10 else binding
                header = ancestry.canonical({"arrays": [], "tree": tagged({"binding": local, "cursor": {
                    "seed": 17, "schedule_id": schedule, "path_kind": kind, "clock": clock,
                    "remaining_steps": 288 - clock, "total_steps": 288, "guard_grain": 48, "baseline_action": 2}})})
                data = ancestry.MAGIC + struct.pack(">Q", len(header)) + header
            write(self.old / "stage_A/seed-17" / name, data)
        science = write(self.old / "stage_A/seed-17/COMPLETE.json", {
            "complete": fault != "incomplete", "phase": "A", "seed": 29 if fault == "seed" else 17,
            "registered_commit": ancestry.SOURCE_COMMIT, "source_freeze_sha256": "0" * 64 if fault == "producer" else freeze["sha256"],
            "assets": assets, "path_count": 16, "costs": {"scheduled_gradient_microsteps": 39168}})
        operation = write(self.old / "operations/A-seed-17.COMPLETE.json", {
            "schema": "hepta.fullstudy.training-operation.2", "attempt_id": "attempt02", "complete": True,
            "phase": "A", "seed": 17, "execution_kind": "training", "registered_commit": ancestry.SOURCE_COMMIT,
            "source_freeze_sha256": freeze["sha256"], "operational_amendment_sha256": profile["sha256"],
            "scientific_protocol_sha256": self.protocol_sha, "entrypoint_protocol_sha256": self.protocol_sha,
            "post_execution_storage_check": True, "scientific_source_bytes_unchanged": True, "scientific_parent": parent,
            "scientific_complete": {**science, "path": "stage_A/seed-17/COMPLETE.json"}})
        controller = write(self.old / "controller/A-17.RESULT.json", {
            "complete": True, "exit_code": 0, "completion": {**operation, "path": "operations/A-seed-17.COMPLETE.json"}})
        paths = {"raw/" + str(path.relative_to(self.old)): path for path in archive.regular_tree(self.old)}
        paths["metadata/PIPELINE_CONFIG.json"] = Path(config["path"])
        total = sum(path.stat().st_size for path in paths.values())
        archive_binding = {"completed_jobs": ["A-17"], "execution_episode": ancestry.SOURCE_EPISODE,
                           "label": "A-17", "pipeline_config": config, "previous_ack": None, "sequence": 1}
        directory = self.ops / "durable/01_A-17"
        request_desc = archive.build_archive(directory, paths, archive_binding, payload_limit=total // 2 + 1)
        request = archive.read(request_desc["path"])
        assert len(request["items"]) == 5
        self.readback_root = self.base / "root_io/01_A-17"
        bound = write(self.readback_root / "BOUND_REQUEST.json", {"request": request_desc})
        items, retired = [], []
        for index, local in enumerate(request["items"]):
            remote = {"file_id": "file-" + str(index), "library_file_id": "lib-" + str(index),
                      "file_name": Path(local["path"]).name, "version": 0}
            readback = self.readback_root / "readback" / Path(local["path"]).name
            readback.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local["path"], readback)
            item = {"local": local, "remote_identity": remote, "readback_remote_identity": remote,
                    "upload_item_success": True, "remote_readback_performed": True, "readback": archive.descriptor(readback),
                    "library_file_id_xattr_verified": remote["library_file_id"]}
            for name in ("upload_receipt", "upload_wait4", "readback_receipt", "complete_transfer_receipt", "readback_helper_stdout", "readback_helper_wait4"):
                item[name] = write(self.readback_root / f"{index}-{name}.json", {"synthetic": True})
            items.append(item)
            if index < 2:
                info = readback.stat()
                retired.append({"duplicate": item["readback"], "retained_original": local, "remote_identity": remote,
                    "verified_remote_identity_xattr": remote["library_file_id"], "stat": {"size": info.st_size, "ino": info.st_ino}})
        ack = write(directory / "ACK.json", {"schema": "hepta.fullstudy.library-archive-ack.1", "status": "VERIFIED_REMOTE_READBACK",
            "unknown_upload_outcome": False, "binding": archive_binding, "request": request_desc, "items": items, "root_operational_binding": bound})
        ack_verified = write(directory / "ACK_VERIFIED.json", archive.verify_ack(ack["path"], request_desc))
        cleanup_plan = write(self.readback_root / "CLEANUP_PLAN.json", {
            "actual_ack": ack, "actual_ack_verified": ack_verified, "count": 2, "rows": retired})
        for row in retired:
            Path(row["duplicate"]["path"]).unlink()
        cleanup_result = write(self.readback_root / "CLEANUP_RESULT.json", {
            "plan": cleanup_plan, "count": 2, "all_duplicate_paths_absent": True, "all_originals_retained": True,
            "remote_items_changed": False, "historical_ack_reverification_requires_rematerializing_duplicate_bytes": True,
            "removed": [row["duplicate"] for row in retired]})
        entries = [entry for row in retired for entry in ({"intent": row["duplicate"], "stat": row["stat"]},
            {"unlinked": row["duplicate"], "immediately_absent": True})]
        journal = write(self.readback_root / "CLEANUP_JOURNAL.jsonl", b"".join((json.dumps(entry) + "\n").encode() for entry in entries))
        self.a = {"protocol": protocol, "profile": profile, "runtime": runtime, "asset_restoration": restoration,
            "source_freeze": freeze, "config": config, "scientific_complete": science, "operation_complete": operation,
            "controller_result": controller, "request": request_desc, "ack": ack, "ack_verified": ack_verified,
            "manifest": request["items"][2], "archive_verification": request["items"][3], "cleanup_plan": cleanup_plan,
            "cleanup_result": cleanup_result, "cleanup_journal": journal}
        self.pins = {"schema": ancestry.PIN_SCHEMA, "source_episode": ancestry.SOURCE_EPISODE, "target_episode": ancestry.TARGET_EPISODE,
            "old_raw": str(self.old), "old_ops": str(self.ops), "fresh_raw": str(self.fresh), "anchors": self.a, "expected": self.expected}
        self.pin_descriptor = write(self.base / "PINS.json", self.pins)

    def load(self):
        return ancestry.load_pins(self.pin_descriptor["path"], self.pin_descriptor["sha256"])

    def validate(self):
        return ancestry.validate_import(self.load(), self.old, self.ops)

    def fresh_registration(self):
        source = self.base / "fullstudy_recovery06_git"
        kernel = write(source / "science/kernel.py", (self.source / "science/kernel.py").read_bytes())
        profile = write(source / "PROFILE.json", {"raw_root": str(self.fresh)})
        freeze_value = archive.read(self.a["source_freeze"]["path"])
        freeze_value.update({"execution_episode": ancestry.TARGET_EPISODE, "registered_commit": "b" * 40,
            "source_git_root": str(source), "operational_amendment_sha256": profile["sha256"], "source_files": {"science/kernel.py": kernel["sha256"]}})
        freeze = write(self.base / "fullstudy_execution06_ops/A_SOURCE_FREEZE.json", freeze_value)
        return {"execution_episode": ancestry.TARGET_EPISODE, "raw_root": str(self.fresh), "source_root": str(source),
            "registered_commit": "b" * 40, "source_freeze": freeze, "profile": profile,
            "protocol_sha256": self.protocol_sha, "runtime_sha256": self.expected["runtime_sha256"]}


class AncestryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ancestry-synthetic-")
        self.addCleanup(self.temp.cleanup)

    def fixture(self, fault=None):
        value = Fixture(self.temp.name, fault)
        for name, replacement in (("FIXED_ANCHORS", {key: value.a[key]["sha256"] for key in ancestry.FIXED_ANCHORS}),
                ("PROTOCOL_SHA", value.protocol_sha), ("PARENT_SHA", value.parent_sha)):
            active = patch.object(ancestry, name, replacement)
            active.start()
            self.addCleanup(active.stop)
        return value

    def test_valid_import_preserves_original_bytes_and_seedwise_producers(self):
        value = self.fixture()
        before = {str(path): archive.descriptor(path) for path in archive.regular_tree(value.old)}
        descriptor = ancestry.materialize_import(value.validate(), value.fresh)
        receipt = archive.read(descriptor["path"])
        self.assertEqual((receipt["stage_files"], receipt["state_headers"], receipt["new_scheduled_gradient_microsteps"], receipt["scientific_cost_owner"]),
            (282, 64, 0, ancestry.SOURCE_EPISODE + ":A-17"))
        self.assertFalse((value.fresh / "controller").exists())
        self.assertEqual(before, {str(path): archive.descriptor(path) for path in archive.regular_tree(value.old)})
        mapping = ancestry.producer_map(descriptor, value.fresh_registration())
        self.assertEqual({k: (v["kind"], v["execution_episode"]) for k, v in mapping.items()}, {
            "17": ("imported", ancestry.SOURCE_EPISODE), "29": ("executed", ancestry.TARGET_EPISODE), "43": ("executed", ancestry.TARGET_EPISODE)})
        operation = archive.descriptor(value.fresh / "operations/A-seed-17.COMPLETE.json")
        self.assertEqual(ancestry.verify_producer(17, operation, mapping), mapping["17"])
        with self.assertRaises(ValueError):
            ancestry.verify_producer(29, operation, mapping)
        wrong = copy.deepcopy(mapping)
        wrong["17"]["profile"] = wrong["29"]["profile"]
        with self.assertRaises(ValueError):
            ancestry.verify_producer(17, operation, wrong)

    def test_tampered_stage_and_failed_job_are_rejected(self):
        value = self.fixture()
        path = value.old / "stage_A/seed-17/bank/field12-bank.npz"
        original = path.read_bytes()
        path.write_bytes(original + b"tamper")
        with self.assertRaises(ValueError):
            value.validate()
        path.write_bytes(original)
        write(value.old / "operations/A-seed-17.FAILED.json", {"complete": False})
        with self.assertRaises(ValueError):
            value.validate()
        self.assertFalse(value.fresh.exists())

    def test_wrong_closed_seal_producer_is_rejected_despite_matching_archive(self):
        with self.assertRaises(ValueError):
            self.fixture("producer").validate()

    def test_seed29_cannot_be_claimed_as_imported_a17(self):
        with self.assertRaises(ValueError):
            self.fixture("seed").validate()

    def test_incomplete_job_is_not_imported_even_with_verified_ack(self):
        with self.assertRaises(ValueError):
            self.fixture("incomplete").validate()

    def test_state_runtime_binding_is_verified_without_tensor_decoding(self):
        with self.assertRaises(ValueError):
            self.fixture("runtime").validate()

    def test_unregistered_missing_readback_is_rejected(self):
        value = self.fixture()
        (value.readback_root / "readback/MANIFEST.json").unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            value.validate()

    def test_original_archive_and_cleanup_journal_tampering_are_rejected(self):
        value = self.fixture()
        journal = Path(value.a["cleanup_journal"]["path"])
        old = journal.read_bytes()
        journal.write_bytes(old + b"{}\n")
        with self.assertRaises(ValueError):
            value.validate()
        journal.write_bytes(old)
        part = value.ops / "durable/01_A-17/part-0000.tar.gz"
        part.write_bytes(part.read_bytes() + b"tamper")
        with self.assertRaises(ValueError):
            value.validate()

    def test_source_changes_and_self_pinned_input_are_rejected(self):
        value = self.fixture()
        with self.assertRaises(ValueError):
            ancestry.load_pins(value.pin_descriptor["path"], "0" * 64)
        write(value.source / "science/kernel.py", b"changed source")
        with self.assertRaises(ValueError):
            value.validate()

    def test_existing_target_and_post_validation_changes_fail_before_writes(self):
        value = self.fixture()
        verified = value.validate()
        value.fresh.mkdir()
        with self.assertRaises(ValueError):
            ancestry.materialize_import(verified, value.fresh)
        self.assertEqual(list(value.fresh.iterdir()), [])
        value.fresh.rmdir()
        write(value.old / "stage_A/seed-17/bank/new.bin", b"unexpected")
        with self.assertRaises(ValueError):
            ancestry.materialize_import(verified, value.fresh)
        self.assertFalse(value.fresh.exists())

    def test_hardlink_failure_leaves_explicit_partial_import_and_blocks_retry(self):
        value = self.fixture()
        verified = value.validate()
        original_link, calls = os.link, []
        def interrupted_link(source, target, **kwargs):
            if str(target).endswith("bank/BANK.json"):
                raise OSError("synthetic target failure")
            calls.append((source, target))
            return original_link(source, target, **kwargs)
        with patch.object(ancestry.os, "link", interrupted_link), self.assertRaises(OSError):
            ancestry.materialize_import(verified, value.fresh, method="hardlink")
        self.assertTrue(calls)
        result = archive.read(value.fresh / "imports/execution04/A-17/IMPORT_FAILED.json")
        self.assertEqual((result["complete"], result["automatic_retry_safe"], result["partial_import_preserved"]), (False, False, True))
        with self.assertRaises(ValueError):
            ancestry.materialize_import(verified, value.fresh, method="hardlink")


if __name__ == "__main__":
    unittest.main()
