"""Post-generation decoder measurements and an executed exact SQLite baseline.

Call binding_specificity only after raw generation journals are sealed. Its
source targets are measurement labels, never generation or selection inputs.
"""

import json
import re
import sqlite3
import time


def _catalogue(facts, questions):
    fields = {"scope", "entity", "relation", "value", "source_digest"}
    if type(facts) is not list or not 1 <= len(facts) <= 128:
        raise ValueError("bounded source fact list required")
    for fact in facts:
        if (
            type(fact) is not dict
            or set(fact) != fields
            or any(
                type(v) is not str or not v.strip() or len(v.encode()) > 1024
                for v in fact.values()
            )
        ):
            raise ValueError("exact typed source fact fields required")
        if re.fullmatch(r"[0-9a-f]{64}", fact["source_digest"]) is None:
            raise ValueError("source digest required")
    if len({f["scope"] for f in facts}) != 1 or len(
        {(f["entity"], f["relation"]) for f in facts}
    ) != len(facts):
        raise ValueError("one scope with unique entity/relation facts required")
    if (
        type(questions) is not list
        or not 1 <= len(questions) <= 256
        or any(
            type(q) is not str or not q.strip() or len(q.encode()) > 4096
            for q in questions
        )
    ):
        raise ValueError("bounded question strings required")


def _fact_index(facts, question):
    matches = [
        i
        for i, f in enumerate(facts)
        if all(
            re.search(r"(?<!\w)" + re.escape(f[key]) + r"(?!\w)", question)
            for key in ("entity", "relation")
        )
    ]
    entities = {
        f["entity"]
        for f in facts
        if re.search(r"(?<!\w)" + re.escape(f["entity"]) + r"(?!\w)", question)
    }
    return matches[0] if len(matches) == len(entities) == 1 else None


def binding_specificity(cell, facts, questions):
    """Measure symmetric swapped-value margins from full-vocabulary logits."""
    import torch
    from experience_inference import frozen_adapter_mode
    from native import digest
    from parametric_model import adapter_digest
    from pretrained import frozen_digest

    _catalogue(facts, questions)
    if facts[0]["scope"] != cell.reader.scope:
        raise ValueError("measurement scope differs from decoder scope")
    mapping = [_fact_index(facts, q) for q in questions]
    if any(i is None for i in mapping):
        raise ValueError("measurement requires uniquely source-bound questions")
    values = [
        cell.reader.tokenizer.encode(f["value"], add_special_tokens=False)
        for f in facts
    ]
    if any(len(v) != 1 or v[0] == cell.reader.tokenizer.eos_token_id for v in values):
        raise ValueError("next-token binding requires single-token source values")
    if len({f["value"] for f in facts}) != len({v[0] for v in values}):
        raise ValueError("distinct source values collide in the tokenizer")
    targets = [values[i][0] for i in mapping]
    pending, pairs, unpaired = list(range(len(questions))), [], []
    while pending:
        counts = {v: sum(targets[i] == v for i in pending) for v in set(targets)}
        first = min(pending, key=lambda i: (-counts[targets[i]], targets[i], i))
        pending.remove(first)
        choices = [
            j
            for j in pending
            if targets[j] != targets[first]
            and facts[mapping[j]]["source_digest"]
            != facts[mapping[first]]["source_digest"]
            and facts[mapping[j]]["relation"] == facts[mapping[first]]["relation"]
        ]
        if choices:
            second = min(choices, key=lambda i: (-counts[targets[i]], targets[i], i))
            pending.remove(second)
            pairs.append((first, second))
        else:
            unpaired.append(first)
    prompts = [cell.prompt_ids(q) for q in questions]
    before_state, started = adapter_digest(cell.reader.model), time.perf_counter()
    scores, calls = {}, 0
    for arm, enabled in (("before", False), ("after", True)):
        scores[arm] = []
        for ids in prompts:
            x = torch.tensor([ids], dtype=torch.long)
            with frozen_adapter_mode(cell.reader.model, enabled=enabled):
                logits = (
                    cell.reader.model(
                        input_ids=x,
                        attention_mask=torch.ones_like(x),
                        use_cache=False,
                        return_dict=True,
                    )
                    .logits[0, -1]
                    .float()
                )
                if (
                    logits.shape != (cell.reader.model.config.vocab_size,)
                    or not torch.isfinite(logits).all()
                ):
                    raise ValueError("invalid full-vocabulary next-token logits")
                scores[arm].append({v: float(logits[v]) for v in set(targets)})
            calls += 1
    if (
        adapter_digest(cell.reader.model) != before_state
        or frozen_digest(cell.reader.model) != cell.reader.base_digest
    ):
        cell.reader.quarantined, cell.reader.scope = True, None
        raise ValueError("measurement changed decoder weights")
    rows = []
    for first, second in pairs:
        a, b = targets[first], targets[second]
        row = dict(
            question_indices=[first, second],
            source_digests=[
                facts[mapping[i]]["source_digest"] for i in (first, second)
            ],
        )
        for arm in ("before", "after"):
            margins = [
                scores[arm][first][a] - scores[arm][first][b],
                scores[arm][second][b] - scores[arm][second][a],
            ]
            row.update(
                {
                    arm + "_margins": margins,
                    arm: sum(margins) / 2,
                    arm + "_both_correct": all(v > 0 for v in margins),
                }
            )
        row["delta"] = row["after"] - row["before"]
        rows.append(row)
    before = sum(row["before"] for row in rows) / len(rows) if rows else None
    after = sum(row["after"] for row in rows) / len(rows) if rows else None
    return dict(
        schema="hepta.parametric-memory.binding-measurement.v1",
        before=before,
        after=after,
        delta=after - before if rows else None,
        pairs=rows,
        unpaired_question_indices=sorted(unpaired),
        prompt_sha256=[digest(ids) for ids in prompts],
        model_forward_calls=calls,
        seconds=time.perf_counter() - started,
        full_vocabulary=True,
        weights_unchanged=True,
        source_values_used_for_measurement_only=True,
        generation_calls=0,
        training_steps=0,
        selection_authority=False,
        production_accepted=False,
    )


def exact_kv_baseline(facts, questions):
    """Execute typed SQLite writes and parsed lookups; retain unresolved reads."""
    _catalogue(facts, questions)
    started = time.perf_counter()
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE memory(scope TEXT NOT NULL, entity TEXT NOT NULL, relation TEXT NOT NULL, value TEXT NOT NULL, source_digest TEXT NOT NULL, PRIMARY KEY(scope, entity, relation)) WITHOUT ROWID"
        )
        connection.executemany(
            "INSERT INTO memory VALUES (?, ?, ?, ?, ?)",
            [
                (f["scope"], f["entity"], f["relation"], f["value"], f["source_digest"])
                for f in facts
            ],
        )
        connection.commit()
        write_seconds = time.perf_counter() - started
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        sqlite_bytes = page_size * page_count
        if (
            hasattr(connection, "serialize")
            and len(connection.serialize()) != sqlite_bytes
        ):
            raise ValueError("SQLite serialized size differs from allocated pages")
        started, rows, sql_reads = time.perf_counter(), [], 0
        for question in questions:
            index, result = _fact_index(facts, question), None
            if index is not None:
                fact = facts[index]
                result = connection.execute(
                    "SELECT value, source_digest FROM memory WHERE scope=? AND entity=? AND relation=?",
                    (fact["scope"], fact["entity"], fact["relation"]),
                ).fetchone()
                sql_reads += 1
            rows.append(
                dict(
                    question=question,
                    text=result[0] if result else None,
                    source_digest=result[1] if result else None,
                    status="answered" if result else "unresolved",
                )
            )
        return dict(
            schema="hepta.parametric-memory.exact-sqlite-baseline.v1",
            rows=rows,
            sqlite_bytes=sqlite_bytes,
            page_size=page_size,
            page_count=page_count,
            source_json_bytes=len(
                json.dumps(
                    facts, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ),
            write_seconds=write_seconds,
            read_seconds=time.perf_counter() - started,
            rows_written=len(facts),
            queries=len(questions),
            sql_reads=sql_reads,
            bytes_basis="actual_sqlite_allocated_pages",
            memory_rss_bytes=None,
            parser="unique_complete_entity_and_relation_word_boundaries",
            source_digest_retained=True,
            idealized_accuracy=False,
            production_accepted=False,
        )
    finally:
        connection.close()
