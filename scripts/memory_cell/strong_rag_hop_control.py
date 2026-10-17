"""Frozen, label-blind single-hop ablation of controlled event evidence.

The inherited entity_time arm ALREADY traverses the entire entity/attribute
path. Only the organized arm removes explicitly superseded events. This control
isolates one-hop filtering from traversal without using target answers or
replacing original bytes. It is an AUTHORED development ablation, not a verified
sufficient or prospective source set.
"""

from dataclasses import asdict
from copy import deepcopy

from event_experience import question
from event_projection import EventProjection, Lookup
from native import Document, digest


PUBLIC_KEYS = frozenset({"entity", "id", "kind", "path", "phase", "revision"})
PROFILE = "hepta.memory-strong-rag.single-hop.v1"


def _source_documents(originals):
    docs = {}
    for key, record in originals.items():
        doc = (
            Document(**(record | {"assets": tuple(record["assets"])}))
            if isinstance(record, dict)
            else record
        )
        if not isinstance(doc, Document) or key != doc.identity or key in docs:
            raise ValueError("original source identity or type drift")
        docs[key] = doc
    return docs


def derive_single_hop(cases, public_specs, originals):
    """Return immutable-plan overlays and a deterministic, answer-free manifest.

    The caller MUST already have admitted the historic case/collection bytes.
    No labels, reference answers, procedures or target support are arguments.
    The published plan's complete-path entity_time and organized controls are
    independently regenerated before the one-hop choice can be admitted.
    """
    if not 1 <= len(cases) <= 16 or not isinstance(public_specs, list):
        raise ValueError("bounded frozen development census required")
    if any(not isinstance(s, dict) or set(s) != PUBLIC_KEYS for s in public_specs):
        raise ValueError("non-public or answer-bearing question field")
    ids = [s["id"] for s in public_specs]
    if len(set(ids)) != len(ids) or not 1 <= len(ids) <= 32:
        raise ValueError("duplicate or oversized public question census")
    specs = {s["id"]: s for s in public_specs if s["phase"] == "test"}
    qids = [c["query"]["identity"] for c in cases]
    if len(set(qids)) != len(qids) or set(qids) != set(specs):
        raise ValueError("test/control census drift")
    docs = _source_documents(originals)
    enriched, proofs = [], []
    for case in cases:
        qid = case["query"]["identity"]
        spec = specs[qid]
        if spec["kind"] != case["kind"]:
            raise ValueError("public kind drift")
        reconstructed, lookup = question(spec, case["query"]["observed_at"])
        if asdict(reconstructed) != case["query"]:
            raise ValueError("public question/prompt drift")
        scope_docs = tuple(d for d in docs.values() if d.scope == qid)
        if not scope_docs or len(scope_docs) > 32:
            raise ValueError("missing or oversized source scope")
        projection = EventProjection(scope_docs)
        if projection.frontier != case["frontier"]:
            raise ValueError("original event frontier drift")
        candidates = tuple(case["candidate_ids"])
        if (
            len(candidates) != len(set(candidates))
            or not 1 <= len(candidates) <= 32
            or digest(candidates) != case["candidate_digest"]
            or any(key not in projection.facts for key in candidates)
        ):
            raise ValueError("changed frozen source ranking")
        full, full_status = projection.select(
            lookup, candidates, mode="entity_time", revoked=set()
        )
        organized, organized_status = projection.select(
            lookup, candidates, mode="organized", revoked=set()
        )
        old_controls = case["controls"]
        if (
            tuple(old_controls["entity_time"]["selected"]) != full
            or tuple(old_controls["organized"]["selected"]) != organized
            or "single_hop" in old_controls
        ):
            raise ValueError("published multi-hop/correction selection drift")
        first_lookup = Lookup(lookup.entity, (lookup.path[0],), lookup.revision)
        first, first_status = projection.select(
            first_lookup, candidates, mode="entity_time", revoked=set()
        )
        if not first or not set(first).issubset(full) or first_status["incomplete"]:
            raise ValueError("invalid first-hop evidence coverage")
        copy = deepcopy(case)
        copy["controls"]["single_hop"] = {"selected": list(first)}
        enriched.append(copy)
        proofs.append(
            dict(
                question_id=qid,
                kind=case["kind"],
                ordered_candidates_sha256=digest(candidates),
                frontier=projection.frontier,
                original_query_sha256=digest(case["query"]),
                first_hop=list(first),
                full_path=list(full),
                corrected_full_path=list(organized),
                path_length=len(lookup.path),
                first_hop_equals_full_path=first == full,
                full_path_equals_correction=full == organized,
                full_path_conflicts=full_status["conflicts"],
                correction_conflicts=organized_status["conflicts"],
            )
        )
    return enriched, dict(
        schema=PROFILE,
        test_cases=proofs,
        planned_questions=len(proofs),
        public_question_census_digest=digest(public_specs),
        original_source_view_digest=digest([asdict(d) for d in docs.values()]),
        source_selection_used_test_labels=False,
        independent_semantic_review=False,
        production_accepted=False,
    )
