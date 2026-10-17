"""Single-hop versus path traversal controls using original event semantics."""

from dataclasses import asdict
from copy import deepcopy
import json
import unittest

from event_experience import question
from event_projection import EventProjection
from native import Document
from strong_rag_hop_control import derive_single_hop


def fixture(kind, path, *, correction=False):
    qid = "scope_1"
    spec = dict(
        id=qid,
        phase="test",
        kind=kind,
        entity="service_1",
        path=list(path),
        revision=2,
    )
    q, _ = question(spec, "2026-10-11T00:00:00Z")
    events = [
        ("event_1", "service_1", path[0], "component_1", 1, []),
    ]
    if len(path) == 2:
        events.append(("event_2", "component_1", path[1], "site_11111111", 1, []))
    if correction:
        events.append(("event_3", "service_1", path[0], "component_2", 2, ["event_1"]))
        if len(path) == 2:
            events.append(("event_4", "component_2", path[1], "site_22222222", 2, []))
    docs = []
    for name, entity, attr, value, rev, replaced in events:
        content = json.dumps(
            dict(
                schema="hepta.controlled-event.v1",
                id=name,
                entity=entity,
                attribute=attr,
                value=value,
                revision=rev,
                supersedes=replaced,
            )
        )
        docs.append(Document(name, "root_" + name, qid, qid, q.observed_at, content))
    projection = EventProjection(tuple(docs))
    candidates = tuple(d.identity for d in docs)
    from native import digest

    _, lookup = question(spec, q.observed_at)
    full, _ = projection.select(lookup, candidates, mode="entity_time", revoked=set())
    organized, _ = projection.select(
        lookup, candidates, mode="organized", revoked=set()
    )
    case = dict(
        query=asdict(q),
        kind=kind,
        frontier=projection.frontier,
        candidate_ids=candidates,
        candidate_digest=digest(candidates),
        controls=dict(
            entity_time=dict(selected=list(full)),
            organized=dict(selected=list(organized)),
        ),
    )
    return [case], [spec], {d.identity: d for d in docs}


class HopControlTests(unittest.TestCase):
    def test_two_hop_traversal_adds_second_original_source(self):
        cases, specs, docs = fixture("composition", ("component", "location"))
        copied, receipt = derive_single_hop(cases, specs, docs)
        self.assertEqual(copied[0]["controls"]["single_hop"]["selected"], ["event_1"])
        self.assertEqual(
            copied[0]["controls"]["entity_time"]["selected"], ["event_1", "event_2"]
        )
        self.assertFalse(receipt["test_cases"][0]["first_hop_equals_full_path"])
        self.assertEqual(cases[0]["controls"].keys(), {"entity_time", "organized"})

    def test_correction_is_not_confused_with_traversal(self):
        cases, specs, docs = fixture("correction", ("component",), correction=True)
        out, receipt = derive_single_hop(cases, specs, docs)
        self.assertEqual(
            out[0]["controls"]["single_hop"]["selected"], ["event_1", "event_3"]
        )
        self.assertEqual(
            out[0]["controls"]["entity_time"]["selected"], ["event_1", "event_3"]
        )
        self.assertEqual(out[0]["controls"]["organized"]["selected"], ["event_3"])
        self.assertTrue(receipt["test_cases"][0]["first_hop_equals_full_path"])
        self.assertFalse(receipt["test_cases"][0]["full_path_equals_correction"])

    def test_answer_bearing_spec_and_heldout_drift_reject(self):
        cases, specs, docs = fixture("composition", ("component", "location"))
        bad = deepcopy(specs)
        bad[0]["support"] = ["event_1"]
        with self.assertRaises(ValueError):
            derive_single_hop(cases, bad, docs)
        bad = deepcopy(specs)
        bad[0]["entity"] = "secret"
        with self.assertRaises(ValueError):
            derive_single_hop(cases, bad, docs)
        with self.assertRaises(ValueError):
            derive_single_hop(cases, specs + specs, docs)

    def test_changed_source_or_original_arm_reject(self):
        cases, specs, docs = fixture("composition", ("component", "location"))
        edited = deepcopy(cases)
        edited[0]["controls"]["entity_time"]["selected"].reverse()
        with self.assertRaises(ValueError):
            derive_single_hop(edited, specs, docs)
        edited = deepcopy(cases)
        edited[0]["candidate_ids"] = tuple(reversed(edited[0]["candidate_ids"]))
        with self.assertRaises(ValueError):
            derive_single_hop(edited, specs, docs)
        modified = dict(docs)
        modified.pop("event_2")
        with self.assertRaises(ValueError):
            derive_single_hop(cases, specs, modified)

    def test_strict_single_hop_semantics(self):
        cases, specs, docs = fixture("new_fact", ("component",))
        _, receipt = derive_single_hop(cases, specs, docs)
        self.assertEqual(receipt["planned_questions"], 1)
        self.assertFalse(receipt["source_selection_used_test_labels"])
        self.assertFalse(receipt["production_accepted"])


if __name__ == "__main__":
    unittest.main()
