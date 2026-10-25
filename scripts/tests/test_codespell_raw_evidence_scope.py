"""Constrain spelling exclusion to immutable raw Agentd runner transcripts."""

from configparser import ConfigParser
from fnmatch import fnmatchcase
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
RAW_PATTERN = (
    "*docs/modules/runtime.agentd/evidence/2026-10-23-production-composition/"
    "owner-workspace-raw/part-*.txt"
)


class CodespellRawEvidenceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = ConfigParser(interpolation=None)
        config.read(ROOT / ".codespellrc", encoding="utf-8")
        cls.patterns = [p.strip() for p in config.get("codespell", "skip").split(",")]

    def test_frozen_transcript_parts_are_excluded(self):
        self.assertIn(RAW_PATTERN, self.patterns)
        for filename in ("part-03.txt", "part-09.txt", "part-10.txt", "part-13.txt", "part-14.txt"):
            relative = (
                "docs/modules/runtime.agentd/evidence/2026-10-23-production-composition/"
                f"owner-workspace-raw/{filename}"
            )
            with self.subTest(filename=filename):
                self.assertTrue(fnmatchcase(relative, RAW_PATTERN))
                self.assertTrue(fnmatchcase("./" + relative, RAW_PATTERN))

    def test_prose_source_and_other_evidence_not_excluded(self):
        checked = (
            "docs/modules/runtime.agentd/README.md",
            "docs/modules/runtime.agentd/evidence/2026-10-23-production-composition/README.md",
            "docs/modules/runtime.agentd/evidence/2026-10-23-production-composition/owner-workspace-raw/README.md",
            "docs/modules/runtime.agentd/evidence/2026-10-23-production-composition/owner-workspace-raw/part-03.txt.bak",
            "docs/modules/runtime.agentd/evidence/2026-10-22-production-composition/owner-workspace-raw/part-03.txt",
            "codex-rs/hepta-agent-loop/src/lib.rs",
        )
        for relative in checked:
            with self.subTest(relative=relative):
                self.assertFalse(fnmatchcase(relative, RAW_PATTERN))
                self.assertFalse(fnmatchcase("./" + relative, RAW_PATTERN))


if __name__ == "__main__":
    unittest.main()
