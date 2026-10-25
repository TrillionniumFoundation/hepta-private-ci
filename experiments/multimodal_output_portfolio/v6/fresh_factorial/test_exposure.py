"""Fail-closed historical source inventory; all added observations are synthetic."""

import copy
import io as memory
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from . import census, exposure, io, published
from .test_support import plan, rewrite


def review_for(record, discovery):
    return {"schema": "hepta.ndu-fresh-factorial.exposure-review.v1", "census_canonical_sha256": io.digest(record),
        "all_available_prior_evidence_roots_reviewed": True, "unresolved_manifests": [], "reviewer": "synthetic-test-only",
        "reviewed_scope": "Synthetic local provenance fixture; this is not the actual source-exposure approval.",
        "root_discovery_evidence": {str(discovery): io.identity(discovery)}, "archive_resolutions": {},
        "opaque_suffix_resolutions": {}, "excluded_directory_resolutions": {},
        "published_study_coverage": {key: {"resolved": True, "reason": "Synthetic coverage-resolution fixture for a rejection test only.",
                                         "published_evidence": ["full002_protocol.json"]} for key in published.COVERAGE_ITEMS},
        "unknown_source_exposure_gaps": [], "source_freshness_scope": "audited_known_v6_sources_only",
        "missing_original_archive_not_recovered": True}


class SourceExposureTests(unittest.TestCase):
    def test_exact_published_records_reconstruct_known_sources(self):
        custody, required, union = published.published_exposures(plan())
        self.assertEqual((len(custody["files"]), len(required), len(union)), (20, 360, 488))
        self.assertTrue(required.issubset(union))

    def test_omitted_published_record_is_not_fixed_by_deleting_manifest_entry(self):
        for omit_manifest in (False, True):
            with self.subTest(omit_manifest=omit_manifest), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "registration"
                shutil.copytree(Path(__file__).parent / "registration", root)
                (root / "published" / "owner_calibration.json").unlink()
                if omit_manifest:
                    path = root / "published-manifest.json"
                    manifest = io.read_json(path)
                    manifest["files"] = [x for x in manifest["files"] if x["name"] != "owner_calibration.json"]
                    rewrite(path, manifest)
                with self.assertRaises(ValueError):
                    published.verify_published(plan(), root)

    def test_rehashed_published_payload_must_still_match_git_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "registration"
            shutil.copytree(Path(__file__).parent / "registration", root)
            changed = root / "published" / "owner_calibration.json"
            changed.write_bytes(b"{}\n")
            manifest_path = root / "published-manifest.json"
            manifest = io.read_json(manifest_path)
            for row in manifest["files"]:
                if row["name"] == changed.name:
                    row.update(io.identity(changed))
            rewrite(manifest_path, manifest)
            with self.assertRaises(ValueError):
                published.verify_published(plan(), root)

    def test_declared_bad_pixel_and_source_types_are_not_silently_zero_exposures(self):
        for value in (None, 1, True, "not-a-hash", [None, 123], {"group": [False]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exposure.exposed_pixels({"source_pixel_sha256": value})
        for value in (None, 5, "mnist:test:bad:" + "a" * 64, "mnist:test:5:broken"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exposure.exposed_pixels({"source_ids": [value]})
        with self.assertRaises(ValueError):
            exposure.parse_payload(b'{"source_ids": [], "source_ids": []}', ".json")

    def test_directory_symlink_and_walk_permission_error_block_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alias").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                census.inventory([root])
            (root / "alias").unlink()
            def failed_walk(base, followlinks, onerror):
                onerror(PermissionError("synthetic unreadable old root"))
                return iter(())
            with patch.object(census.os, "walk", side_effect=failed_walk), self.assertRaises(PermissionError):
                census.inventory([root])

    def test_archive_metadata_is_scanned_and_unsafe_members_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "old.tgz"
            pixel = "e" * 64
            with tarfile.open(archive, "w:gz") as stream:
                raw = io.canonical({"source_ids": ["mnist:test:4:" + pixel]})
                member = tarfile.TarInfo("old/cases.json")
                member.size = len(raw)
                stream.addfile(member, memory.BytesIO(raw))
                blob = tarfile.TarInfo("old/weights.pt")
                blob.size = 7
                stream.addfile(blob, memory.BytesIO(b"nonmodel"[:7]))
            record, pixels = census.scan_archive(archive, exposure.parse_payload)
            self.assertEqual(pixels, {pixel})
            self.assertEqual(len(record["members"]), 2)
            with tarfile.open(root / "unsafe.tar", "w") as stream:
                member = tarfile.TarInfo("../outside.json")
                member.size = 2
                stream.addfile(member, memory.BytesIO(b"{}"))
            with self.assertRaises(ValueError):
                census.scan_archive(root / "unsafe.tar", exposure.parse_payload)
            (root / "unsupported.tar.zst").write_bytes(b"synthetic")
            with self.assertRaises(ValueError):
                census.scan_archive(root / "unsupported.tar.zst", exposure.parse_payload)

    def test_removed_extra_exposure_or_new_manifest_blocks_freeze(self):
        for mutation in ("omitted_union", "changed", "new"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root, p = Path(tmp), plan()
                prior = root / "prior"
                prior.mkdir()
                discovery = prior / "discovery.json"
                io.write(discovery, {"scope": "synthetic bounded discovery record"})
                extra = prior / "additional.json"
                io.write(extra, {"source_ids": ["mnist:test:4:" + "f" * 64]})
                template = root / "template.json"
                io.write(template, p)
                source = {"git_commit": "synthetic-only", "files": {"synthetic": "bound"}}
                with patch.object(exposure, "published_source", return_value=source):
                    exposure.scan(template, [str(prior)], "synthetic-only", root / "census")
                    census_path = root / "census" / "exposure-census.json"
                    record = io.read_json(census_path)
                    if mutation == "omitted_union":
                        record["all_exposed_pixels"].remove("f" * 64)
                        record["all_exposed_pixel_count"] -= 1
                        rewrite(census_path, record)
                    review = review_for(record, discovery)
                    review_path = root / "review.json"
                    io.write(review_path, review)
                    if mutation == "changed":
                        extra.write_bytes(b"{}\n")
                    elif mutation == "new":
                        io.write(prior / "new.json", {"source_ids": ["mnist:test:5:" + "d" * 64]})
                    with self.assertRaises(ValueError):
                        exposure.freeze(template, census_path, review_path, "synthetic-only",
                                        str(root / "one-owner"), root / "frozen")

    def test_unknown_scope_cannot_be_attested_away_by_omitting_coverage_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "prior"
            prior.mkdir()
            discovery = prior / "discovery.json"
            io.write(discovery, {"scope": "synthetic bounded discovery"})
            template = root / "template.json"
            io.write(template, plan())
            with patch.object(exposure, "published_source", return_value={"files": {}, "git_commit": "synthetic-only"}):
                exposure.scan(template, [str(prior)], "synthetic-only", root / "census")
            record = io.read_json(root / "census" / "exposure-census.json")
            good = review_for(record, discovery)
            exposure.verify_review(record, good)
            for mutation in ("unknown", "missing", "unresolved", "no_discovery"):
                bad = copy.deepcopy(good)
                if mutation == "unknown":
                    bad["unknown_source_exposure_gaps"] = ["unreviewed local run"]
                elif mutation == "missing":
                    del bad["published_study_coverage"]["ci_smoke_and_full"]
                elif mutation == "unresolved":
                    bad["published_study_coverage"]["unlisted_local_or_ci_runs"]["resolved"] = False
                else:
                    bad["root_discovery_evidence"] = {}
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    exposure.verify_review(record, bad)

    def test_algorithm_closure_includes_all_non_test_execution_modules(self):
        directory = Path(__file__).parent
        actual = {p.name for p in directory.glob("*.py") if not p.name.startswith("test_")}
        self.assertEqual(actual, {name for name in io.SOURCE_FILES if name.endswith(".py")})


if __name__ == "__main__":
    unittest.main()
