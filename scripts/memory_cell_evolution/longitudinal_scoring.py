"""Score only raw admitted decoder rows against frozen current source values."""

from evolution_common import require


def questions(snapshot, templates):
    return [
        template.format(**fact) for fact in snapshot["facts"] for template in templates
    ]


def score_round(snapshot, previous, events, journal, templates):
    facts, rows = snapshot["facts"], journal["rows"]
    expected = questions(snapshot, templates)
    require(
        len(rows) == len(expected) and [r["question"] for r in rows] == expected,
        "raw decoder/fact/question alignment",
    )
    require(
        journal["fact_input"] is False
        and journal["retrieval_input"] is False
        and journal["answer_lexicon_input"] is False,
        "parameter score cannot include source/retrieval answers",
    )
    require(
        all(r["answer_postprocessed"] is False for r in rows),
        "parameter raw output was postprocessed",
    )
    width = len(templates)
    by_key, per_source, raw_correct = {}, [], 0
    for index, fact in enumerate(facts):
        chosen = rows[index * width : (index + 1) * width]
        hits = [row["text"].strip() == fact["value"] for row in chosen]
        raw_correct += sum(hits)
        key = (fact["entity"], fact["relation"])
        by_key[key] = all(hits)
        per_source.append(
            dict(
                entity=key[0],
                relation=key[1],
                source_digest=fact["source_digest"],
                expected=fact["value"],
                raw=[r["text"] for r in chosen],
                correct=hits,
                both_wordings_correct=all(hits),
            )
        )
    old = {(f["entity"], f["relation"]): f for f in (previous or {}).get("facts", [])}
    retained = [
        by_key[(f["entity"], f["relation"])]
        for f in facts
        if (f["entity"], f["relation"]) in old
        and old[(f["entity"], f["relation"])]["value"] == f["value"]
    ]
    corrected_keys = {
        (e["entity"], e["relation"]) for e in events if e["kind"] == "correct"
    }
    corrected = [by_key[k] for k in sorted(corrected_keys) if k in by_key]
    return dict(
        raw_queries=dict(correct=raw_correct, total=len(rows)),
        source_both_wordings=dict(
            correct=sum(by_key.values()),
            total=len(facts),
            accuracy=sum(by_key.values()) / len(facts),
        ),
        unchanged_retention=dict(
            correct=sum(retained),
            total=len(retained),
            accuracy=sum(retained) / len(retained) if retained else None,
        ),
        corrected_sources=dict(
            correct=sum(corrected), total=len(corrected), all_exact=all(corrected)
        ),
        per_source=per_source,
        origin="parameters",
        overlay_used=False,
    )


def quality_gates(scores, protocol):
    limits = protocol["predeclared_quality"]
    return dict(
        every_round_parameter_accuracy=all(
            s["source_both_wordings"]["accuracy"]
            >= limits["each_round_source_both_wordings_accuracy_min"]
            for s in scores
        ),
        every_measured_retention_panel=all(
            s["unchanged_retention"]["accuracy"] is None
            or s["unchanged_retention"]["accuracy"]
            >= limits["unchanged_retention_both_wordings_accuracy_min"]
            for s in scores
        ),
        every_corrected_source_exact=all(
            s["corrected_sources"]["all_exact"] for s in scores
        ),
    )
