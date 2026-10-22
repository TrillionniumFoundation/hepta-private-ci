"""Real archive safety tests and dependency-isolated replay routing, not model quality."""

import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import multimodal_evidence as evidence


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def record(value):
    return {"bytes": len(value), "sha256": sha(value)}


class ArchiveFixture:
    def __init__(self, base, entries=None, *, inventory=None, compressed=None):
        self.source, self.target = base / "source", base / "restored"
        self.source.mkdir(parents=True)
        self.entries = entries or [("bank/features.bin", b"frozen features", tarfile.REGTYPE),
                                   ("results/report.json", b'{"retained":true}', tarfile.REGTYPE)]
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, payload, kind in self.entries:
                item = tarfile.TarInfo(name)
                item.type, item.mtime = kind, 0
                item.size = len(payload) if kind == tarfile.REGTYPE else 0
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    item.linkname = "bank/features.bin"
                archive.addfile(item, io.BytesIO(payload) if item.size else None)
        self.tar_bytes = stream.getvalue()
        self.compressed = gzip.compress(self.tar_bytes, mtime=0) if compressed is None else compressed
        middle = max(1, len(self.compressed) // 2)
        parts = []
        for index, payload in enumerate((self.compressed[:middle], self.compressed[middle:]), 1):
            name = f"evidence.tar.gz.part-{index:02d}"
            (self.source / name).write_bytes(payload)
            parts.append({"name": name, **record(payload)})
        self.manifest = {"schema": "hepta.multimodal-evidence-archive.v1", "authority": "DENY_ALL",
            "production_activation_allowed": False, "source_sha": "b" * 40,
            "archive": {"format": "tar+gzip", **record(self.compressed), "parts": parts},
            "members": inventory if inventory is not None else {
                name: record(payload) for name, payload, _ in self.entries}}
        self.pin()

    def pin(self):
        raw = canonical(self.manifest)
        (self.source / "archive-manifest.json").write_bytes(raw)
        self.manifest_sha = sha(raw)

    def restore(self):
        return evidence.restore_evidence(self.source,
            expected_manifest_sha256=self.manifest_sha, output=self.target)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def rejected(self, fixture, exception=ValueError):
        with self.assertRaises(exception):
            fixture.restore()
        self.assertFalse(fixture.target.exists())
        self.assertFalse(list(fixture.target.parent.glob(".hepta-mm-restore-*")))

    def test_split_archive_restores_exact_bytes_and_private_files(self):
        fixture = ArchiveFixture(self.root)
        self.assertEqual(fixture.restore(), fixture.manifest)
        for name, payload, _ in fixture.entries:
            path = fixture.target / name
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(list(self.root.glob(".hepta-mm-restore-*")))

    def test_external_manifest_pin_cannot_be_replaced_by_internal_hashes(self):
        fixture = ArchiveFixture(self.root)
        fixture.manifest["source_sha"] = "a" * 40
        (fixture.source / "archive-manifest.json").write_bytes(canonical(fixture.manifest))
        self.rejected(fixture)

    def test_rehashed_archive_still_requires_research_schema_and_no_authority(self):
        for field, value in (("schema", "other"), ("authority", "ALLOW"),
                             ("production_activation_allowed", True)):
            with self.subTest(field=field):
                fixture = ArchiveFixture(self.root / field)
                fixture.manifest[field] = value
                fixture.pin()
                self.rejected(fixture)

    def test_part_corruption_length_and_missing_file(self):
        for change in ("same-length", "shorter", "missing"):
            with self.subTest(change=change):
                fixture = ArchiveFixture(self.root / change)
                path = fixture.source / fixture.manifest["archive"]["parts"][0]["name"]
                raw = path.read_bytes()
                if change == "missing":
                    path.unlink()
                else:
                    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:] if change == "same-length" else raw[:-1])
                self.rejected(fixture)

    def test_assembly_checks_order_and_digest_even_when_each_part_is_valid(self):
        for change in ("reordered", "duplicate", "wrong-archive-hash"):
            with self.subTest(change=change):
                fixture = ArchiveFixture(self.root / change)
                archive = fixture.manifest["archive"]
                if change == "reordered":
                    archive["parts"].reverse()
                elif change == "duplicate":
                    archive["parts"][1] = copy.deepcopy(archive["parts"][0])
                else:
                    archive["sha256"] = "0" * 64
                fixture.pin()
                self.rejected(fixture)

    def test_member_digest_size_and_complete_inventory_are_enforced(self):
        for change in ("digest", "size", "missing-indexed", "unindexed"):
            with self.subTest(change=change):
                fixture = ArchiveFixture(self.root / change)
                members = fixture.manifest["members"]
                name = fixture.entries[1][0]
                if change == "digest":
                    members[name]["sha256"] = "0" * 64
                elif change == "size":
                    members[name]["bytes"] += 1
                elif change == "missing-indexed":
                    members["never-in-tar.bin"] = record(b"absent")
                else:
                    del members[name]
                fixture.pin()
                self.rejected(fixture)

    def test_duplicate_tar_entry_rejected_after_partial_extraction(self):
        fixture = ArchiveFixture(self.root, [("a", b"first", tarfile.REGTYPE)] * 2)
        self.rejected(fixture)

    def test_unsafe_tar_names_never_escape_and_partial_output_is_removed(self):
        names = ("../escape", "/escape", "C:/escape", "x:stream", "a\\b", "a//b", "a/./b", ".")
        for index, name in enumerate(names):
            with self.subTest(name=name):
                fixture = ArchiveFixture(self.root / str(index), [
                    ("first", b"valid", tarfile.REGTYPE), (name, b"bad", tarfile.REGTYPE)],
                    inventory={"first": record(b"valid")})
                self.rejected(fixture)
                self.assertFalse((self.root / "escape").exists())

    def test_inventory_and_part_paths_must_be_canonical_local_names(self):
        for index, name in enumerate((".", "../outside", "x:stream", "C:/file", "a\\b", "a//b", "a\x00b", "a\nb")):
            for field in ("member", "part"):
                with self.subTest(name=name, field=field):
                    fixture = ArchiveFixture(self.root / f"{index}-{field}")
                    if field == "member":
                        fixture.manifest["members"][name] = record(b"bad")
                    else:
                        fixture.manifest["archive"]["parts"][0]["name"] = name
                    fixture.pin()
                    self.rejected(fixture)

    def test_tar_links_directories_and_devices_cannot_be_extracted(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                fixture = ArchiveFixture(self.root / kind.decode(), [
                    ("bank/features.bin", b"good", tarfile.REGTYPE), ("second", b"bad", kind)])
                self.rejected(fixture)

    def test_linked_source_manifest_part_parent_and_dangling_output_are_rejected(self):
        for kind in ("source", "manifest", "part", "parent", "output"):
            with self.subTest(kind=kind):
                fixture = ArchiveFixture(self.root / kind)
                if kind == "parent":
                    alias = self.root / "parent-alias"
                    alias.symlink_to(fixture.target.parent, target_is_directory=True)
                    fixture.target = alias / "restored"
                elif kind == "output":
                    fixture.target.symlink_to(self.root / "nonexistent")
                else:
                    path = fixture.source if kind == "source" else fixture.source / (
                        "archive-manifest.json" if kind == "manifest" else fixture.manifest["archive"]["parts"][0]["name"])
                    original = path.with_name(path.name + ".original")
                    path.rename(original)
                    path.symlink_to(original, target_is_directory=kind == "source")
                self.rejected(fixture)

    def test_existing_output_is_not_overwritten(self):
        fixture = ArchiveFixture(self.root)
        fixture.target.mkdir()
        sentinel = fixture.target / "retain"
        sentinel.write_bytes(b"user data")
        with self.assertRaises(ValueError):
            fixture.restore()
        self.assertEqual(sentinel.read_bytes(), b"user data")

    def test_compressed_and_expanded_budgets_apply_to_actual_bytes(self):
        for kind in ("compressed-header", "compressed-sum", "expanded-inventory", "expanded-stream"):
            with self.subTest(kind=kind):
                fixture = ArchiveFixture(self.root / kind)
                if kind.startswith("compressed"):
                    limit = len(fixture.compressed) - 1
                    if kind == "compressed-sum":
                        fixture.manifest["archive"]["bytes"] = limit
                        fixture.pin()
                    attribute = "MAX_COMPRESSED"
                else:
                    attribute = "MAX_EXPANDED"
                    limit = len(fixture.tar_bytes) - 1
                    if kind == "expanded-inventory":
                        limit = 100
                        for item in fixture.manifest["members"].values():
                            item["bytes"] = 60
                        fixture.pin()
                with patch.object(evidence, attribute, limit):
                    self.rejected(fixture)

    def test_per_part_metadata_manifest_size_and_inventory_count_budgets(self):
        for kind in ("part-size", "part-bool", "bad-hash", "parts-count", "members-count", "manifest-size"):
            with self.subTest(kind=kind):
                fixture = ArchiveFixture(self.root / kind)
                part = fixture.manifest["archive"]["parts"][0]
                if kind == "part-size":
                    part["bytes"] = 512001
                elif kind == "part-bool":
                    part["bytes"] = True
                elif kind == "bad-hash":
                    part["sha256"] = "z" * 64
                elif kind == "parts-count":
                    fixture.manifest["archive"]["parts"] = [part] * 65
                elif kind == "members-count":
                    fixture.manifest["members"] = {str(i): record(b"x") for i in range(1025)}
                fixture.pin()
                if kind == "manifest-size":
                    raw = b" " * 512001
                    (fixture.source / "archive-manifest.json").write_bytes(raw)
                    fixture.manifest_sha = sha(raw)
                self.rejected(fixture)

    def test_transport_errors_and_file_directory_collision_leave_no_partial_output(self):
        for kind in ("gzip-truncated", "invalid-tar", "path-collision"):
            with self.subTest(kind=kind):
                entries, compressed = None, None
                if kind == "gzip-truncated":
                    compressed = gzip.compress(b"some data", mtime=0)[:-5]
                elif kind == "invalid-tar":
                    compressed = gzip.compress(b"not a tar", mtime=0)
                else:
                    entries = [("a", b"file", tarfile.REGTYPE), ("a/b", b"nested", tarfile.REGTYPE)]
                fixture = ArchiveFixture(self.root / kind, entries, compressed=compressed)
                self.rejected(fixture, (ValueError, OSError, EOFError, tarfile.TarError))


class ReplayFixture:
    """Only route and integrity contracts are faked; all metadata files are real."""
    arms = ("text_only", "image_only", "text_image")
    modes = ("linear", "gated")
    interventions = ("shuffled_image", "missing_text", "missing_image")

    def __init__(self, root):
        self.root, self.calls, self.stored = root, [], {}
        self.rows = [{"row_id": f"r{i}", "label": i % 2} for i in range(4)]
        (root / "cohorts").mkdir()
        (root / "cohorts/test.jsonl").write_text("\n".join(json.dumps(row) for row in self.rows))
        (root / "results").mkdir()
        self.report = {"schema": "hepta.multimodal-research-report.v1", "engineering_status": "COMPLETE",
            "authority": "DENY_ALL", "production_activation_allowed": False, "quality_qualified": False,
            "data_manifest_sha256": "d" * 64, "bank_manifest_sha256": "b" * 64,
            "head_artifacts": {}, "ledgers": {}}
        self.report["plan"] = self.make_plan(data_sha256="d" * 64, bank_sha256="b" * 64, threads=2)
        self.report["plan_sha256"] = sha(canonical(self.report["plan"]))
        for arm in self.arms:
            for mode in self.modes:
                key = f"{arm}-{mode}"
                self.report["head_artifacts"][key] = {"directory": key + "-head", "manifest_sha256": sha(key.encode())}
                cases = [(key, "test", "paired", None, False),
                         (key + "-minority", "minority_test", "paired", [0, 2], False)]
                if arm == "text_image":
                    cases += [(key + "-" + item, "test", item, None, False) for item in self.interventions]
                    cases.append((key + "-shuffled_relabelled", "test", "shuffled_relabelled", None, True))
                for name, split, intervention, indices, relabel in cases:
                    directory = name + "-test" if name == key else name
                    path = root / "results" / directory
                    path.mkdir()
                    metadata = {"arm": key, "split": split, "intervention": intervention}
                    raw = canonical({"metadata": metadata})
                    (path / "manifest.json").write_bytes(raw)
                    feature_case = "shuffled_image" if relabel else intervention
                    ledger = self.ledger(key, arm, feature_case, self.rows, metadata, indices, relabel)
                    self.stored[directory] = ledger
                    self.report["ledgers"][name] = {"directory": directory, "manifest_sha256": sha(raw),
                        "ledger_sha256": ledger.ledger_sha256, "metrics": ledger.metrics()}
        self.modules = {
            "torch": SimpleNamespace(set_num_threads=lambda n: self.calls.append(("threads", n))),
            "cell_head_training": SimpleNamespace(load_head_artifact=self.load_head),
            "multimodal_features": SimpleNamespace(ARMS=self.arms, load_bank=self.load_bank, pair_features=self.pair),
            "multimodal_research": SimpleNamespace(MODES=self.modes, INTERVENTIONS=self.interventions,
                make_plan=self.make_plan, minority_indices=self.minority, make_ledger=self.make_ledger),
            "prediction_ledger": SimpleNamespace(canonical=canonical, sha=sha, load_prediction_ledger=self.load_ledger)}
        self.save()

    def make_plan(self, *, data_sha256, bank_sha256, threads):
        return {"schema": "execution-fixture-only", "data_manifest_sha256": data_sha256,
            "bank_manifest_sha256": bank_sha256, "threads": threads, "arms": list(self.arms),
            "modes": list(self.modes), "interventions": list(self.interventions),
            "code_file_sha256": {"multimodal_research.py": sha(Path(evidence.__file__).with_name("multimodal_research.py").read_bytes())}}

    def save(self):
        (self.root / "results/report.json").write_bytes(canonical(self.report))

    def load_bank(self, path, **kwargs):
        assert path == self.root / "bank"
        assert kwargs == {"expected_manifest_sha256": "b" * 64, "expected_data_sha256": "d" * 64}
        self.calls.append(("bank",))
        return "bank", "features"

    def pair(self, rows, bank, features, *, arm, intervention="paired"):
        assert rows == self.rows and (bank, features) == ("bank", "features")
        self.calls.append(("pair", arm, intervention))
        return SimpleNamespace(arm=arm, intervention=intervention, identity="shared-frozen-identity")

    def minority(self, rows, plan):
        assert rows == self.rows and plan == self.report["plan"]
        return [0, 2]

    def load_head(self, path, **kwargs):
        key = path.name.removesuffix("-head")
        assert path.parent == self.root / "results"
        assert kwargs == {"expected_manifest_sha256": sha(key.encode()), "expected_identity": "shared-frozen-identity"}
        self.calls.append(("head", key))
        return SimpleNamespace(key=key)

    def ledger(self, key, arm, feature_case, rows, metadata, indices, relabel):
        selected = rows if indices is None else [rows[index] for index in indices]
        labels = [1 - row["label"] if relabel else row["label"] for row in selected]
        identity = {"head": key, "bundle_arm": arm, "feature_case": feature_case, **metadata}
        digest = sha(canonical({"identity": identity, "rows": [row["row_id"] for row in selected], "labels": labels}))
        metrics = {"rows": len(selected), "positives": sum(labels)}
        return SimpleNamespace(identity=identity, ledger_sha256=digest, metrics=lambda: metrics)

    def make_ledger(self, head, bundle, rows, plan, *, arm, split, intervention, indices, relabel):
        assert plan == self.report["plan"]
        self.calls.append(("replay", head.key, intervention, indices, relabel))
        return self.ledger(head.key, bundle.arm, bundle.intervention, rows,
            {"arm": arm, "split": split, "intervention": intervention}, indices, relabel)

    def load_ledger(self, path, *, expected_manifest_sha256, expected_identity):
        assert path.parent == self.root / "results"
        assert sha((path / "manifest.json").read_bytes()) == expected_manifest_sha256
        stored = self.stored[path.name]
        assert stored.identity == expected_identity
        self.calls.append(("stored", path.name))
        return stored

    def replay(self):
        with patch.dict(sys.modules, self.modules):
            return evidence.replay_heads(self.root)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = ReplayFixture(Path(temporary.name))

    def test_complete_replay_routes_six_heads_and_twenty_distinct_ledgers(self):
        fixture = self.fixture
        before = copy.deepcopy(fixture.rows)
        result = fixture.replay()
        self.assertEqual((result["head_count"], result["replayed_ledgers"]), (6, 20))
        self.assertTrue(result["predictions_match_exactly"])
        self.assertFalse(result["original_image_encoding_repeated"])
        self.assertFalse(result["quality_qualified"])
        self.assertFalse(result["production_activation_allowed"])
        self.assertEqual(result["authority"], "DENY_ALL")
        self.assertEqual(sum(call[0] == "head" for call in fixture.calls), 6)
        self.assertEqual(len({call[1] for call in fixture.calls if call[0] == "stored"}), 20)
        replay = [call for call in fixture.calls if call[0] == "replay"]
        self.assertEqual(sum(call[3] == [0, 2] for call in replay), 6)
        self.assertEqual(sum(call[4] for call in replay), 2)
        self.assertEqual(fixture.calls[0], ("threads", 2))
        self.assertEqual(fixture.rows, before)

    def test_report_and_plan_drift_fail_before_any_artifact_load(self):
        fixture = self.fixture
        original = copy.deepcopy(fixture.report)
        for field, value in (("schema", "other"), ("engineering_status", "PARTIAL"),
                ("authority", "ALLOW"), ("production_activation_allowed", True), ("plan_sha256", "0" * 64),
                ("threads", True), ("threads", 0), ("threads", 9), ("arms", []), ("modes", []),
                ("interventions", []), ("code_file_sha256", {})):
            with self.subTest(field=field, value=value):
                fixture.report = copy.deepcopy(original)
                if field in fixture.report["plan"]:
                    fixture.report["plan"][field] = value
                    fixture.report["plan_sha256"] = sha(canonical(fixture.report["plan"]))
                else:
                    fixture.report[field] = value
                fixture.save()
                with self.assertRaises(ValueError):
                    fixture.replay()
                self.assertEqual(fixture.calls, [])

    def test_incomplete_extra_or_escaping_artifact_inventory_fails_before_load(self):
        fixture = self.fixture
        original = copy.deepcopy(fixture.report)
        for category in ("head_artifacts", "ledgers"):
            for change in ("empty", "missing", "extra", "parent", "absolute", "alias"):
                with self.subTest(category=category, change=change):
                    fixture.report = copy.deepcopy(original)
                    records = fixture.report[category]
                    key = next(iter(records))
                    if change == "empty":
                        records.clear()
                    elif change == "missing":
                        del records[key]
                    elif change == "extra":
                        records["unregistered"] = copy.deepcopy(records[key])
                    else:
                        records[key]["directory"] = {"parent": "../escaped", "absolute": "/escaped", "alias": "another-head"}[change]
                    fixture.save()
                    with self.assertRaises(ValueError):
                        fixture.replay()
                    self.assertEqual(fixture.calls, [])

    def test_each_retained_prediction_digest_and_metrics_is_checked(self):
        fixture = self.fixture
        key = "text_image-gated-shuffled_relabelled"
        original = copy.deepcopy(fixture.report)
        stored = fixture.stored[key]
        for change in ("stored-hash", "reported-hash", "reported-metrics"):
            with self.subTest(change=change):
                fixture.report = copy.deepcopy(original)
                fixture.stored[key] = stored
                if change == "stored-hash":
                    fixture.stored[key] = SimpleNamespace(identity=stored.identity, ledger_sha256="0" * 64)
                elif change == "reported-hash":
                    fixture.report["ledgers"][key]["ledger_sha256"] = "0" * 64
                else:
                    fixture.report["ledgers"][key]["metrics"]["positives"] += 1
                fixture.save()
                with self.assertRaisesRegex(ValueError, "replayed predictions differ"):
                    fixture.replay()


if __name__ == "__main__":
    unittest.main()
