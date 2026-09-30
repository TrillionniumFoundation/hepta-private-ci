from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeGraphAuthoringExportOnceTests(unittest.TestCase):
    def test_export_formatted_compile_fix_in_read_only_ci(self) -> None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            self.skipTest("one-shot authoring export only runs in GitHub Actions")

        runner_temp = os.environ.get("RUNNER_TEMP")
        self.assertIsNotNone(runner_temp)
        evidence = Path(runner_temp) / "knowledge-graph-metadata" / "authoring"
        tree = evidence / "tree"
        tree.mkdir(parents=True, exist_ok=True)

        lib = ROOT / "codex-rs/hepta-kg/src/lib.rs"
        text = lib.read_text(encoding="utf-8")
        anchor = "pub use resource::measure_generation_v2;\n"
        insertion = (
            "pub(crate) use resource::measure_query_edge_bytes_v2;\n"
            "pub(crate) use resource::measure_query_result_base_bytes_v2;\n"
        )
        if insertion not in text:
            self.assertIn(anchor, text)
            lib.write_text(text.replace(anchor, insertion + anchor, 1), encoding="utf-8")

        subprocess.run(
            [
                "cargo",
                "fmt",
                "--package",
                "codex-hepta-kg",
                "--package",
                "codex-hepta-memory",
                "--package",
                "codex-hepta-prompt-registry",
                "--package",
                "codex-hepta-prompt-optimizer",
                "--package",
                "codex-hepta-agentd",
            ],
            cwd=ROOT / "codex-rs",
            check=True,
        )

        changed = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACMRT"],
            cwd=ROOT,
            text=True,
        ).splitlines()
        self.assertIn("codex-rs/hepta-kg/src/lib.rs", changed)
        self.assertGreater(len(changed), 1)
        for relative in changed:
            source = ROOT / relative
            destination = tree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        patch = subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT
        )
        (evidence / "authoring.patch").write_bytes(patch)
        (evidence / "paths.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
        (evidence / "source.txt").write_text(
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
