"""Answer-free metadata capabilities and exact raw/support evaluation metrics."""

from population_fixtures import validate_sources


GROUPS = {
    "all": None,
    "known": {
        "semantic",
        "episode",
        "procedure",
        "event_interpolation",
        "procedure_extrapolation",
    },
    "retention": {"semantic", "episode", "procedure"},
    "transfer": {"event_interpolation", "procedure_extrapolation"},
    "unknown": {"unknown"},
    **{
        name: {name}
        for name in (
            "semantic",
            "episode",
            "procedure",
            "event_interpolation",
            "procedure_extrapolation",
        )
    },
}


def source_capabilities(sources):
    """Strip answers, locations and program coefficients from validated sources."""
    fields = {
        "semantic": ("kind", "entity", "relation", "source_digest"),
        "episode": ("kind", "entity", "day", "source_digest"),
        "procedure": ("kind", "rule", "source_digest"),
    }
    return [
        {key: row[key] for key in fields[row["kind"]]}
        for row in validate_sources(sources)
    ]


def probe_eligibility(probe, version, capabilities):
    """Use supplied structured operations and source metadata, never probe gold.

    This is a capability guard, not a learned natural-language parser. Complete
    event histories are required for as-of reads, including the temporal bound.
    """
    operation = probe["operation"]
    shapes = {
        "semantic": {"kind", "entity", "relation"},
        "event_at": {"kind", "entity", "day"},
        "event_asof": {"kind", "entity", "day"},
        "procedure": {"kind", "rule", "input"},
    }
    if (
        type(operation) is not dict
        or operation.get("kind") not in shapes
        or set(operation) != shapes[operation["kind"]]
    ):
        raise ValueError("closed source capability operation required")
    kind = operation["kind"]
    if any(
        type(operation[key]) is not str or not 1 <= len(operation[key].encode()) <= 1024
        for key in shapes[kind] - {"day", "input"}
    ):
        raise ValueError("bounded capability operation strings required")
    if kind == "semantic":
        rows = [
            r
            for r in capabilities
            if r["kind"] == "semantic"
            and r["entity"] == operation["entity"]
            and r["relation"] == operation["relation"]
        ]
        operation_supported = bool(rows)
    elif kind in ("event_at", "event_asof"):
        if type(operation["day"]) is not int or not 0 <= operation["day"] <= 100:
            raise ValueError("bounded event capability day required")
        rows = [
            r
            for r in capabilities
            if r["kind"] == "episode" and r["entity"] == operation["entity"]
        ]
        if kind == "event_at":
            rows = [r for r in rows if r["day"] == operation["day"]]
        operation_supported = any(r["day"] <= operation["day"] for r in rows)
    else:
        if type(operation["input"]) is not int or not 0 <= operation["input"] <= 100:
            raise ValueError("bounded procedure capability input required")
        rows = [
            r
            for r in capabilities
            if r["kind"] == "procedure" and r["rule"] == operation["rule"]
        ]
        operation_supported = bool(rows)
    expected = sorted(r["source_digest"] for r in rows)
    roots = probe["source_roots"]
    if type(roots) is not list or len(roots) != len(set(roots)):
        raise ValueError("unique declared probe source roots required")
    supported = bool(roots) and set(roots) <= set(version["roots"])
    matches = sorted(roots) == expected
    return {
        "source_supported": supported,
        "operation_supported": operation_supported,
        "declared_roots_match": matches,
        "capability_allowed": supported and matches and operation_supported,
        "expected_roots": expected,
    }


def assess_probe(probe, generated, version, capabilities):
    abstained = generated is None
    raw = None if abstained else generated["text"]
    eligibility = probe_eligibility(probe, version or {"roots": []}, capabilities)
    known = probe["family"] != "unknown"
    exact = not abstained and raw == probe["value"]
    supported_correct = bool(known and exact and eligibility["capability_allowed"])
    return {
        "probe_id": probe["probe_id"],
        "family": probe["family"],
        "raw_text": raw,
        "output_text": "unknown" if abstained else raw,
        **eligibility,
        "raw_correct": exact,
        "supported_correct": supported_correct,
        "correct": supported_correct if known else abstained or raw == "unknown",
        "action_abstained": abstained,
        "decoder_unknown": not abstained and raw == "unknown",
        "version_manifest_sha256": version["manifest_sha256"] if version else None,
    }


def summarize_rows(rows):
    result = {}
    for name, families in GROUPS.items():
        cohort = [r for r in rows if families is None or r["family"] in families]
        count = len(cohort)
        correct = sum(r["correct"] for r in cohort)
        raw = sum(r["raw_correct"] for r in cohort)
        result[name] = {
            "total": count,
            "correct": correct,
            "accuracy": correct / count if count else None,
            "raw_correct": raw,
            "raw_exact_match": raw / count if count else None,
            "supported_correct": sum(r["supported_correct"] for r in cohort),
            "action_abstentions": sum(r["action_abstained"] for r in cohort),
            "decoder_unknown": sum(r["decoder_unknown"] for r in cohort),
        }
    return result


def score_single(probes, journal, version, capabilities):
    """Score exact raw strings and supported answers separately; no normalization."""
    if [p["question"] for p in probes] != [r["question"] for r in journal["rows"]]:
        raise ValueError("evaluation probes and raw generation journal differ")
    rows = [
        assess_probe(p, r, version, capabilities)
        for p, r in zip(probes, journal["rows"], strict=True)
    ]
    return {"rows": rows, "metrics": summarize_rows(rows)}
