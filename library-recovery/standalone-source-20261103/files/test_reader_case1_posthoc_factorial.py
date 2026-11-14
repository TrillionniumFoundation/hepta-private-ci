"""Adversarial masks, provenance and raw-answer controls; NO model answers."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from io import BytesIO
import zipfile

from reader_case1_posthoc_factorial import (
    ARMS,
    HYBRID,
    IDENTITIES,
    QUESTION_ID,
    SCHEMA,
    SUPPORT,
    check_rows,
    checked_zip,
    digest_bytes,
    registered_plan,
    selections,
    strict_json,
)


def stable(value):
    return digest_bytes(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    )


def sample():
    candidate_ids = list(HYBRID) + [
        "event_cbfd4ba5_6", "event_cbfd4ba5_0", "event_cbfd4ba5_3"
    ]
    case = dict(
        query=dict(identity=QUESTION_ID, scope=QUESTION_ID, content="test"),
        kind="correction",
        candidate_ids=candidate_ids,
        candidate_digest=stable(candidate_ids),
        frontier="fixed-source-frontier",
        controls=dict(
            program_support=dict(selected=[SUPPORT]),
            hybrid=dict(selected=list(HYBRID)),
        ),
    )
    docs = {
        name: SimpleNamespace(scope=QUESTION_ID, content=f"immutable:{name}")
        for name in candidate_ids
    }
    return case, docs


def seal_fixture(files):
    data = dict(files)
    data["SHA256SUMS"] = "".join(
        f"{digest_bytes(value)}  ./{name}\n"
        for name, value in sorted(data.items())
    ).encode()
    with BytesIO() as output:
        with zipfile.ZipFile(output, "w") as archive:
            for name, value in data.items():
                archive.writestr(name, value)
        return output.getvalue()


class PosthocFactorialTests(unittest.TestCase):
    def setUp(self):
        module = ModuleType("native")
        module.digest = stable
        self.mock_native = patch.dict(sys.modules, {"native": module})
        self.mock_native.start()
        self.addCleanup(self.mock_native.stop)
        self.case, self.docs = sample()

    def test_entire_three_bit_factorial_preserves_original_rank(self):
        x = selections()
        self.assertEqual(len(x), 8)
        self.assertEqual(len(set(x.values())), 8)
        self.assertEqual(x[ARMS[0]], (SUPPORT,))
        self.assertEqual(x[ARMS[-1]], HYBRID)
        for name, keys in x.items():
            self.assertIn(SUPPORT, keys)
            self.assertEqual(keys, tuple(k for k in HYBRID if k in keys))
            self.assertEqual(len(keys), 1 + name.count("1"))

    def test_original_authored_case_is_registered_without_targets(self):
        a = registered_plan(self.case, self.docs)
        self.assertEqual(a["case_id"], QUESTION_ID)
        self.assertEqual(a["eight_arms"], list(ARMS))
        self.assertTrue(a["observed_then_registered"])
        self.assertFalse(a["target_labels_exposed"])
        self.assertFalse(a["original_80_call_matrix_membership"])

    def test_wrong_support_or_source_order_never_becomes_new_arm(self):
        for kind in ("support", "order", "scope", "digest", "kind"):
            with self.subTest(kind=kind):
                case, docs = sample()
                if kind == "support":
                    case["controls"]["program_support"]["selected"] = [HYBRID[0]]
                elif kind == "order":
                    case["controls"]["hybrid"]["selected"].reverse()
                elif kind == "scope":
                    docs[SUPPORT].scope = "other"
                elif kind == "digest":
                    case["candidate_digest"] = "b" * 64
                else:
                    case["kind"] = "procedure"
                with self.assertRaises(ValueError):
                    registered_plan(case, docs)

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                strict_json(raw)

    def test_incomplete_source_gate_never_invents_a_model_attempt(self):
        self.assertEqual(
            check_rows({}, tier="smol-1.7b", case=self.case,
                       originals=self.docs, expected_commit="a" * 40)["attempted"],
            0,
        )
        with self.assertRaises(ValueError):
            check_rows({"raw-answers.jsonl": b"{}\n"}, tier="smol-1.7b",
                       case=self.case, originals=self.docs,
                       expected_commit="a" * 40)

    def test_fabricated_source_set_or_preexisting_score_is_rejected(self):
        for kind in ("source", "arm", "score", "status"):
            with self.subTest(kind=kind):
                files = self.valid_single_row()
                row = strict_json(files["raw-answers.jsonl"].strip())
                if kind == "source":
                    row["selected"] = list(HYBRID)
                elif kind == "arm":
                    row["arm"] = ARMS[1]
                elif kind == "score":
                    row["strict_task_success"] = True
                else:
                    row["status"] = "fabricated"
                files["raw-answers.jsonl"] = (json.dumps(row) + "\n").encode()
                with self.assertRaises(ValueError):
                    self.audit(files)

    def test_model_identity_prompt_and_exact_source_bytes_are_required(self):
        for kind in ("model", "prompt", "source", "citation"):
            with self.subTest(kind=kind):
                files = self.valid_single_row()
                row = strict_json(files["raw-answers.jsonl"].strip())
                if kind == "model":
                    row["receipt"]["reader_identity"] = "0" * 64
                elif kind == "prompt":
                    row["receipt"]["input_ids_digest"] = "0" * 64
                elif kind == "source":
                    row["receipt"]["delivered_evidence"][0]["excerpt"] = "fake"
                else:
                    row["citation_audit"]["request"]["answer"] = "rewritten"
                files["raw-answers.jsonl"] = (json.dumps(row) + "\n").encode()
                with self.assertRaises(ValueError):
                    self.audit(files)

    def test_one_mock_fixture_row_is_not_eight_actual_calls(self):
        value = self.audit(self.valid_single_row())
        self.assertEqual(value["attempted"], 1)
        self.assertEqual(value["succeeded"], 1)
        self.assertFalse(value["complete"])
        self.assertEqual(value["input_tokens"], 13)

    def test_run_seal_requires_five_part_original_provenance(self):
        files = self.valid_single_row()
        files["run.json"] = b'{"attempts":8}'
        with self.assertRaises(ValueError):
            self.audit(files)

    def test_original_outer_zip_digest_and_inner_sha_are_independent(self):
        payload = seal_fixture({"host-gate.json": b"{}"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "original.zip"
            path.write_bytes(payload)
            self.assertIn("host-gate.json", checked_zip(path, outer_sha=digest_bytes(payload)))
            with self.assertRaisesRegex(ValueError, "external original"):
                checked_zip(path, outer_sha="0" * 64)
            modified = seal_fixture({"host-gate.json": b"{}"})
            with zipfile.ZipFile(BytesIO(modified)) as archive:
                files = {n: archive.read(n) for n in archive.namelist()}
            files["host-gate.json"] = b"altered"
            with BytesIO() as out:
                with zipfile.ZipFile(out, "w") as archive:
                    for name, data in files.items():
                        archive.writestr(name, data)
                corrupted = out.getvalue()
            path.write_bytes(corrupted)
            with self.assertRaisesRegex(ValueError, "inner ZIP"):
                checked_zip(path, outer_sha=digest_bytes(corrupted))

    def test_original_source_case1_matches_preobserved_masks(self):
        import os
        source = Path(os.getenv("HEPTA_ORIGINAL_SOURCE_ZIP", ""))
        if not source.is_file():
            self.skipTest("immutable Actions source ZIP not staged during source-only CI")
        with zipfile.ZipFile(source) as archive:
            case = strict_json(archive.read("plan/plan.json"))["cases"][1]
            docs = {
                row["identity"]: SimpleNamespace(scope=row["scope"], content=row["content"])
                for row in strict_json(archive.read("plan/source-view.json"))
            }
        frozen = registered_plan(case, docs)
        self.assertEqual(tuple(frozen["masks"][ARMS[-1]]), HYBRID)
        self.assertEqual(tuple(frozen["masks"][ARMS[0]]), (SUPPORT,))

    def valid_single_row(self):
        arm, selected = ARMS[0], list(selections()[ARMS[0]])
        prompt = "a" * 64
        row = dict(
            question_id=QUESTION_ID, kind="correction", arm=arm,
            candidate_digest=self.case["candidate_digest"],
            selected=selected, status="succeeded", answer="I do not have enough evidence.",
            receipt=dict(
                reader_identity=IDENTITIES["smol-1.7b"],
                view_profile="hepta.controlled-event.schema-expansion.v1",
                query_digest=stable(self.case["query"]),
                omitted_evidence_bytes=0,
                derived_evidence=[], derived_view_digest=stable([]),
                token_limit=2048, trainable_parameters=0,
                answer_postprocessed=False, production_accepted=False,
                input_tokens=13, generated_tokens=3,
                input_ids_digest=prompt, generated_ids_digest="b" * 64,
                reader_profile="c" * 64, seconds=0.01,
                delivered_evidence=[
                    dict(original_id=key, excerpt=self.docs[key].content, scope=QUESTION_ID)
                    for key in selected
                ],
            ),
            citation_audit=dict(
                request=dict(query_id=QUESTION_ID, prompt_digest=prompt,
                             answer="I do not have enough evidence."),
                semantic_precision=None, production_accepted=False,
            ),
        )
        frozen = registered_plan(self.case, self.docs)
        return dict(
            **{"case-plan.json": (json.dumps(frozen) + "\n").encode()},
            **{"raw-answers.jsonl": (json.dumps(row) + "\n").encode()},
        )

    def audit(self, files):
        return check_rows(
            files, tier="smol-1.7b", case=self.case,
            originals=self.docs, expected_commit="a" * 40,
        )


if __name__ == "__main__":
    unittest.main()
