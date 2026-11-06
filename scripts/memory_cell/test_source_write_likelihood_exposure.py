"""Teacher forcing cannot relabel an unvisited writer question as training gain."""

from pathlib import Path
import tempfile
import unittest

from source_recall_likelihood import probe
from test_source_recall_probe import FakeReader
from test_source_write_probe_exposure import ProbeExposureTests


class LikelihoodExposureTests(unittest.TestCase):
    def test_teacher_forced_rows_split_actual_write_visits(self):
        example = ProbeExposureTests()
        example.setUp()
        docs, training = example.docs, example.training
        reader = FakeReader(docs)
        reader.tokenizer = example.tokenizer

        def score(_reader, prompt, _target, _arm):
            return dict(
                mean_nll=0.5,
                input_tokens=len(prompt) + 2,
                supervised_tokens=2,
                seconds=0.1,
            )

        with tempfile.TemporaryDirectory() as directory:
            result = probe(
                reader,
                docs,
                Path(directory) / "likelihood",
                snapshot_sha="a" * 64,
                writer_source="b" * 40,
                source_commit="c" * 40,
                maximum=2,
                scorer=score,
                training=training,
            )
            self.assertTrue(result["training_exposure_verified"])
            self.assertEqual(result["visited_source_questions"], 1)
            self.assertEqual(result["unvisited_source_questions"], 1)
            self.assertEqual(result["planned_records"], 16)
            self.assertEqual(
                result["by_exposure"]["visited"]["training"]["planned_source_scopes"], 1
            )
            self.assertEqual(
                result["by_exposure"]["unvisited"]["paraphrase"][
                    "planned_source_scopes"
                ],
                1,
            )
            self.assertEqual(
                result["by_exposure"]["unknown"]["training"]["planned_source_scopes"], 0
            )
            self.assertIsNone(result["parameter_memory_task_gain"])


if __name__ == "__main__":
    unittest.main()
