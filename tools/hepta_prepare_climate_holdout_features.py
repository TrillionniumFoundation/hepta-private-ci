#!/usr/bin/env python3
"""Root custody: freeze all eligible Climate components before reading labels.

This entry does not open gold, keys or CAS, issue a scope, or select a labeled
subset. The Rust custody importer subsequently applies the fixed evidence
label mapping to every evidence in this complete feature-only cut.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import types

PREVIEW = Path(
    "/opt/hepta-private-ci/acceptance-artifacts/climate-fever-component-preview-v2-20261002/climate-fever-fixed-custody-component-preview-v2.py"
)
PREVIEW_SHA = "8c5322d863be6c1a184ebb23b7764ad2881120ca80f9dd46ccb8f408c7f8e0ed"
COMPARISON = Path(
    "/opt/hepta-private-ci/acceptance-artifacts/climate-fever-old-feature-comparison-v2-20261002/climate-fever-old-private-feature-comparison-v2.py"
)
COMPARISON_SHA = "4ae450750faebb7b9ed74423683eb17cfecfa7834f9f418c329c7969f95fe96e"
OUTPUT = Path(
    "/var/lib/hepta/fixed-holdout-source-banks/climate-fever-03de61617b10a5c1935f8e08bb0e8ac1ee775356/feature-cut-v1.json"
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_fixed(path, pin):
    # Bootstrap the same protected-file boundary before executing a pinned
    # previously reviewed program. No Python site packages are needed (-I -B -S).
    for parent in [path.parent, *path.parent.parents]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("fixed program ancestor")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or before.st_size > 65536
        ):
            raise RuntimeError("fixed protected program")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            program = handle.read(65537)
        after = os.fstat(fd)
        if any(
            getattr(before, field) != getattr(after, field)
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise RuntimeError("fixed program changed")
        if len(program) > 65536 or sha(program) != pin:
            raise RuntimeError("fixed program pin")
    finally:
        os.close(fd)
    module = types.ModuleType("fixed_" + pin)
    exec(compile(program, str(path), "exec"), module.__dict__)
    return module


def eligible_components(raw, earlier, preview):
    """All features, including neutral evidence, participate before label use."""
    nodes = []
    ids = set()
    for line in raw.splitlines():
        row = json.loads(line, object_pairs_hook=preview.unique_keys)
        if set(row) != {"claim_id", "claim", "claim_label", "evidences"}:
            raise RuntimeError("official claim shape")
        claim_id = preview.text(row["claim_id"])
        if claim_id in ids:
            raise RuntimeError("duplicate source claim")
        ids.add(claim_id)
        evidences = row["evidences"]
        if not isinstance(evidences, list) or len(evidences) != 5:
            raise RuntimeError("complete evidence inventory")
        hashes = []
        articles = []
        for evidence in evidences:
            if set(evidence) != {
                "evidence_id",
                "evidence_label",
                "article",
                "evidence",
                "entropy",
                "votes",
            }:
                raise RuntimeError("official evidence shape")
            preview.text(evidence["evidence_id"])
            hashes.append(preview.normalized_hash(preview.text(evidence["evidence"])))
            articles.append(preview.article_hash(preview.text(evidence["article"])))
        nodes.append(
            (
                claim_id,
                preview.normalized_hash(preview.text(row["claim"])),
                hashes,
                articles,
            )
        )
    if (
        not preview.PUBLIC_EXAMPLE_CLAIM_IDS <= ids
        or len(nodes) > 16384
        or len(earlier) > 24000
    ):
        raise RuntimeError("complete bounded feature inventory")
    count = len(nodes)
    nodes.extend(
        (None, claim, evidences, articles) for claim, evidences, articles in earlier
    )
    parent = list(range(len(nodes)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen = {}
    for index, (_, claim, evidences, articles) in enumerate(nodes):
        keys = [("claim", claim)] + [("evidence", value) for value in evidences]
        keys += [("article", value) for value in articles]
        for key in keys:
            if key in seen:
                first, second = find(index), find(seen[key])
                parent[max(first, second)] = min(first, second)
            else:
                seen[key] = index
    groups = {}
    for index in range(len(nodes)):
        groups.setdefault(find(index), []).append(index)
    eligible = []
    for members in groups.values():
        if any(index >= count for index in members) or any(
            nodes[index][0] in preview.PUBLIC_EXAMPLE_CLAIM_IDS for index in members
        ):
            continue
        eligible.append(sorted(nodes[index][0] for index in members))
    eligible.sort()
    # Independently reconcile this manifest projection with the already frozen
    # actual feature-only preview, not with any label or desired sample count.
    reference = preview.preview(raw, earlier)
    if (
        len(eligible) != reference["candidate_disjoint_components"]
        or sum(map(len, eligible)) != reference["candidate_disjoint_claims"]
    ):
        raise RuntimeError("original feature graph projection differs")
    return eligible, reference


def main():
    preview = load_fixed(PREVIEW, PREVIEW_SHA)
    comparison = load_fixed(COMPARISON, COMPARISON_SHA)
    preview.require_boundary()
    original = [
        comparison.read_protected(path)
        for path in (
            comparison.CONFIG72,
            comparison.WITNESS72,
            comparison.REQUEST99,
            comparison.MASKED72,
            comparison.SOURCE99,
        )
    ]
    pins = comparison.historical_pins(*original)
    masked = json.loads(original[3], object_pairs_hook=preview.unique_keys)
    complete = [
        json.loads(line, object_pairs_hook=preview.unique_keys)
        for line in original[4].splitlines()
    ]
    if not isinstance(masked, list) or len(masked) != 72:
        raise RuntimeError("original complete masked feature count")
    earlier = comparison.features(masked, preview) + comparison.features(
        complete, preview
    )
    health = [
        preview.source(preview.HEALTH / ("healthver_" + split + ".csv"), pin, True)
        for split, pin in preview.HEALTH_PINS.items()
    ]
    earlier += preview.public_health_features(health)
    earlier += preview.public_footprint_features(
        preview.source(preview.FOOTPRINT, preview.FOOTPRINT_SHA, True)
    )
    raw = preview.source(preview.CLIMATE, preview.CLIMATE_SHA, True)
    components, reference = eligible_components(raw, earlier, preview)
    own_program = comparison.read_protected(Path(__file__), 65536, False)
    manifest = dict(
        schema="hepta.climate-fever.feature-cut.v1",
        source_digest=preview.CLIMATE_SHA,
        adapter_program_digest=sha(own_program),
        preview_program_digest=PREVIEW_SHA,
        comparison_program_digest=COMPARISON_SHA,
        known_feature_inventory_digest=sha(canonical(earlier)),
        original_source_pins=pins,
        known_feature_records=len(earlier),
        public_health_source_pins=preview.HEALTH_PINS,
        public_scifact_footprint_digest=preview.FOOTPRINT_SHA,
        normalization="NFC/casefold/canonical-whitespace; article underscores equal spaces",
        public_example_claim_ids=sorted(preview.PUBLIC_EXAMPLE_CLAIM_IDS),
        components=components,
        source_claims=reference["climate_claims"],
        source_evidence_rows=reference["climate_evidence_rows"],
        annotation_values_used=False,
        old_gold_keys_CAS_opened=False,
    )
    encoded = canonical(manifest)
    # Exclusive publication cannot overwrite an old cut or any original history.
    for directory in [OUTPUT.parent, *OUTPUT.parent.parents]:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("protected output ancestor")
    if OUTPUT.parent.lstat().st_mode & 0o077:
        raise RuntimeError("private cut directory")
    parent_fd = os.open(
        OUTPUT.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        fd = os.open(
            OUTPUT.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    print(
        json.dumps(
            dict(
                schema="hepta.climate-fever.feature-cut.prepared.v1",
                feature_cut_digest=sha(encoded),
                components=len(components),
                claims=sum(map(len, components)),
                evidence_rows=5 * sum(map(len, components)),
                annotation_values_used=False,
                holdout_initialized=False,
                holdout_consumed=False,
                qualified=False,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
