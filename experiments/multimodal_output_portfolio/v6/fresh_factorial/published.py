"""Exact published v6 records are mandatory even when old model archives are lost."""

import hashlib
from pathlib import Path

from .io import digest, identity, read_json, require_identity


REQUIRED_PUBLISHED = {
    "base_protocol.json", "conditioned_protocol.json", "full001_protocol.json", "full002_protocol.json",
    "replay001_verification.json", "competence001_summary.json", "command_film001_specification.json",
    "command_film001_summary.json", "neuron_calibration_spec.json", "owner_calibration.json",
    "owner_paired.json", "owner_terminal.json", "owner_trained_replay.json", "owner_plasticity.json",
    "owner_README.md", "run_recipe.py", "replay_recipe.py", "ndu_v6_workflow.yml",
    "ndu_recursion_workflow.yml", "results_manifest.json",
}
COVERAGE_ITEMS = {
    "full001", "full002", "replay001", "competence_and_command_film", "neuron_calibration",
    "terminal_paired_trained_owners", "ci_smoke_and_full", "unlisted_local_or_ci_runs",
}


def verify_published(plan, root=None):
    root = Path(root) if root else Path(__file__).parent / "registration"
    manifest = read_json(root / "published-manifest.json")
    records = manifest["files"]
    if (manifest["schema"] != "hepta.ndu-fresh.published-v6-exposure.v1"
            or manifest["commit"] != plan["original_evidence_commit"]
            or manifest["repository"] != "TrillionniumFoundation/hepta-private-ci"
            or len(records) != len(REQUIRED_PUBLISHED) or {r["name"] for r in records} != REQUIRED_PUBLISHED):
        raise ValueError("complete exact published-v6 exposure evidence is required")
    actual = {str(p.relative_to(root / "published")) for p in (root / "published").rglob("*") if p.is_file()}
    if actual != REQUIRED_PUBLISHED:
        raise ValueError("published evidence required set has omissions or unregistered additions")
    result = {}
    for record in records:
        path = root / "published" / record["name"]
        require_identity(path, record)
        payload = path.read_bytes()
        if hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest() != record["sha"]:
            raise ValueError("published evidence differs from exact committed Git blob")
        result[record["name"]] = identity(path)
    return {"commit": manifest["commit"], "manifest": identity(root / "published-manifest.json"), "files": result}


def published_exposures(plan):
    from .exposure import exposed_pixels, parse_payload
    root = Path(__file__).parent / "registration" / "published"
    custody = verify_published(plan)
    old = read_json(root / "full001_protocol.json")
    recent = read_json(root / "full002_protocol.json")
    old_pixels = exposed_pixels(old["cases"])
    new_pixels = exposed_pixels(recent["cases"])
    required = exposed_pixels(recent)
    if (digest(recent) != plan["prior_protocol_canonical_sha256"] or len(old_pixels) != 180
            or len(new_pixels) != 180 or old_pixels & new_pixels or required != old_pixels | new_pixels
            or len(required) != plan["required_prior_pixel_count"]):
        raise ValueError("original full-001/full-002 360-source exclusion cannot be reconstructed exactly")
    pixels = set(required)
    for name in sorted(REQUIRED_PUBLISHED):
        pixels.update(parse_payload((root / name).read_bytes(), Path(name).suffix))
    return custody, required, pixels


def verify_scope_review(review, custody):
    coverage = review.get("published_study_coverage", {})
    if set(coverage) != COVERAGE_ITEMS:
        raise ValueError("every known published full/replay/probe/owner/CI exposure requires scope review")
    for key, record in coverage.items():
        if (record.get("resolved") is not True or len(record.get("reason", "")) < 30
                or not record.get("published_evidence")
                or not set(record["published_evidence"]).issubset(custody["files"])):
            raise ValueError("unresolved source exposure coverage: " + key)
    if (review.get("unknown_source_exposure_gaps") != []
            or review.get("source_freshness_scope") != "audited_known_v6_sources_only"
            or review.get("missing_original_archive_not_recovered") is not True):
        raise ValueError("unknown source gaps or a false historical recovery claim block a fresh confirmatory cohort")
