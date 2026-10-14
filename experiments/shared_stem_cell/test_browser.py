"""Real Chromium and MCP lifecycle regressions, confined to a private fixture."""
import unittest

from experiments.shared_stem_cell.browser_loop import BrowserFixture, McpClient, action_frame
from experiments.shared_stem_cell.execution import InputError


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.local = BrowserFixture()
        try:
            cls.remote = McpClient()
        except Exception:
            cls.local.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.remote.close()
        cls.local.close()

    def setUp(self):
        if self.local.quarantined:
            self.local.reconcile()
        self.local.reset()
        self.remote.call("fixture_reset", {})

    def test_real_reset_reinstalls_handlers(self):
        for text in ("first", "second", "third"):
            self.local.reset()
            result = self.local.program(text)
            self.assertEqual(result["state"]["result"], text)
            self.assertEqual(result["state"]["count"], 1)

    def test_replay_cannot_enter(self):
        request = action_frame(self.local.observe(), "fill", "once")
        self.local.action(request)
        with self.assertRaises(InputError):
            self.local.action(request)
        self.assertEqual(self.local.sequence, 1)

    def test_stale_target(self):
        request = action_frame(self.local.observe(), "fill", "forbidden")
        request["target_digest"] = "0" * 64
        with self.assertRaises(InputError):
            self.local.action(request)
        self.assertEqual(self.local.observe()["state"]["value"], "")

    def test_stale_observation(self):
        request = action_frame(self.local.observe(), "click", "")
        self.local.page.get_by_role("textbox", name="Task value", exact=True).fill("external change")
        with self.assertRaises(InputError):
            self.local.action(request)
        self.assertEqual(self.local.observe()["state"]["count"], 0)

    def test_revocation_between_program_steps(self):
        original = self.local.action
        def revoke_after_fill(request):
            result = original(request)
            if request["op"] == "fill":
                self.local.revoke()
            return result
        self.local.action = revoke_after_fill
        try:
            with self.assertRaises(InputError):
                self.local.program("not saved")
            state = self.local.observe()["state"]
            self.assertEqual(state["value"], "not saved")
            self.assertEqual(state["count"], 0)
        finally:
            self.local.action = original

    def test_unknown_effect_cannot_reset_or_replay(self):
        self.local.action(action_frame(self.local.observe(), "fill", "one commit"))
        request = action_frame(self.local.observe(), "click", "")
        self.local.fault_after_effect = True
        with self.assertRaises(RuntimeError):
            self.local.action(request)
        with self.assertRaises(InputError):
            self.local.reset()
        with self.assertRaises(InputError):
            self.local.action(request)
        self.assertEqual(self.local.observe()["state"]["count"], 1)
        self.assertEqual(self.local.reconcile()["status"], "applied")
        with self.assertRaises(InputError):
            self.local.action(request)
        self.assertEqual(self.local.observe()["state"]["count"], 1)

    def test_effect_postcondition_is_required(self):
        self.local.page.evaluate("() => document.querySelector('#save').onclick = null")
        request = action_frame(self.local.observe(), "click", "")
        with self.assertRaises(InputError):
            self.local.action(request)
        self.assertTrue(self.local.quarantined)
        self.assertEqual(self.local.reconcile()["status"], "unknown")
        # Deliberately replace this disposable test owner, never claim recovery.
        self.local.close()
        type(self).local = BrowserFixture()

    def test_actual_mcp_steps_and_program(self):
        for op, value in (("fill", "over stdio"), ("click", "")):
            observed = self.remote.call("fixture_observe", {})
            self.remote.call("fixture_action", action_frame(observed, op, value))
        result = self.remote.call("fixture_observe", {})
        self.assertEqual(result["state"]["result"], "over stdio")
        self.remote.call("fixture_reset", {})
        result = self.remote.call("fixture_program", {"value": "batched MCP"})
        self.assertEqual(result["state"]["result"], "batched MCP")
        self.assertEqual(result["state"]["count"], 1)

    def test_mcp_revoke_same_effect_policy(self):
        observed = self.remote.call("fixture_observe", {})
        self.remote.call("fixture_revoke", {})
        with self.assertRaises(InputError):
            self.remote.call("fixture_action", action_frame(observed, "fill", "forbidden"))
        self.assertEqual(self.remote.call("fixture_observe", {})["state"]["value"], "")

    def test_mcp_unknown_tool_rejected(self):
        with self.assertRaises(InputError):
            self.remote.call("shell_exec", {"command": "not supported"})


if __name__ == "__main__":
    unittest.main()
