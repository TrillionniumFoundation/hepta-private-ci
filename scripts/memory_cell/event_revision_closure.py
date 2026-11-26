"""Source-bound correction closure for the controlled event projection.

The inherited organized mode remains unchanged for historical replay. This mode
uses the entire already-built projection to reject obsolete candidate facts;
it NEVER inserts an out-of-pool fact into the reader. These logical revisions
are not trusted calendar times. No weights or production authorities are used.
"""

PROFILE = "hepta.controlled-event.revision-closure.v1"


def select_current(projection, lookup, candidates, *, revoked, limit=4):
    """Keep complete current alternative groups or report a missing prerequisite.

    Reuse EventProjection validation before reading its derived state. All
    ancestors are present and revisions strictly decrease. Work on the full
    bounded projection is reported, not counted free.
    """
    projection.select(lookup, candidates, mode="hybrid", revoked=revoked, limit=limit)
    facts = projection.facts
    active = {
        key: row for key, row in facts.items() if row["revision"] <= lookup.revision
    }
    retired, edges = set(), 0
    for row in active.values():
        # Every intermediate event is active because correction revisions strictly
        # increase. Include chains even when retrieval omits intermediate nodes.
        retired.update(row["supersedes"])
        edges += len(row["supersedes"])
    heads = {key: row for key, row in active.items() if key not in retired}
    pool = set(candidates)
    selected, missing, capacity = [], set(), []
    entities, conflicts = {lookup.entity}, 0
    incomplete = False
    for attribute in lookup.path:
        next_entities = set()
        for entity in sorted(entities):
            required = {
                key
                for key, row in heads.items()
                if (row["entity"], row["attribute"]) == (entity, attribute)
            }
            absent = required - pool
            alternatives = {heads[key]["value"] for key in required}
            conflicts += int(len(alternatives) > 1)
            if not required or absent:
                missing.update(absent)
                incomplete = True
                continue  # A missing conflicting head cannot certify the other.
            if len(set(selected) | required) > limit:
                capacity.append((entity, attribute))
                incomplete = True
                continue
            for key in candidates:
                if key in required and key not in selected:
                    selected.append(key)
            next_entities.update(alternatives)
        entities = next_entities
    return tuple(selected), dict(
        profile=PROFILE,
        inspected=len(candidates),
        source_event_reads=len(facts),
        active_event_reads=len(active),
        correction_edges_read=edges,
        conflicts=conflicts,
        incomplete=incomplete,
        missing_current_heads=sorted(missing),
        capacity_blocked=capacity,
        obsolete_candidates=[key for key in candidates if key in retired],
        injected_out_of_pool_sources=0,
        independently_adjudicated=False,
    )
