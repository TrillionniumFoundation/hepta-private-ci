"""Actual browser/file composition; blocked browser is an explicit NOT_RUN."""

import os
from pathlib import Path
import socket
import tempfile
import unittest

from browser_family import BrowserUnavailable, launch_browser
from composite_family import CompositeDestination
from run import macro
from sqlite_destination import BudgetExhausted


class CompositeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
            from playwright.sync_api import sync_playwright

            cls.playwright = sync_playwright().start()
            cls.browser = launch_browser(
                cls.playwright, os.environ.get("ACT3_BROWSER_EXECUTABLE")
            )
        except (ImportError, BrowserUnavailable, OSError) as error:
            if cls.playwright:
                cls.playwright.stop()
            raise unittest.SkipTest(
                f"NOT_RUN_COMPOSITE_BROWSER: {type(error).__name__}: {str(error)[:300]}"
            )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def task(self, length=4, fault="normal", version=1):
        return {
            "id": f"mixed/{length}/{fault}/{version}",
            "goals": [f"goal-{i}" for i in range(length)],
            "fault": fault,
            "version": version,
        }

    def test_actual_mixed_effects_and_faults(self):
        for length, fault, version in (
            (3, "normal", 1),
            (4, "normal", 2),
            (4, "lost_reply", 1),
            (4, "partial_failure", 2),
            (4, "opaque_after_apply", 1),
        ):
            with (
                self.subTest(length=length, fault=fault, version=version),
                tempfile.TemporaryDirectory() as folder,
            ):
                task = self.task(length, fault, version)
                destination = CompositeDestination(
                    Path(folder) / "owners", task, self.browser
                )
                claimed = False
                try:
                    for _ in range(2 * destination.budget):
                        action = macro(destination)
                        if action == "stop":
                            view = destination.inspect()
                            claimed = bool(view and view["complete"])
                            break
                        getattr(destination, action)()
                except BudgetExhausted:
                    pass
                finally:
                    row = destination.score(claimed)
                self.assertEqual(
                    row["primitive_calls"],
                    sum(r["primitive_calls"] for r in row["children"].values()),
                )
                self.assertLessEqual(row["primitive_calls"], destination.budget)
                self.assertFalse(row["false_success"])
                self.assertEqual(row["duplicate_effects"], 0)
                self.assertEqual(row["complete"], fault != "opaque_after_apply")
                self.assertEqual(row["claimed_success"], row["complete"])
                self.assertGreater(row["dom_actions"], 0)
                for record in row["effect_records"]:
                    self.assertEqual(
                        record["goal"], task["goals"][record["global_key"]]
                    )
                if fault == "normal":
                    self.assertEqual(
                        [
                            e["global_index"]
                            for e in row["events"]
                            if e["action"] == "ensure"
                        ],
                        list(range(length)),
                    )
                if fault == "lost_reply":
                    self.assertEqual(row["lost_replies"], 2)

    def test_reservation_precedes_any_child_mutation_or_read(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = CompositeDestination(
                Path(folder) / "owners", self.task(), self.browser
            )
            try:
                destination.inspect()
                prior = destination.calls
                destination.budget = prior + 1
                with self.assertRaises(BudgetExhausted):
                    destination.ensure()
                with self.assertRaises(BudgetExhausted):
                    destination.inspect()
                self.assertEqual(destination.calls, prior)
                for child in destination.children.values():
                    self.assertEqual(child.owner.audit()["effect_count"], 0)
                    self.assertFalse(list((child.owner.path / "staged").iterdir()))
            finally:
                destination.close()


if __name__ == "__main__":
    unittest.main()
