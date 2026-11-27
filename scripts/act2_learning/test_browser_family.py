"""Real-browser tests skip explicitly when unavailable; CLI remains a failing gate."""

import os
from pathlib import Path
import socket
import tempfile
import unittest

from browser_family import BrowserDestination, BrowserUnavailable, launch_browser
from run import macro
from sqlite_destination import BudgetExhausted


class BrowserIntegrationTests(unittest.TestCase):
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
                f"NOT_RUN_BROWSER: {type(error).__name__}: {str(error)[:400]}"
            )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def task(self, version, fault):
        return {
            "id": f"browser-test/{version}/{fault}",
            "goals": ["one", "two", "three"],
            "fault": fault,
            "version": version,
        }

    def test_real_dom_owner_effects_and_faults(self):
        for version in (1, 2):
            for fault in (
                "normal",
                "lost_reply",
                "partial_failure",
                "opaque_after_apply",
            ):
                with (
                    self.subTest(version=version, fault=fault),
                    tempfile.TemporaryDirectory() as folder,
                ):
                    destination = BrowserDestination(
                        Path(folder) / "owner", self.task(version, fault), self.browser
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
                    self.assertFalse(row["false_success"])
                    self.assertEqual(row["duplicate_effects"], 0)
                    self.assertEqual(row["complete"], fault != "opaque_after_apply")
                    self.assertEqual(row["claimed_success"], row["complete"])
                    self.assertGreater(row["dom_actions"], 0)
                    self.assertGreater(row["network_requests"], 0)
                    if fault == "lost_reply":
                        self.assertEqual(row["lost_replies"], 1)
                        self.assertGreaterEqual(row["network_failures"], 1)

    def test_retry_and_parameter_mismatch_go_through_real_form(self):
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as folder:
                task = self.task(version, "normal")
                destination = BrowserDestination(
                    Path(folder) / "owner", task, self.browser
                )
                try:
                    destination.inspect()
                    destination.stage()
                    destination.apply()
                    destination.apply()  # Same invocation through DOM: no additional effect.
                    self.assertEqual(destination.owner.audit()["effect_count"], 1)
                    destination._charge("adversarial_parameter_mismatch")
                    destination._fill(1, task["goals"][1], task["id"] + ":0")
                    response = destination._click("apply")
                    self.assertEqual(response["http_status"], 400)
                    self.assertEqual(destination.owner.audit()["effect_count"], 1)
                finally:
                    destination.close()

    def test_scorer_rejects_forged_dom_success(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = BrowserDestination(
                Path(folder) / "owner", self.task(1, "normal"), self.browser
            )
            destination.page.locator("#result").evaluate(
                "e => e.textContent=JSON.stringify({complete:true})"
            )
            row = destination.score(True)
            self.assertFalse(row["complete"])
            self.assertTrue(row["false_success"])
            self.assertEqual(row["effect_count"], 0)


if __name__ == "__main__":
    unittest.main()
