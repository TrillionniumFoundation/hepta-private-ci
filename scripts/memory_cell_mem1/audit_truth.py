"""Reconstruct MEM-1 v1 query truth from frozen facts and the owner protocol.

The event's own expected label never supplies ground truth. This checks retained
synthetic evidence; it neither attests execution nor qualifies a real-task model.
"""

from environment import OUTPUTS


def validate_labels(value, width, field):
    if (
        type(value) is not list
        or len(value) != width
        or any(type(label) is not int or not 0 <= label < OUTPUTS for label in value)
    ):
        raise ValueError(f"{field} must contain one integer label per source")


def audit_truth(events, frozen_input, *, owner_change):
    """Check outcomes without the runner's Owner, answer, or correctness code."""
    records = frozen_input.get("initial_facts")
    sources = {f"{task}:{index}" for task in "AB" for index in range(12)}
    if type(records) is not list or len(records) != len(sources):
        raise ValueError("frozen initial facts must contain the MEM-1 source roster")
    facts = {}
    fields = {"source", "label", "version", "scope", "live", "replay"}
    for record in records:
        if type(record) is not dict or set(record) != fields:
            raise ValueError("invalid frozen initial fact fields")
        source = record["source"]
        if type(source) is not str or source not in sources or source in facts:
            raise ValueError("duplicate or unknown frozen initial source")
        validate_labels([record["label"]], 1, "frozen label")
        if (
            type(record["version"]) is not int
            or record["version"] != 1
            or record["scope"] != "scope:mem1"
            or record["live"] is not True
            or record["replay"] is not True
        ):
            raise ValueError("initial fact differs from the MEM-1 v1 owner protocol")
        facts[source] = dict(record)

    seen, previous, changed, queries = set(), {}, False, 0
    for row in events:
        if row["event"] == "owner_change":
            if not owner_change or changed:
                raise ValueError("unexpected owner change while reconstructing truth")
            for source in ("A:8", "A:9"):
                previous[source] = facts[source]["label"]
                facts[source]["label"] = (facts[source]["label"] + 3) % OUTPUTS
                facts[source]["version"] = 2
            facts["A:10"].update(version=2, live=False)
            facts["A:11"].update(version=2, scope="scope:other")
            # The fixed 24-source roster fits the v1 pool; only this reset
            # removes exposures, including superseded but still live sources.
            seen.difference_update({"A:8", "A:9", "A:10", "A:11"})
            changed = True
        if row["event"] not in {"probe", "prequential"}:
            continue
        queries += 1
        query = row.get("sources")
        if (
            type(query) is not list
            or not query
            or any(type(source) is not str or source not in facts for source in query)
        ):
            raise ValueError("query contains an unknown or malformed source")
        current = [facts[source] for source in query]
        eligible = all(
            fact["live"] and fact["scope"] == "scope:mem1" for fact in current
        )
        truth = [fact["label"] for fact in current]
        expected = truth if eligible else None
        output = row.get("output")
        if "output" not in row:
            raise ValueError("query is missing its output")
        if output is not None:
            validate_labels(output, len(query), "output")
        if row.get("expected") is not None:
            validate_labels(row["expected"], len(query), "expected")
        if "expected" not in row or row["expected"] != expected:
            raise ValueError("expected differs from frozen owner truth")
        derived = {
            "eligible": eligible,
            "correct": output == truth if eligible else output is None,
            "answered": output is not None,
            "wrong_assertion": output is not None and output != truth,
            "stale_assertion": output is not None
            and any(
                source in previous and label == previous[source]
                for source, label in zip(query, output)
            ),
            "invalid_assertion": output is not None and not eligible,
        }
        for field, value in derived.items():
            if row.get(field) is not value:
                raise ValueError(f"{field} differs from frozen owner truth")
        blocked = [
            not (fact["live"] and fact["scope"] == "scope:mem1" and source in seen)
            for source, fact in zip(query, current)
        ]
        recorded = row.get("blocked")
        if (
            type(recorded) is not list
            or len(recorded) != len(blocked)
            or any(type(flag) is not bool for flag in recorded)
            or recorded != blocked
        ):
            raise ValueError("blocked differs from frozen source exposure")
        if row["event"] == "prequential":
            # Queries precede supervision even though their log records follow
            # the update receipt. Read-only probes never add an exposure.
            seen.update(query)
    if changed is not owner_change:
        raise ValueError("missing owner change while reconstructing truth")
    return queries
