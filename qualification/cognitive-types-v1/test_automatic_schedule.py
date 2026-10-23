"""Exercise loss of automatic qualification coverage as a rejected mutation."""

import importlib.util
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("hnmf_schedule", ROOT / "scripts/hepta-hnmf.py")
HNMF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HNMF)


class AutomaticScheduleTests(unittest.TestCase):
    def test_reusable_and_manual_entrypoints_cannot_replace_automatic_coverage(self):
        workflow = (ROOT / ".github/workflows/hnmf-qualification.yml").read_text()
        HNMF.verify_automatic_schedule(workflow)
        mutant = re.sub(
            r"(?ms)^on:\n.*?(?=^\S|\Z)",
            "on:\n  workflow_call:\n  workflow_dispatch:\n\n",
            workflow,
            count=1,
        )
        with self.assertRaises(SystemExit):
            HNMF.verify_automatic_schedule(mutant)

    def test_losing_either_automatic_event_is_rejected(self):
        workflow = (ROOT / ".github/workflows/hnmf-qualification.yml").read_text()
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                mutant = re.sub(
                    rf"(?ms)^  {event}:\n.*?(?=^  \w|^\S|\Z)",
                    "",
                    workflow,
                    count=1,
                )
                with self.assertRaises(SystemExit):
                    HNMF.verify_automatic_schedule(mutant)


if __name__ == "__main__":
    unittest.main()
