"""Clean source fields and fixed identifier baselines for prospective actions."""

import hashlib
from pathlib import Path

import numpy as np

from long_document_sources import canonical, sha
from operational_source_regions import (SELECTOR, identifiers, jaccard, parse_regions,
                                        readout_features)


HASH_WIDTH = 384
HASH_POLICY = {"schema": "hepta.operational-identifier-fields.v1", "width": HASH_WIDTH,
    "vocabulary": "selected-source identifier sets, no fitted vocabulary",
    "bucket": "little-endian first 8 bytes of SHA256(domain + UTF8 identifier) modulo 384",
    "sign": "+1 if byte 8 is even, -1 otherwise", "domain": "hepta-operational-id-v1\\0",
    "collision": "sum signed unit counts; normalize FP64 to FP32; zero norm unavailable",
    "scalar_features": ["identifier_jaccard", "changed_identifier_recall", "test_identifier_precision"],
    "metadata_features": False, "encoder_forward_calls": 0,
    "empty_identifier_policy": "both identifier baselines unavailable; never a fabricated numeric example"}


class SourceFeatureUnavailable(ValueError):
    """Valid supplied source with no defined feature under this fixed condition."""


def clean_fields(text, input_regions):
    regions = parse_regions(text, input_regions)
    if regions.family != "diagnostic_action":
        raise ValueError("prospective single-action source fields required")
    fields = {name: "\n".join(text[a:b] for a, b in spans) for name, spans in regions.fields}
    receipt = regions.receipt(text)
    receipt["join_policy"] = "exact selected source slices joined with one constant LF separator"
    for name, value in fields.items():
        receipt["fields"][name] = {"source_spans": receipt["fields"][name],
            "clean_utf8_sha256": sha(value.encode()), "clean_utf8_bytes": len(value.encode()),
            "selected_source_characters": sum(b - a for a, b in regions.spans(name))}
    return regions, fields, receipt


def hashed_identifiers(names):
    if not names:
        raise SourceFeatureUnavailable("empty source identifier set is unavailable")
    vector, used = np.zeros(HASH_WIDTH, np.float64), set()
    for name in sorted(names):
        value = hashlib.sha256(b"hepta-operational-id-v1\0" + name.encode()).digest()
        bucket = int.from_bytes(value[:8], "little") % HASH_WIDTH
        vector[bucket] += 1 if value[8] % 2 == 0 else -1
        used.add(bucket)
    norm = np.linalg.norm(vector)
    if norm == 0:
        raise SourceFeatureUnavailable("exact signed-hash cancellation is unavailable")
    output = np.frombuffer((vector / norm).astype(np.float32).tobytes(), np.float32)
    return output, {"identifiers": len(names), "occupied_buckets": len(used),
                    "colliding_identifier_insertions": len(names) - len(used),
                    "identifier_set_sha256": sha(canonical(sorted(names)))}


def source_only_features(text, input_regions):
    regions, _, receipt = clean_fields(text, input_regions)
    names = {name: identifiers(text, spans) for name, spans in regions.fields}
    pools, collisions = {}, {}
    for name, values in names.items():
        try:
            pools[name], collisions[name] = hashed_identifiers(values)
        except SourceFeatureUnavailable as error:
            raise SourceFeatureUnavailable(name + ": " + str(error)) from error
    intersection = len(names["change"] & names["test"])
    scalars = np.asarray([jaccard(names["change"], names["test"]),
        intersection / len(names["change"]), intersection / len(names["test"])], np.float32)
    receipt["hash_accounting"] = collisions
    return readout_features(regions, pools, text), np.frombuffer(scalars.tobytes(), np.float32), receipt


def baseline_definition(kind):
    if kind not in ("identifier_hash770", "identifier_overlap3"):
        raise ValueError("unknown predeclared source-only baseline")
    definition = {"kind": kind, "selector": SELECTOR, "hash_policy": HASH_POLICY,
        "source_code_sha256": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in
            ("operational_field_features.py", "operational_source_regions.py", "long_document_sources.py")}}
    return definition, sha(canonical(definition))
