"""Adversarial source-bound partial Reader control tests; no model calls."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from reader_original_case_binding import (
    ARMS,
    IDENTITIES,
    SCHEMA,
    VIEW,
    bind_shard,
    digest,
    frozen_case,
    open_public_plan,
)


def fixture():
    q = dict(identity="task1", scope="task1", family="task1",
             content="Which source is current?", observed_at="2026-10-10T00:00:00+00:00")
    ids = [f"event_{i}" for i in range(4)]
    case = dict(query=q, kind="correction", candidate_ids=ids,
                candidate_digest=digest(ids), frontier="frontier1",
                controls=dict(hybrid=dict(selected=ids),
                              program_support=dict(selected=ids[1:3]),
                              without_prerequisite=dict(selected=ids[2:3]),
                              empty=dict(selected=[])))
    docs = {key: dict(identity=key, scope="task1", content='{"id":"'+key+'"}')
            for key in ids}
    expected = frozen_case(case, docs, 0)
    row = dict(question_id="task1", kind="correction", arm="none", selected=[],
               candidate_digest=case["candidate_digest"], status="succeeded",
               answer="I do not have enough evidence.",
               receipt=dict(reader_identity=IDENTITIES["smol-1.7b"],
                            view_profile=VIEW, query_digest=digest(q), token_limit=2048,
                            input_tokens=209, generated_tokens=8, trainable_parameters=0,
                            answer_postprocessed=False, independent_semantic_review=False,
                            semantic_citation_precision=None, production_accepted=False,
                            seconds=2.2, reader_profile="f"*64,
                            input_ids_digest="a"*64, generated_ids_digest="b"*64,
                            delivered_evidence=[]),
               citation_audit=dict(request=dict(query_id="task1",prompt_digest="a"*64,
                                                answer="I do not have enough evidence."),
                                   semantic_precision=None, production_accepted=False))
    contents = {"case-plan.json":json.dumps(expected).encode(),
                "raw-answers.jsonl":(json.dumps(row)+"\n").encode()}
    return case,docs,contents


class FrozenSourceBindingTests(unittest.TestCase):
    def test_authored_partial_generation_is_not_complete_shard(self):
        case,docs,files=fixture()
        result=bind_shard(files,tier="smol-1.7b",index=0,
                          plan={"cases":[case]},docs=docs)
        self.assertEqual(result["rows"],1)
        self.assertEqual(result["succeeded"],1)
        self.assertFalse(result["full_original_pair"])
        self.assertTrue(result["exact_source_bound"])

    def test_altered_model_identity_never_counts_as_real_frozen_reader(self):
        case,docs,files=fixture()
        row=json.loads(files["raw-answers.jsonl"])
        row["receipt"]["reader_identity"]="f"*64
        files["raw-answers.jsonl"]=(json.dumps(row)+"\n").encode()
        with self.assertRaisesRegex(ValueError,"model/prompt"):
            bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)

    def test_changed_prompt_or_citation_request_cannot_be_accepted(self):
        for mode in ("query_digest","prompt_digest","answer"):
            with self.subTest(mode=mode):
                case,docs,files=fixture()
                row=json.loads(files["raw-answers.jsonl"])
                if mode=="query_digest":
                    row["receipt"]["query_digest"]="f"*64
                else:
                    row["citation_audit"]["request"][mode]="fake"
                files["raw-answers.jsonl"]=(json.dumps(row)+"\n").encode()
                with self.assertRaises(ValueError):
                    bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)

    def test_wrong_source_excerpt_is_not_valid_delivery(self):
        case,docs,files=fixture()
        row=json.loads(files["raw-answers.jsonl"])
        row["arm"]="selected_k"
        row["selected"]=["event_0"]
        row["receipt"]["delivered_evidence"]=[
            dict(original_id="event_0", excerpt="INJECTED")]
        files["raw-answers.jsonl"]=(json.dumps(row)+"\n").encode()
        # Cannot skip none arm; hidden reorder is itself invalid.
        with self.assertRaisesRegex(ValueError,"original frozen task/arm"):
            bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)
        # The first, valid none arm must appear before the altered second arm.
        original=json.loads(fixture()[2]["raw-answers.jsonl"])
        files["raw-answers.jsonl"]=(json.dumps(original)+"\n"+json.dumps(row)+"\n").encode()
        with self.assertRaisesRegex(ValueError,"source excerpt"):
            bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)

    def test_unauthorized_training_precision_or_semantic_attestation_rejected(self):
        mutations=("trainable_parameters","answer_postprocessed",
                   "independent_semantic_review","production_accepted")
        for field in mutations:
            with self.subTest(field=field):
                case,docs,files=fixture()
                row=json.loads(files["raw-answers.jsonl"])
                row["receipt"][field]=1 if field=="trainable_parameters" else True
                files["raw-answers.jsonl"]=(json.dumps(row)+"\n").encode()
                with self.assertRaisesRegex(ValueError,"model/prompt"):
                    bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)

    def test_modifying_frozen_ablation_or_source_pool_rejected(self):
        case,docs,files=fixture()
        fake=json.loads(files["case-plan.json"])
        fake["arms"]["hybrid_k4"].reverse()
        files["case-plan.json"]=json.dumps(fake).encode()
        with self.assertRaisesRegex(ValueError,"original public frozen plan"):
            bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)
        copy=deepcopy(case)
        copy["controls"]["without_prerequisite"]["selected"]=["event_1"]
        with self.assertRaisesRegex(ValueError,"pre-registered"):
            frozen_case(copy,docs,0)

    def test_complete_receipt_required_before_five_successes_qualify(self):
        case,docs,files=fixture()
        raw=json.loads(files["raw-answers.jsonl"])
        rows=[]
        for arm in ARMS:
            row=deepcopy(raw)
            row["arm"]=arm
            row["selected"]=json.loads(files["case-plan.json"])["arms"][arm]
            row["receipt"]["delivered_evidence"]=[
                dict(original_id=source,excerpt=docs[source]["content"])
                for source in row["selected"]]
            rows.append(row)
        files["raw-answers.jsonl"]=("\n".join(json.dumps(row) for row in rows)+"\n").encode()
        with self.assertRaisesRegex(ValueError,"complete run receipt"):
            bind_shard(files,tier="smol-1.7b",index=0,plan={"cases":[case]},docs=docs)

    def test_external_source_checksum_must_match_exact_archived_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            bad=Path(temp)/"source.zip"
            bad.write_bytes(b"fake source zip")
            with self.assertRaisesRegex(ValueError,"original source artifact"):
                open_public_plan(bad)


if __name__=="__main__":
    unittest.main()
