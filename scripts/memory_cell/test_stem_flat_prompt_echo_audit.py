"""Synthetic-only attribution guards; cannot certify author-written citations."""

from copy import deepcopy
import unittest

from native import digest
from stem_audit_archive import AuditError
from stem_reader_format_ablation import flat_user_message
from stem_flat_prompt_echo_audit import (
    MIN_COPY_LENGTH, MARKER, _static_system,
    longest_prompt_copy, review_copied_markers,
)

PHASES = ("select", "retention", "test", "transfer")
SYSTEM = "Give short direct answers and cite the evidence label [E1]. Do not echo the prompt."


def fixture():
    cases, raw = [], []
    for phase in PHASES:
        for i in range(8):
            qid = f"{phase}-{i}"
            q = dict(identity=qid, family="family-"+qid,
                     content="Where?", scope="scope-"+qid,
                     observed_at="2024-04-11")
            evidence = [dict(label="E1", id="source-"+qid,
                             root="root", scope=q["scope"],
                             observed_at="2024-04-10",
                             excerpt="Paris, France, is described here.")]
            case = dict(
                phase=phase, question_id=qid, question=q,
                delivered_evidence=evidence,
                original_reader_identity="reader-pin",
                original_reader_profile="prompt-pin",
                original_input_sha256="a"*64,
                original_generated_sha256="b"*64,
                original_answer_sha256="c"*64,
                original_canonical_request_sha256="d"*64,
                format_rewrite_only=True,
            )
            user = flat_user_message(q, evidence)
            answer = (
                user if i == 0
                else SYSTEM if i == 1
                else "Paris [E1]." if i == 2
                else "Bogus reference [E99]." if i == 3
                else "No citation asserted."
            )
            raw.append(dict(
                schema="hepta.stem-flat-format-answer.v1",
                question_id=qid, phase=phase, status="succeeded",
                answer=answer,
                case_original_digest=digest(case),
                original_reader_identity="reader-pin",
                original_reader_profile="prompt-pin",
                previous_answer_sha256="c"*64,
                receipt=dict(
                    generator_identity="reader-pin",
                    original_reader_profile="prompt-pin",
                    delivered_evidence=evidence,
                    question_digest=digest(q),
                    new_flat_user_message_digest=digest(user),
                    decoded_max_new_tokens=96,
                    generator_parameter_updates=0,
                    new_flat_user_payload_only=True,
                    same_generator_weights=True,
                    same_system_instruction=True,
                    production_accepted=False,
                ),
            ))
            cases.append(case)
    return cases, raw


class FlatPromptEchoTests(unittest.TestCase):
    def test_long_original_system_and_user_prompt_copies_are_distinct(self):
        case, _ = fixture()
        user = flat_user_message(
            case[0]["question"], case[0]["delivered_evidence"]
        )
        for answer, expected in ((user, "user"), (SYSTEM, "system")):
            marker = next(MARKER.finditer(answer))
            n, source = longest_prompt_copy(answer, marker, user, SYSTEM)
            self.assertGreaterEqual(n, MIN_COPY_LENGTH)
            self.assertEqual(source, expected)

    def test_bare_source_label_without_context_is_not_credited_as_copy(self):
        case, _ = fixture()
        user = flat_user_message(
            case[0]["question"], case[0]["delivered_evidence"]
        )
        response = "Paris [E1]."
        marker = next(MARKER.finditer(response))
        n, _ = longest_prompt_copy(response, marker, user, SYSTEM)
        self.assertLess(n, MIN_COPY_LENGTH)

    def test_complete_phase_denominators_and_nonsemantic_echo_categories(self):
        result = review_copied_markers(*fixture(), SYSTEM)
        self.assertEqual(result["registered_distinct_questions"], 32)
        self.assertEqual(result["structural_citation_markers"], 16)
        self.assertEqual(result["bound_to_delivered_evidence_label"], 12)
        self.assertEqual(result["verbatim_prompt_citation_markers"], 8)
        self.assertEqual(result["flat_user_prompt_copies"], 4)
        self.assertEqual(result["original_system_prompt_copies"], 4)
        self.assertEqual(result["markers_not_proven_prompt_copies"], 8)
        self.assertIsNone(result["independent_semantic_entailment_precision"])
        self.assertFalse(result["production_accepted"])

    def test_missing_duplicate_source_drift_and_forged_identity_are_rejected(self):
        for issue in ("missing", "duplicate", "source", "reader", "prompt"):
            cases, rows = fixture()
            if issue == "missing":
                rows.pop()
            elif issue == "duplicate":
                rows[-1] = deepcopy(rows[0])
            elif issue == "source":
                rows[0]["receipt"]["delivered_evidence"][0]["excerpt"] = "forged"
            elif issue == "reader":
                rows[0]["receipt"]["generator_identity"] = "forged"
            else:
                rows[0]["receipt"]["new_flat_user_message_digest"] = "0"*64
            with self.subTest(issue=issue), self.assertRaises(AuditError):
                review_copied_markers(cases, rows, SYSTEM)

    def test_static_system_ast_does_not_execute_imports(self):
        self.assertEqual(
            _static_system(b'SYSTEM = "Please cite [E1]."\n'
                           b'UNUSED = None\n'),
            "Please cite [E1].",
        )
        with self.assertRaises(AuditError):
            _static_system(b'SYSTEM = "No citation in prompt"\n')


if __name__ == "__main__":
    unittest.main()
