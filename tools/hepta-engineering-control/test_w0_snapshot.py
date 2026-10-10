#!/usr/bin/env python3
"""Focused tests for the W0 source-preparation proposal."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import w0_snapshot as subject


class FakeReader:
    def __init__(self, files):
        self.files = files

    def read(self, path):
        return self.files[path]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def model():
    modules = [f"m{number:02d}" for number in range(40)]
    lane_members = {lane: [] for lane in subject.LANE_IDS}
    files, module_rows, guides, bindings = {}, [], [], []
    ready, ownership, details, profiles, dossier_profiles = [], [], [], [], {}
    for number, module in enumerate(modules):
        lane = subject.LANE_IDS[number % 7]
        lane_members[lane].append(module)
        root = f"src/{module}"
        guide_path, detail_path = f"guides/{module}.md", f"details/{module}.md"
        guide_raw, detail_raw = f"guide {module}\n".encode(), f"detail {module}\n".encode()
        files[guide_path], files[detail_path] = guide_raw, detail_raw
        module_rows.append({"id": module})
        guides.append({"module": module, "path": guide_path,
                       "sha256": sha(guide_raw), "bytes": len(guide_raw)})
        bindings.append({"module": module, "declaredRoots": [root]})
        ready.append({"module": module, "primaryLane": lane})
        ownership.append({"module": module,
                          "rootBindings": [{"path": root, "mode": "exclusive"}]})
        details.append({"module": module, "lane": lane, "path": detail_path,
                        "sha256": sha(detail_raw)})
        profiles.append({"module": module, "lane": subject.LANE_LETTERS[lane],
                         "guide": guide_path, "design": detail_path,
                         "declaredRoots": [root]})
        dossier_profiles[module] = ["profile", number]
    lanes = [{"id": lane, "owner": "owner", "deputy": "deputy",
              "modules": lane_members[lane], "dependsOn": [],
              "entryGate": ["formal"], "exitGate": ["formal"]}
             for lane in subject.LANE_IDS]
    documents = {
        "docs/modules/MODULES.json": {"modules": module_rows},
        "docs/modules/MODULE_DOCS.json": {"modules": guides},
        "docs/modules/SOURCE_BINDINGS.json": {"bindings": bindings},
        "docs/readiness/READINESS.json": {"implementationLanes": lanes,
                                            "moduleBindings": ready},
        "docs/delivery/PATH_OWNERSHIP.json": {"moduleNamespaces": ownership},
        "qualification/module-execution-dossiers/DETAILS.json": {"rows": details},
        "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json": {
            "modules": profiles},
        "qualification/module-execution-dossiers/MODULE_DOSSIERS.json": {
            "moduleProfiles": dossier_profiles},
    }
    return FakeReader(files), documents


def proposal():
    inputs = {path: {"path": path, "sha256": "0" * 64}
              for path in subject.INPUT_PATHS}
    value = {
        "schema": "hepta.w0-source-preparation-proposal.v1",
        "preEntrySourcePreparation": True, "formalW0Passed": False,
        "formalReceiptIssued": False,
        "base": {"commit": "1" * 40, "tree": "2" * 40, "orderedParents": []},
        "source": {"commit": "1" * 40, "tree": "2" * 40, "orderedParents": []},
        "canonicalDocuments": [], "canonicalInputs": inputs,
        "modules": [], "laneProposals": [],
        "freshness": {"workingTreeClean": True,
                      "workingTreeStatusSha256": sha(b"")},
        "authorityFlags": {flag: False for flag in subject.AUTHORITY_FLAGS},
    }
    value["snapshotDigest"] = subject.digest(value)
    return value


class W0SnapshotTests(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(subject.W0Error) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)

    def test_exact_seven_lane_and_forty_module_proposals(self):
        reader, documents = model()
        modules, lanes, shared = subject.module_and_lane_records(reader, documents)
        self.assertEqual((40, 7, False), (len(modules), len(lanes), shared))
        self.assertTrue(all(lane["proposalOnly"] for lane in lanes))
        self.assertTrue(all(not lane["authorityGranted"] for lane in lanes))

    def test_missing_and_duplicate_lanes_reject(self):
        for mutation in ("missing", "duplicate"):
            reader, documents = model()
            lanes = documents["docs/readiness/READINESS.json"]["implementationLanes"]
            if mutation == "missing":
                lanes.pop()
            else:
                lanes[-1] = copy.deepcopy(lanes[0])
            with self.subTest(mutation=mutation):
                self.assert_code("LANE_SET_INVALID", lambda: subject.module_and_lane_records(
                    reader, documents))

    def test_missing_and_duplicate_modules_reject(self):
        for mutation in ("missing", "duplicate"):
            reader, documents = model()
            rows = documents["docs/modules/MODULES.json"]["modules"]
            if mutation == "missing":
                rows.pop()
            else:
                rows[-1] = copy.deepcopy(rows[0])
            with self.subTest(mutation=mutation):
                self.assert_code("MODULE_SET_INVALID", lambda: subject.module_and_lane_records(
                    reader, documents))

    def test_guide_digest_drift_rejects(self):
        reader, documents = model()
        documents["docs/modules/MODULE_DOCS.json"]["modules"][0]["sha256"] = "0" * 64
        self.assert_code("GUIDE_DIGEST_MISMATCH", lambda: subject.module_and_lane_records(
            reader, documents))

    def test_exclusive_path_collision_rejects(self):
        reader, documents = model()
        collision = "src/m00/child"
        documents["docs/modules/SOURCE_BINDINGS.json"]["bindings"][1]["declaredRoots"] = [collision]
        documents["docs/delivery/PATH_OWNERSHIP.json"]["moduleNamespaces"][1]["rootBindings"] = [
            {"path": collision, "mode": "exclusive"}]
        documents["qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"][
            "modules"][1]["declaredRoots"] = [collision]
        self.assert_code("EXCLUSIVE_PATH_COLLISION", lambda: subject.module_and_lane_records(
            reader, documents))

    def test_contract_drift_precedes_dirty_observation(self):
        expected, actual = proposal(), proposal()
        actual["canonicalInputs"]["docs/contracts/CONTRACTS.json"]["sha256"] = "f" * 64
        actual["freshness"]["workingTreeClean"] = False
        self.assert_code("CONTRACT_DIGEST_DRIFT",
                         lambda: subject.compare_snapshots(expected, actual))

    def test_source_provenance_drift_rejects(self):
        expected, actual = proposal(), proposal()
        actual["source"]["commit"] = "3" * 40
        self.assert_code("SOURCE_PROVENANCE_DRIFT",
                         lambda: subject.compare_snapshots(expected, actual))

    def test_malformed_and_duplicate_key_snapshot_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            for raw in (b"{", b'{"a":1,"a":2}', b'{"a":NaN}'):
                path.write_bytes(raw)
                with self.subTest(raw=raw):
                    self.assert_code("SNAPSHOT_FILE_INVALID",
                                     lambda: subject.load_snapshot(path))

    def test_expected_maps_must_be_objects(self):
        for key in ("authorityFlags", "freshness"):
            expected, actual = proposal(), proposal()
            expected[key] = []
            expected["snapshotDigest"] = subject.digest(
                {name: value for name, value in expected.items()
                 if name != "snapshotDigest"})
            with self.subTest(key=key):
                self.assert_code("EXPECTED_SNAPSHOT_SHAPE_INVALID",
                                 lambda: subject.compare_snapshots(expected, actual))

    def test_declared_blob_size_blocks_read_before_git_show(self):
        reader = subject.SourceReader.__new__(subject.SourceReader)
        reader.root, reader.source, reader.total, reader.cache = Path("."), "0" * 40, 0, {}
        reader.files = {"large": {"kind": "blob", "mode": "100644",
                                  "gitBlob": "0" * 40,
                                  "bytes": subject.MAX_BYTES + 1}}
        self.assert_code("SOURCE_BUDGET_EXCEEDED", lambda: reader.read("large"))

    def test_short_snapshot_read_rejects_as_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(proposal()))
            with mock.patch.object(subject.os, "read", return_value=b""):
                self.assert_code("SNAPSHOT_FILE_CHANGED",
                                 lambda: subject.load_snapshot(path))

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
                         "FIFO and nonblocking open required")
    def test_regular_path_swapped_to_fifo_cannot_block_open(self):
        with tempfile.TemporaryDirectory() as directory:
            regular, fifo = Path(directory) / "regular", Path(directory) / "fifo"
            regular.write_text("{}")
            os.mkfifo(fifo)
            claimed = os.lstat(regular)
            real_open, seen = os.open, []

            def checked_open(path, flags):
                seen.append(flags)
                return real_open(path, flags)

            with mock.patch.object(subject.os, "lstat", return_value=claimed), \
                    mock.patch.object(subject.os, "open", side_effect=checked_open):
                self.assert_code("SNAPSHOT_FILE_CHANGED",
                                 lambda: subject.load_snapshot(fifo))
            self.assertTrue(seen[0] & os.O_NONBLOCK)

    def test_excessive_compare_nesting_rejects_with_fixed_code(self):
        expected, actual, nested = proposal(), proposal(), None
        for _ in range(66):
            nested = [nested]
        expected["nested"] = nested
        self.assert_code("EXPECTED_SNAPSHOT_SHAPE_INVALID",
                         lambda: subject.compare_snapshots(expected, actual))

    def test_nested_snapshot_cli_never_emits_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested.json"
            path.write_text("[" * 2000 + "0" + "]" * 2000)
            result = subprocess.run(
                [sys.executable, subject.__file__, "check", "--root", directory,
                 "--base", "0" * 40, "--source", "0" * 40, "--snapshot", str(path)],
                check=False, capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("W0_INPUT_REJECTED:SNAPSHOT_JSON_STRUCTURE_EXCEEDED", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
