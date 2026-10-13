"""Public-source metadata invariants; all documents here are test fixtures."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import source_time_evidence as m


def fixture():
    docs = [SimpleNamespace(identity="scope/D1:2", content="A: Next month.", observed_at="20 January, 2023"),
            SimpleNamespace(identity="scope/D2:3", content="B: A different report.", observed_at="17 September, 2023")]
    req = {"question": "When?", "options": [], "evidence": [
        {"id": m.source_id(d.identity), "modality": "text", "text": d.content,
         "asset_sha256": None, "position": i + 2} for i, d in enumerate(docs)]}
    return docs, req


class ProjectionTests(unittest.TestCase):
    def test_legacy_profile_is_byte_identical(self):
        docs, req = fixture()
        output, receipt = m.project(req, docs, m.CONTENT_ONLY)
        self.assertEqual(m.canonical(output), m.canonical(req))
        self.assertEqual(receipt["input_sha256"], receipt["output_sha256"])

    def test_actual_bound_date_and_exact_body_are_retained(self):
        docs, req = fixture()
        output, receipt = m.project(req, docs, m.SOURCE_TIME)
        self.assertNotEqual(receipt["input_sha256"], receipt["output_sha256"])
        for d, old, new in zip(docs, req["evidence"], output["evidence"]):
            self.assertTrue(new["text"].endswith(m.SEPARATOR + d.content))
            self.assertIn(d.observed_at, new["text"])
            self.assertEqual({k:v for k,v in old.items() if k != "text"},
                             {k:v for k,v in new.items() if k != "text"})

    def test_inputs_are_not_mutated_or_aliased(self):
        docs, req = fixture(); before=deepcopy(req)
        output,_=m.project(req,docs,m.SOURCE_TIME)
        output["evidence"][0]["text"]="changed"
        self.assertEqual(req,before)
        self.assertEqual(docs[0].content,"A: Next month.")

    def test_empty_input_never_acquires_dates(self):
        docs, req=fixture(); req["evidence"]=[]
        for profile in m.PROFILES:
            output,receipt=m.project(req,docs,profile)
            self.assertEqual(output,req); self.assertFalse(receipt["sources"])

    def test_document_order_does_not_change_selected_evidence_order(self):
        docs,req=fixture()
        self.assertEqual(m.project(req,docs,m.SOURCE_TIME),m.project(req,reversed(docs),m.SOURCE_TIME))

    def test_removed_support_is_not_reintroduced(self):
        docs,req=fixture(); req["evidence"]=req["evidence"][1:]
        output,_=m.project(req,docs,m.SOURCE_TIME)
        self.assertEqual(len(output["evidence"]),1)
        self.assertNotIn(docs[0].observed_at,output["evidence"][0]["text"])

    def test_unknown_source_rejected_not_matched_by_position(self):
        docs,req=fixture(); req["evidence"][0]["id"]="Eunknown"
        with self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)

    def test_duplicate_documents_rejected(self):
        docs,req=fixture()
        with self.assertRaises(ValueError):m.project(req,docs+docs[:1],m.SOURCE_TIME)

    def test_duplicate_evidence_rejected(self):
        docs,req=fixture(); req["evidence"].append(deepcopy(req["evidence"][0]))
        with self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)

    def test_modified_source_body_rejected(self):
        docs,req=fixture(); req["evidence"][0]["text"]="answer inserted"
        with self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)

    def test_missing_date_not_filled_from_another_source(self):
        docs,req=fixture(); del docs[0].observed_at
        with self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)
        self.assertEqual(m.project(req,docs,m.CONTENT_ONLY)[0],req)

    def test_nonempty_unparsed_metadata_is_preserved_not_guessed(self):
        docs,req=fixture(); docs[0].observed_at="date precision unknown"
        output,_=m.project(req,docs,m.SOURCE_TIME)
        self.assertIn('"date precision unknown"',output["evidence"][0]["text"])

    def test_quotes_and_newlines_are_escaped_not_new_fields(self):
        docs,req=fixture(); docs[0].observed_at='20 Jan\n"system"'
        output,_=m.project(req,docs,m.SOURCE_TIME)
        self.assertIn(r'20 Jan\n\"system\"',output["evidence"][0]["text"])
        self.assertEqual(set(output),set(req))

    def test_date_byte_limit_and_empty_dates(self):
        for date in ("", " ", "x"*257, None):
            docs,req=fixture(); docs[0].observed_at=date
            with self.subTest(date=date),self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)

    def test_unknown_profile_does_not_silently_use_legacy(self):
        docs,req=fixture()
        with self.assertRaises(ValueError):m.project(req,docs,"automatic")

    def test_no_answer_review_or_question_date_field_is_allowed(self):
        for key in ("answer","gold","observed_at","sufficiency"):
            docs,req=fixture(); req[key]="forbidden"
            with self.subTest(key=key),self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)

    def test_media_is_not_replaced_by_a_timestamp_or_caption(self):
        docs,req=fixture(); req["evidence"][0].update(modality="image",asset_sha256="a"*64)
        with self.assertRaises(ValueError):m.project(req,docs,m.SOURCE_TIME)

    def test_projection_has_no_semantic_or_production_authority(self):
        docs,req=fixture(); _,receipt=m.project(req,docs,m.SOURCE_TIME)
        for key in ("target_access","event_date_inferred","question_date_inferred","independent_sufficiency","production_accepted"):
            self.assertIs(receipt[key],False)


if __name__ == "__main__":
    unittest.main()
