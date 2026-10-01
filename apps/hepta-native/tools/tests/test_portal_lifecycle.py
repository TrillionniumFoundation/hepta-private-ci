"""Deterministic portal callback/deadline tests without a physical session bus."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


class Variant:
    def __init__(self, _signature, value):
        self.value = value

    def unpack(self):
        return self.value


class PortalLifecycleTests(unittest.TestCase):
    def exercise(self, name, dispatch_seconds, early_response=False):
        now = [0.0]
        timers, removed, closed, subscriptions = [], [], [], []
        loop_runs = []

        class Loop:
            def quit(self):
                pass

            def run(self):
                loop_runs.append(True)
                timers[-1][1]()

        class Connection:
            def get_unique_name(self):
                return ":1.99"

            def signal_subscribe(self, *args):
                subscriptions.append(args)
                return len(subscriptions)

            def signal_unsubscribe(self, _subscription):
                pass

            def reply(self):
                now[0] += dispatch_seconds
                if early_response:
                    callback = subscriptions[0][-2]
                    callback(None, None, None, None, None, Variant("", (0, {"uris": ["file:///chosen"]})), None)
                return Variant("", (subscriptions[0][3],))

            def call_sync(self, *args):
                if args[3] == "Close":
                    closed.append(args[1])
                    return None
                return self.reply()

            def call_with_unix_fd_list_sync(self, *args):
                return self.reply(), None

        connection = Connection()

        def timeout_add(delay, callback):
            timers.append((delay, callback))
            return len(timers)

        glib = types.SimpleNamespace(MainLoop=Loop, Variant=Variant,
            VariantType=types.SimpleNamespace(new=lambda value: value),
            SOURCE_REMOVE=False, timeout_add=timeout_add, source_remove=removed.append)
        gio = types.SimpleNamespace(BusType=types.SimpleNamespace(SESSION=0),
            DBusSignalFlags=types.SimpleNamespace(NONE=0),
            DBusCallFlags=types.SimpleNamespace(NONE=0),
            UnixFDList=types.SimpleNamespace(new=lambda: types.SimpleNamespace(append=lambda fd: fd)),
            bus_get_sync=lambda *_args: connection)
        gi = types.ModuleType("gi")
        gi.require_version = lambda *_args: None
        repository = types.ModuleType("gi.repository")
        repository.Gio, repository.GLib = gio, glib
        path = Path(__file__).resolve().parents[2] / "portal" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"portal_test_{name}", path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
            spec.loader.exec_module(module)
        with mock.patch.object(module.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(module.sys, "argv", [str(path), "open"]), \
             mock.patch.object(module.sys, "stdout", new=types.SimpleNamespace(write=lambda _v: None, flush=lambda: None)), \
             mock.patch.object(module.sys, "stderr", new=types.SimpleNamespace(write=lambda _v: None, flush=lambda: None)):
            code = module.main()
        return module, code, timers, closed, loop_runs

    def test_dispatch_consumes_total_budget_and_timeout_closes_request(self):
        for name in ["open_uri", "file_chooser"]:
            with self.subTest(adapter=name):
                module, code, timers, closed, runs = self.exercise(name, 15.0)
                self.assertEqual(code, 124)
                self.assertEqual(timers[0][0], (module.MAXIMUM_SECONDS - 15) * 1000)
                self.assertEqual(len(closed), 1)
                self.assertEqual(len(runs), 1)

    def test_expired_dispatch_closes_without_starting_a_fresh_loop(self):
        for name in ["open_uri", "file_chooser"]:
            with self.subTest(adapter=name):
                _, code, timers, closed, runs = self.exercise(name, 200.0)
                self.assertEqual(code, 124)
                self.assertEqual(timers, [])
                self.assertEqual(len(closed), 1)
                self.assertEqual(runs, [])

    def test_response_during_dispatch_does_not_reenter_the_main_loop(self):
        for name in ["open_uri", "file_chooser"]:
            with self.subTest(adapter=name):
                _, code, timers, closed, runs = self.exercise(name, 0.0, early_response=True)
                self.assertEqual(code, 0)
                self.assertEqual((timers, closed, runs), ([], [], []))


if __name__ == "__main__":
    unittest.main()
