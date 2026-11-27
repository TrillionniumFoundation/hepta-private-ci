"""Source selection and independent actual-call observation for the real probe."""

from datetime import datetime, timezone
import unittest

import torch

from native_latent import LightCellHead
from prepare_news_cohorts import normalized_title, publisher_is_ood
from real_evolution_probe import _measure, select_unused_rows


class EvolutionProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        publishers = {}
        for index in range(100):
            value = f"synthetic publisher {index}"
            publishers.setdefault(publisher_is_ood(value), value)
        cls.rows = []
        for month in range(3, 9):
            for ood in (False, True):
                for label in range(4):
                    for index in range(96):
                        name = f"{month}-{int(ood)}-{label}-{index}"
                        cls.rows.append({"source_id": name, "source_group_id": "story-" + name,
                            "text": "Unique headline " + name, "publisher": publishers[ood], "label": label,
                            "timestamp_ms": int(datetime(2014, month, 15, tzinfo=timezone.utc).timestamp() * 1000)})

    def test_exclusion_covers_groups_titles_and_later_story_copies(self):
        old = self.rows[0]
        alias = {**old, "source_id": "title-alias", "source_group_id": "title-alias",
                 "text": "  " + old["text"].upper() + "  "}
        late = {**self.rows[1], "source_id": "late-copy",
                "timestamp_ms": int(datetime(2014, 5, 15, tzinfo=timezone.utc).timestamp() * 1000)}
        source = self.rows + [alias, late]
        selected = select_unused_rows(source, {"original": [old]})
        self.assertEqual(selected, select_unused_rows(list(reversed(source)), {"original": [old]}))
        rows = [r for values in selected.values() for r in values]
        self.assertEqual(len(rows), len({r["source_group_id"] for r in rows}))
        self.assertEqual(len(rows), len({normalized_title(r["text"]) for r in rows}))
        self.assertNotIn(old["source_group_id"], {r["source_group_id"] for r in rows})
        self.assertNotIn(normalized_title(old["text"]), {normalized_title(r["text"]) for r in rows})
        self.assertNotIn("late-copy", {r["source_id"] for r in rows})

    def test_insufficient_future_window_never_substitutes_another_month(self):
        source = [r for r in self.rows if datetime.fromtimestamp(r["timestamp_ms"] / 1000,
                                                                timezone.utc).month != 8]
        with self.assertRaisesRegex(ValueError, "future_2 lacks"):
            select_unused_rows(source, {})

    def test_forward_observer_counts_real_examples_and_restores_method(self):
        head = LightCellHead(2, task_count=4)
        original = LightCellHead.forward
        def run():
            return [head(torch.zeros(n, 2), torch.zeros(n, head.state_width))["task_logits"] for n in (3, 5)]
        outputs, counts = _measure(run)
        self.assertEqual([list(value.shape) for value in outputs], [[3, 4], [5, 4]])
        self.assertEqual(counts, {"head_example_calls": 8, "head_module_invocations": 2})
        self.assertIs(LightCellHead.forward, original)


if __name__ == "__main__":
    unittest.main()
