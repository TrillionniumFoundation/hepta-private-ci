"""Independent source capabilities, answer scoring and fresh-worker bindings."""

import json

from population_audit_artifacts import _checkpoint, _hash, _json, _read, _require, _same


FAMILIES = (
    "semantic",
    "episode",
    "procedure",
    "event_interpolation",
    "procedure_extrapolation",
)


GROUPS = {
    "all": None,
    "known": set(FAMILIES),
    "retention": set(FAMILIES[:3]),
    "transfer": set(FAMILIES[3:]),
    "unknown": {"unknown"},
    **{k: {k} for k in FAMILIES},
}


def _capability(probe, version, sources):
    op = probe["operation"]
    if op["kind"] == "semantic":
        rows = [
            r
            for r in sources
            if r["kind"] == "semantic"
            and (r["entity"], r["relation"]) == (op["entity"], op["relation"])
        ]
        allowed = bool(rows)
    elif op["kind"] in ("event_at", "event_asof"):
        rows = [
            r
            for r in sources
            if r["kind"] == "episode"
            and r["entity"] == op["entity"]
            and (op["kind"] != "event_at" or r["day"] == op["day"])
        ]
        allowed = 0 <= op["day"] <= 100 and any(r["day"] <= op["day"] for r in rows)
    else:
        _require(op["kind"] == "procedure", "registered capability kind")
        rows = [
            r for r in sources if r["kind"] == "procedure" and r["rule"] == op["rule"]
        ]
        allowed = bool(rows) and 0 <= op["input"] <= 100
    roots = sorted(r["source_digest"] for r in rows)
    match = roots == sorted(probe["source_roots"])
    supported = bool(probe["source_roots"]) and set(probe["source_roots"]) <= set(
        version["roots"]
    )
    return {
        "source_supported": supported,
        "operation_supported": allowed,
        "declared_roots_match": match,
        "capability_allowed": supported and match and allowed,
        "expected_roots": roots,
    }


def _assessment(probe, generated, version, sources):
    abstained = generated is None
    text = None if abstained else generated["text"]
    capability = _capability(probe, version or {"roots": []}, sources)
    known, exact = (
        probe["family"] != "unknown",
        not abstained and text == probe["value"],
    )
    correct = bool(known and exact and capability["capability_allowed"])
    return {
        "probe_id": probe["probe_id"],
        "family": probe["family"],
        "raw_text": text,
        "output_text": "unknown" if abstained else text,
        **capability,
        "raw_correct": exact,
        "supported_correct": correct,
        "correct": correct if known else abstained or text == "unknown",
        "action_abstained": abstained,
        "decoder_unknown": not abstained and text == "unknown",
        "version_manifest_sha256": version["manifest_sha256"] if version else None,
    }


def _metrics(rows):
    metrics = {}
    for name, families in GROUPS.items():
        selected = [r for r in rows if families is None or r["family"] in families]
        n = len(selected)
        correct, raw = (
            sum(r["correct"] for r in selected),
            sum(r["raw_correct"] for r in selected),
        )
        metrics[name] = {
            "total": n,
            "correct": correct,
            "accuracy": correct / n if n else None,
            "raw_correct": raw,
            "raw_exact_match": raw / n if n else None,
            "supported_correct": sum(r["supported_correct"] for r in selected),
            "action_abstentions": sum(r["action_abstained"] for r in selected),
            "decoder_unknown": sum(r["decoder_unknown"] for r in selected),
        }
    return metrics


def _journal(directory, label, version, probes, context):
    journal = _json(directory / f"{label}-journal.json")
    request, binding = (
        _json(directory / f"{label}-request.json"),
        _json(directory / f"{label}-binding.json"),
    )
    activation = _json(directory / f"{label}-activation.json")
    stdout = _json(directory / f"{label}-stdout.json")
    expected_keys = {
        "model",
        "snapshot",
        "manifest_sha256",
        "scope",
        "allowed_roots",
        "questions",
        "rank",
        "seed",
        "control",
    }
    _require(
        set(request) == expected_keys and request["control"] == "adapter",
        "closed answer-free worker request",
    )
    _same(
        request["questions"],
        [p["question"] for p in probes],
        "actual final worker questions",
    )
    _require(
        request["manifest_sha256"] == version["manifest_sha256"]
        and request["rank"] == version["rank"]
        and request["seed"] == version["seed"]
        and set(request["allowed_roots"]) == set(version["roots"]),
        "actual worker version binding",
    )
    _same(journal["binding"], binding, "persisted reader binding")
    _same(binding["context"], context, "worker commitment context")
    _same(activation["context"], context, "activation commitment context")
    _require(
        journal["request_sha256"]
        == binding["request_sha256"]
        == _hash(json.dumps(request, sort_keys=True).encode()),
        "worker payload hash",
    )
    _require(
        activation["activated_unix_ns"]
        <= binding["bound_unix_ns"]
        <= journal["worker_started_unix_ns"]
        <= journal["worker_finished_unix_ns"],
        "activation/request/worker ordering",
    )
    if context:
        _require(
            context["route_plan_committed_unix_ns"] <= activation["activated_unix_ns"],
            "route plan committed before worker activation",
        )
    _same(
        journal["active_version"],
        binding["active_version"],
        "owner active version binding",
    )
    _same(
        journal["active_version"],
        activation["active_version"],
        "persisted owner activation",
    )
    _require(
        journal["active_version"]["manifest_sha256"] == version["manifest_sha256"]
        and journal["owner_admitted_before_and_after"] is True,
        "verified owner lifecycle",
    )
    checkpoint = _checkpoint(version)
    _require(
        journal["admitted_adapter_state_sha256"]
        == journal["consumed_adapter_state_sha256"]
        == checkpoint["state"],
        "actual inference state equals checkpoint",
    )
    _require(
        all(
            journal[key] is False
            for key in (
                "fact_input",
                "retrieval_input",
                "answer_lexicon_input",
                "production_accepted",
            )
        ),
        "no answer material in worker ingress",
    )
    for key, value in stdout.items():
        _same(journal[key], value, "raw worker stdout preserved")
    _same(
        [r["question"] for r in journal["rows"]],
        request["questions"],
        "raw final output alignment",
    )
    _require(
        all(
            r["answer_postprocessed"] is False and type(r["text"]) is str
            for r in journal["rows"]
        ),
        "unmodified decoder strings",
    )
    return journal
