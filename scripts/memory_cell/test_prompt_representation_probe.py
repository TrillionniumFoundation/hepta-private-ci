"""Fail-closed reader-format controls with synthetic plus optional archive tests."""

import copy
import json
import os
from pathlib import Path
import unittest

from offline_event_reader_trial import inputs
from offline_smol_reader import digest
from prompt_representation_probe import (
    ARMS,
    STYLES,
    build_messages,
    event_text,
    strict_answer,
)


def fixture():
    rows = [
        dict(
            schema="hepta.controlled-event.v1",
            id=f"event_{i}",
            entity="service_a" if i == 0 else "component_a",
            attribute="component" if i == 0 else "location",
            value="component_a" if i == 0 else "site_1234abcd",
            revision=1,
            supersedes=[],
        )
        for i in range(2)
    ]
    sources = {
        row["id"]: dict(
            identity=row["id"],
            scope="scope_a",
            observed_at="2026-10-15T00:00:00Z",
            content=json.dumps(row),
        )
        for row in rows
    }
    selected = ["event_0", "event_1"]
    case = dict(
        query=dict(
            identity="question_a",
            scope="scope_a",
            observed_at="2026-10-15T10:00:00Z",
            content="At revision 1 what is the assigned component's location?",
        ),
        candidate_ids=selected,
        candidate_digest=digest(selected),
        controls={
            "empty": dict(selected=[]),
            "hybrid": dict(selected=selected),
            "organized": dict(selected=selected),
            "without_prerequisite": dict(selected=["event_1"]),
        },
    )
    return case, sources


class FrozenReaderRepresentationTests(unittest.TestCase):
    def setUp(self):
        self.case, self.sources = fixture()

    def test_selection_unchanged_for_each_fixed_style(self):
        for arm in ARMS:
            original = self.case["controls"][arm]["selected"]
            for style in STYLES:
                messages, selected = build_messages(self.case, arm, style, self.sources)
                self.assertEqual(selected, list(original))
                self.assertEqual(messages[0]["role"], "system")
                evidence = json.loads(messages[1]["content"])["evidence"]
                self.assertEqual(len(evidence), len(original))
                self.assertEqual(
                    [item["label"] for item in evidence],
                    [f"E{i + 1}" for i in range(len(original))],
                )

    def test_normalized_text_contains_all_original_fields(self):
        row = json.loads(self.sources["event_0"]["content"])
        text = event_text(self.sources["event_0"])
        for field in ("id", "entity", "attribute", "value", "schema"):
            self.assertIn(f"{field}={row[field]}", text)
        self.assertIn(f"revision={row['revision']}", text)
        self.assertNotIn("expected", text)

    def test_source_time_and_scope_guards(self):
        for field, bad in (
            ("scope", "wrong-scope"),
            ("observed_at", "9999-01-01T00:00:00Z"),
        ):
            altered = copy.deepcopy(self.sources)
            altered["event_0"][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_messages(self.case, "organized", "verbatim", altered)

    def test_bad_identity_and_duplicate_json_properties(self):
        altered = copy.deepcopy(self.sources["event_0"])
        altered["content"] = altered["content"].replace(
            '"entity":', '"entity": "fake", "entity":', 1
        )
        with self.assertRaises(ValueError):
            event_text(altered)
        altered = copy.deepcopy(self.sources["event_0"])
        altered["identity"] = "other"
        with self.assertRaises(ValueError):
            event_text(altered)

    def test_candidate_drift_and_unknown_conditions(self):
        modified = copy.deepcopy(self.case)
        modified["candidate_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            build_messages(modified, "organized", "normalized", self.sources)
        for arm, style in (("program_support", "verbatim"), ("organized", "free")):
            with self.assertRaises(ValueError):
                build_messages(self.case, arm, style, self.sources)

    def test_strict_scoring_rejects_prose(self):
        self.assertEqual(strict_answer("site_abcd1234 [E1]"), "site_abcd1234")
        self.assertEqual(strict_answer("site_abcd1234"), "site_abcd1234")
        self.assertIsNone(strict_answer("The answer is site_abcd1234."))
        self.assertIsNone(strict_answer("site_abcd1234 [E0]"))


@unittest.skipUnless(
    os.environ.get("HEPTA_FROZEN_EVENT_ARCHIVE"), "archive unavailable"
)
class ArchivedInputIntegrityTests(unittest.TestCase):
    def test_actual_8_by_4_by_2_unmodified_selection_census(self):
        plan, sources, _ = inputs(Path(os.environ["HEPTA_FROZEN_EVENT_ARCHIVE"]))
        self.assertEqual(len(plan["cases"]) * len(ARMS) * len(STYLES), 64)
        for case in plan["cases"]:
            for arm in ARMS:
                original = case["controls"][arm]["selected"]
                for style in STYLES:
                    messages, selected = build_messages(case, arm, style, sources)
                    self.assertEqual(selected, list(original))
                    self.assertEqual(
                        len(json.loads(messages[1]["content"])["evidence"]),
                        len(original),
                    )


if __name__ == "__main__":
    unittest.main()
