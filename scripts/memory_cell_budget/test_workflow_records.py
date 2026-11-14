"""Verify source extraction and grouping without a model or repair labels."""

import unittest

from workflow_records import direct_command, extract, source_partitions


class WorkflowRecordsTests(unittest.TestCase):
    def documents(self):
        return [
            dict(
                text="steps:\n  - name: inspect\n    run: |\n      set -e\n      python --version\n      echo hidden\n  - run: cargo --version\n",
                path=f".github/workflows/{i}.yml",
                group_id=f"g{i}",
                source_sha256=str(i) * 64,
                origin=f"https://source/{i}",
            )
            for i in range(3)
        ]

    def test_exact_lines_and_no_shell_programs(self):
        rows = extract(self.documents())
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            {r["value"] for r in rows}, {"python --version", "cargo --version"}
        )
        self.assertEqual({r["source"]["line"] for r in rows}, {5, 7})
        self.assertIsNone(direct_command("python -c 'print(1)'; rm file"))
        self.assertIsNone(direct_command("echo $(cat secret)"))

    def test_partition_preserves_whole_workflows(self):
        rows = extract(self.documents())
        partitions = source_partitions(rows)
        for result in partitions.values():
            self.assertEqual(set(result["slots"]), {0, 1})
            for group in {r["group_id"] for r in rows}:
                self.assertEqual(
                    len(
                        {
                            slot
                            for r, slot in zip(rows, result["slots"])
                            if r["group_id"] == group
                        }
                    ),
                    1,
                )
        self.assertEqual(partitions, source_partitions(rows))

    def test_heredoc_body_is_not_a_shell_command(self):
        document = self.documents()[0]
        document["text"] = (
            "steps:\n  - run: |\n      python - <<'PY'\n      from pathlib import Path\n      PY\n      python --version\n"
        )
        self.assertEqual(
            [r["value"] for r in extract([document])], ["python --version"]
        )


if __name__ == "__main__":
    unittest.main()
