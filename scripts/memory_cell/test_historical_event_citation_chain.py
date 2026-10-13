"""Pure, model-free tests for historical literal-citation provenance tracing."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from historical_event_citation_chain import (
    archived_files,
    digest_json,
    sha,
    trace_cited_chain,
    trace_row,
    summarize,
)


def event(name, subject, attribute, value, revision=1):
    return dict(
        identity=name,
        root="root_" + name,
        scope="scope_1",
        content=json.dumps(
            dict(
                schema="hepta.controlled-event.v1",
                id=name,
                entity=subject,
                attribute=attribute,
                value=value,
                revision=revision,
                supersedes=[],
            ),
            sort_keys=True,
        ),
    )


def case():
    a = event("first", "service_1", "component", "component_1")
    b = event("second", "component_1", "location", "site_good")
    c = event("wrong", "component_other", "location", "site_bad")
    docs = {r["identity"]: r for r in (a, b, c)}
    spec = dict(entity="service_1", path=["component", "location"], revision=2)
    deliveries = [
        dict(
            label=f"E{i}",
            original_id=x,
            root=docs[x]["root"],
            scope=docs[x]["scope"],
            excerpt=docs[x]["content"],
            source_digest=digest_json(docs[x]["content"]),
        )
        for i, x in enumerate(("first", "second"), 1)
    ]
    row = dict(
        question_id="q1",
        kind="composition",
        arm="organized",
        status="succeeded",
        answer="site_good [E2]",
        selected=["first", "second"],
        strict_task_success=True,
        parsed_identifier="site_good",
        receipt=dict(input_ids_digest="a" * 64, delivered_evidence=deliveries),
        citation_audit=dict(
            request=dict(
                query_id="q1",
                answer="site_good [E2]",
                prompt_digest="a" * 64,
            )
        ),
    )
    return row, spec, docs


class FormalCitationTests(unittest.TestCase):
    def test_two_hop_answer_with_only_final_hop_cited_is_not_proven(self):
        row, spec, docs = case()
        found = trace_row(row, spec, ["first", "second"], docs)
        self.assertTrue(found["strict_task_success"])
        self.assertEqual(found["missing_program_declared_support"], ["first"])
        self.assertFalse(found["program_declared_support_cited"])
        self.assertFalse(found["publicly_declared_event_path_connected"])

    def test_full_original_source_chain_becomes_formally_connected(self):
        row, spec, docs = case()
        row["answer"] = row["citation_audit"]["request"]["answer"] = (
            "site_good [E1] [E2]"
        )
        found = trace_row(row, spec, ["first", "second"], docs)
        self.assertTrue(found["program_declared_support_cited"])
        self.assertTrue(found["publicly_declared_event_path_connected"])

    def test_extra_delivered_citation_is_not_a_valid_answer_path(self):
        row, spec, docs = case()
        row["selected"].append("wrong")
        row["receipt"]["delivered_evidence"].append(
            dict(
                label="E3",
                original_id="wrong",
                root=docs["wrong"]["root"],
                scope=docs["wrong"]["scope"],
                excerpt=docs["wrong"]["content"],
                source_digest=digest_json(docs["wrong"]["content"]),
            )
        )
        row["answer"] = row["citation_audit"]["request"]["answer"] = (
            "site_good [E1] [E2] [E3]"
        )
        found = trace_row(row, spec, ["first", "second"], docs)
        self.assertTrue(found["strict_task_success"])
        self.assertTrue(found["program_declared_support_cited"])
        self.assertFalse(found["publicly_declared_event_path_connected"])

    def test_dangling_citation_rejected_but_complete_alternative_path_allowed(self):
        _, spec, docs = case()
        docs["dangling"] = event("dangling", "service_1", "component", "component_2")
        self.assertFalse(
            trace_cited_chain(
                spec, ["first", "second", "dangling"], docs, "site_good"
            )
        )
        docs["alternate_end"] = event(
            "alternate_end", "component_2", "location", "site_good"
        )
        self.assertTrue(
            trace_cited_chain(
                spec,
                ["first", "second", "dangling", "alternate_end"],
                docs,
                "site_good",
            )
        )

    def test_wrong_disconnected_source_cannot_pretend_to_be_first_hop(self):
        row, spec, docs = case()
        self.assertFalse(trace_cited_chain(spec, ["second"], docs, "site_good"))
        self.assertFalse(trace_cited_chain(spec, ["first", "wrong"], docs, "site_good"))
        self.assertFalse(trace_cited_chain(spec, ["first", "second"], docs, "site_bad"))

    def test_future_revision_cannot_supply_historical_answer(self):
        row, spec, docs = case()
        doc = json.loads(docs["second"]["content"])
        doc["revision"] = 3
        docs["second"]["content"] = json.dumps(doc, sort_keys=True)
        self.assertFalse(
            trace_cited_chain(spec, ["first", "second"], docs, "site_good")
        )

    def test_provenance_must_not_prove_conflicting_answers(self):
        row, spec, docs = case()
        docs["another"] = event("another", "component_1", "location", "site_other")
        self.assertFalse(
            trace_cited_chain(spec, ["first", "second", "another"], docs, "site_good")
        )

    def test_superseded_first_hop_cannot_prove_current_event_chain(self):
        _, spec, docs = case()
        newer = event("new_first", "service_1", "component", "component_2", revision=2)
        source = json.loads(newer["content"])
        source["supersedes"] = ["first"]
        newer["content"] = json.dumps(source, sort_keys=True)
        docs["new_first"] = newer
        docs["new_second"] = event(
            "new_second", "component_2", "location", "site_good", revision=2
        )
        self.assertFalse(
            trace_cited_chain(spec, ["first", "second"], docs, "site_good")
        )
        self.assertTrue(
            trace_cited_chain(spec, ["new_first", "new_second"], docs, "site_good")
        )

    def test_superseder_after_query_revision_is_not_retroactive(self):
        _, spec, docs = case()
        newer = event(
            "future_first", "service_1", "component", "component_2", revision=3
        )
        source = json.loads(newer["content"])
        source["supersedes"] = ["first"]
        newer["content"] = json.dumps(source, sort_keys=True)
        docs["future_first"] = newer
        self.assertTrue(trace_cited_chain(spec, ["first", "second"], docs, "site_good"))

    def test_unrelated_scopes_cannot_form_a_citation_path(self):
        _, spec, docs = case()
        docs["second"]["scope"] = "other_scope"
        self.assertFalse(
            trace_cited_chain(spec, ["first", "second"], docs, "site_good")
        )

    def test_unlabelled_correct_generation_fails_provenance_not_task_score(self):
        row, spec, docs = case()
        row["answer"] = row["citation_audit"]["request"]["answer"] = "site_good"
        found = trace_row(row, spec, ["first", "second"], docs)
        self.assertTrue(found["strict_task_success"])
        self.assertFalse(found["answer_has_citation_marker"])
        self.assertFalse(found["publicly_declared_event_path_connected"])

    def test_fabricated_label_replacement_and_queue_detachment_fail_closed(self):
        row, spec, docs = case()
        scenarios = []
        altered = deepcopy(row)
        altered["answer"] = altered["citation_audit"]["request"]["answer"] = (
            "site_good [E3]"
        )
        scenarios.append(altered)
        altered = deepcopy(row)
        altered["receipt"]["delivered_evidence"][1]["excerpt"] = "tampered"
        scenarios.append(altered)
        altered = deepcopy(row)
        altered["citation_audit"]["request"]["answer"] = "other"
        scenarios.append(altered)
        for bad in scenarios:
            with self.subTest(bad=bad["answer"]):
                with self.assertRaises(ValueError):
                    trace_row(bad, spec, ["first", "second"], docs)

    def test_correct_and_citation_complete_metrics_are_separate(self):
        row, spec, docs = case()
        found = trace_row(row, spec, ["first", "second"], docs)
        rows = [
            found | {"arm": arm}
            for arm in (
                "empty",
                "hybrid",
                "entity_time",
                "organized",
                "program_support",
                "without_prerequisite",
            )
            for _ in range(8)
        ]
        report = summarize(rows)
        self.assertEqual(report["organized"]["strict_task_success"], 8)
        self.assertEqual(
            report["organized"]["correct_with_public_event_chain_connected"], 0
        )

    def test_inner_manifest_rejects_mutation_even_if_outer_hash_is_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.zip"
            contents = dict(
                **{"tested-commit.txt": b"59f9eadd5cc919359079e04442f7343838a60057\n"},
                **{"demo.json": b'{"a":1}'},
            )
            sums = b"".join(
                (sha(data) + "  " + name + "\n").encode()
                for name, data in sorted(contents.items())
            )
            with zipfile.ZipFile(path, "w") as z:
                for name, payload in contents.items():
                    z.writestr(name, payload)
                z.writestr("SHA256SUMS", sums)
            self.assertEqual(
                archived_files(path, sha(path.read_bytes()))["demo.json"], b'{"a":1}'
            )
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("tested-commit.txt", contents["tested-commit.txt"])
                z.writestr("demo.json", b'{"a":2}')
                z.writestr("SHA256SUMS", sums)
            with self.assertRaisesRegex(
                ValueError, "inner archive member SHA mismatch"
            ):
                archived_files(path, sha(path.read_bytes()))

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        from historical_event_citation_chain import strict_json

        with self.assertRaises(ValueError):
            strict_json('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            strict_json('{"a":NaN}')


if __name__ == "__main__":
    unittest.main()
