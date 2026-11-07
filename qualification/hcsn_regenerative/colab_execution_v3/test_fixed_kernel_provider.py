import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

import fixed_kernel_provider
from fixed_kernel_provider import FixedKernelHTTPGuard, FixedKernelGuardError, GuardedOfficialSDKProvider


class Response:
    def __init__(self, status=200, model=None, raw=None):
        self.status_code = status
        self.content = raw if raw is not None else json.dumps(
            model if model is not None else {"id": "fixed-kernel", "execution_state": "idle", "connections": 1}).encode()


class FixedKernelGuardTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.events = [], []
        self.response = Response()
        owner = self

        class FakeSession:
            def request(self, method, url, **kw):
                owner.calls.append((method, url, kw))
                if isinstance(owner.response, BaseException):
                    raise owner.response
                return owner.response

        self.session_class = FakeSession
        self.original = FakeSession.request
        self.session = FakeSession()
        self.url = "https://runtime.example/api/kernels/fixed-kernel"

    def guard(self):
        return FixedKernelHTTPGuard("https://runtime.example", "fixed-kernel",
                                   self.events.append, session_class=self.session_class)

    def test_exact_get_preserves_headers_and_none_params(self):
        headers = {"Authorization": "private-test-token", "X-Colab-Runtime-Proxy-Token": "private-test-token"}
        with self.guard():
            result = self.session.request("GET", self.url, headers=headers, params=None, timeout=10)
        self.assertIs(result, self.response)
        self.assertEqual(self.calls[0][2]["headers"], headers)
        self.assertIsNone(self.calls[0][2]["params"])
        self.assertFalse(self.calls[0][2]["allow_redirects"])
        self.assertNotIn("private-test-token", json.dumps(self.events))
        self.assertIs(self.session_class.request, self.original)

    def test_sdk_404_fallback_cannot_create_kernel(self):
        self.response = Response(404, raw=b"not found")
        def sdk_09_shape():
            model = self.session.request("GET", self.url)
            if model.status_code == 404:
                return self.session.request("POST", "https://runtime.example/api/kernels", json={"name": "python3"})
            return model
        with self.assertRaisesRegex(FixedKernelGuardError, "FIXED_KERNEL_HTTP_404"):
            with self.guard():
                sdk_09_shape()
        self.assertEqual([x[0] for x in self.calls], ["GET"])
        self.assertEqual(self.events[-1]["http_status"], 404)

    def test_all_kernel_and_session_mutations_blocked_before_delegate(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            for route in ("/api/kernels", "/api/sessions", "/api/kernels/fixed-kernel/restart"):
                with self.subTest(method=method, route=route):
                    with self.assertRaisesRegex(FixedKernelGuardError, "HTTP_MUTATION_FORBIDDEN"):
                        with self.guard():
                            self.session.request(method, "https://runtime.example" + route)
        self.assertEqual(self.calls, [])

    def test_foreign_origin_route_or_query_rejected(self):
        for url in ("https://other.example/api/kernels/fixed-kernel",
                    "https://runtime.example/api/kernels/other-kernel",
                    "https://runtime.example/api/sessions", self.url + "?token=secret"):
            with self.subTest(url=url):
                with self.assertRaises(FixedKernelGuardError):
                    with self.guard():
                        self.session.request("GET", url)
        self.assertEqual(self.calls, [])
        self.assertNotIn("secret", json.dumps(self.events))

    def test_wrong_response_id_rejected(self):
        self.response = Response(model={"id": "different-kernel"})
        with self.assertRaisesRegex(FixedKernelGuardError, "MODEL_ID_MISMATCH"):
            with self.guard():
                self.session.request("GET", self.url)

    def test_redirect_and_http_error_never_followed_or_retried(self):
        for status in (302, 401, 403, 500, 503):
            self.calls.clear()
            self.response = Response(status, raw=b"sensitive upstream body")
            with self.subTest(status=status):
                with self.assertRaisesRegex(FixedKernelGuardError, "FIXED_KERNEL_HTTP_" + str(status)):
                    with self.guard():
                        self.session.request("GET", self.url)
                self.assertEqual(len(self.calls), 1)
                self.assertFalse(self.calls[0][2]["allow_redirects"])
        self.assertNotIn("sensitive upstream body", json.dumps(self.events))

    def test_response_oversized_or_invalid_json_rejected(self):
        for raw in (b"x" * 65537, b"not-json"):
            self.response = Response(raw=raw)
            with self.assertRaises((FixedKernelGuardError, ValueError)):
                with self.guard():
                    self.session.request("GET", self.url)
            self.assertIs(self.session_class.request, self.original)

    def test_network_exception_preserved_and_sanitized(self):
        self.response = ConnectionError("https://secret.example/?token=never-export")
        with self.assertRaises(ConnectionError):
            with self.guard():
                self.session.request("GET", self.url)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.events[-1]["exception_class"], "ConnectionError")
        self.assertNotIn("never-export", json.dumps(self.events))
        self.assertIs(self.session_class.request, self.original)

    def test_nested_guard_rejected_and_original_restored(self):
        with self.guard():
            with self.assertRaisesRegex(FixedKernelGuardError, "NESTED"):
                with self.guard():
                    pass
            self.session.request("GET", self.url)
        self.assertIs(self.session_class.request, self.original)

    def test_guard_replacement_detected(self):
        with self.assertRaisesRegex(FixedKernelGuardError, "REPLACED"):
            with self.guard():
                self.session_class.request = lambda *_a, **_kw: None
        self.assertIs(self.session_class.request, self.original)

    def test_provider_keeps_authentication_and_job_identity_guard(self):
        profile = types.SimpleNamespace(endpoint="endpoint", kernel_id="fixed-kernel", session_id="client-session")
        constructed = []
        def original_factory(p):
            constructed.append(p)
            return types.SimpleNamespace(session=types.SimpleNamespace(
                endpoint=p.endpoint, kernel_id=p.kernel_id, session_id=p.session_id,
                url="https://runtime.example"))
        provider = GuardedOfficialSDKProvider(original_factory, profile, self.events.append)
        self.assertEqual(constructed, [profile])
        with self.assertRaisesRegex(FixedKernelGuardError, "JOB_IDENTITY"):
            provider.execute({"endpoint": "foreign", "kernel_id": profile.kernel_id,
                              "session_id": profile.session_id, "job_id": "job"}, "print(1)", lambda _: None)

    def test_asset_contents_and_bounded_read_write_delegated_unchanged(self):
        profile = types.SimpleNamespace(endpoint="endpoint", kernel_id="fixed-kernel", session_id="client-session")
        calls = []
        contents = object()
        base = types.SimpleNamespace(
            session=types.SimpleNamespace(endpoint=profile.endpoint, kernel_id=profile.kernel_id,
                                          session_id=profile.session_id, url="https://runtime.example"),
            contents=contents, read_bytes=lambda p: (calls.append(("read", p)), b"exact")[1],
            write_bytes=lambda p, b: calls.append(("write", p, b)),
            close=lambda: calls.append(("close",)))
        wrapped = GuardedOfficialSDKProvider(lambda _: base, profile, self.events.append)
        self.assertIs(wrapped.contents, contents)
        self.assertEqual(wrapped.read_bytes("/content/owned/part"), b"exact")
        wrapped.write_bytes("/content/owned/part", b"exact")
        wrapped.close()
        self.assertEqual(calls, [("read", "/content/owned/part"),
                                ("write", "/content/owned/part", b"exact"), ("close",)])
        self.assertEqual(self.events, [])


class PinnedLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.saved_modules = dict(sys.modules)
        self.saved_cache = dict(fixed_kernel_provider._ADAPTER_CACHE)
        fixed_kernel_provider._ADAPTER_CACHE.clear()
        sys.modules.pop("authorize_colab", None)
        for key in list(sys.modules):
            if key.startswith("_hcsn_fixed_colab_adapter_"):
                sys.modules.pop(key)
        (self.root / "authorize_colab.py").write_text("MARKER = 'exact-authorizer'\n")
        (self.root / "remote_runner.py").write_text("# compile-only fixture; never executed\n")
        (self.root / "hepta_colab.py").write_text(
            "from pathlib import Path\nRUNNER = Path(__file__).with_name('remote_runner.py')\n"
            "def lazy_authorizer():\n import authorize_colab\n return authorize_colab.MARKER\n")
        self.pins = {k: hashlib.sha256((self.root / n).read_bytes()).hexdigest()
                     for k, n in (("adapter_sha256", "hepta_colab.py"),
                                  ("runner_sha256", "remote_runner.py"),
                                  ("authorizer_sha256", "authorize_colab.py"))}

    def tearDown(self):
        for key in list(sys.modules):
            if key == "authorize_colab" or key.startswith("_hcsn_fixed_colab_adapter_"):
                sys.modules.pop(key, None)
        for key, value in self.saved_modules.items():
            if key == "authorize_colab" or key.startswith("_hcsn_fixed_colab_adapter_"):
                sys.modules[key] = value
        fixed_kernel_provider._ADAPTER_CACHE.clear()
        fixed_kernel_provider._ADAPTER_CACHE.update(self.saved_cache)
        self.temp.cleanup()

    def load(self):
        return fixed_kernel_provider.load_pinned_adapter(self.root / "hepta_colab.py", **self.pins)

    def test_exact_authorizer_lazy_import_without_sys_path_change_or_pyc(self):
        before = list(sys.path)
        module = self.load()
        self.assertEqual(module.lazy_authorizer(), "exact-authorizer")
        self.assertEqual(sys.path, before)
        self.assertFalse((self.root / "__pycache__").exists())
        self.assertIs(self.load(), module)

    def test_wrong_authorizer_pin_rejected_before_import(self):
        self.pins["authorizer_sha256"] = "0" * 64
        with self.assertRaisesRegex(FixedKernelGuardError, "SHA_MISMATCH"):
            self.load()
        self.assertNotIn("authorize_colab", sys.modules)

    def test_foreign_preloaded_authorizer_rejected(self):
        sys.modules["authorize_colab"] = types.ModuleType("authorize_colab")
        with self.assertRaisesRegex(FixedKernelGuardError, "FOREIGN_AUTHORIZER"):
            self.load()

    def test_cached_source_drift_and_module_replacement_rejected(self):
        self.load()
        (self.root / "remote_runner.py").write_text("# changed\n")
        with self.assertRaisesRegex(FixedKernelGuardError, "SHA_MISMATCH"):
            self.load()
        (self.root / "remote_runner.py").write_text("# compile-only fixture; never executed\n")
        sys.modules["authorize_colab"] = types.ModuleType("authorize_colab")
        with self.assertRaisesRegex(FixedKernelGuardError, "PINNED_MODULE_REPLACED"):
            self.load()

    def test_symlink_and_hardlink_source_rejected(self):
        auth = self.root / "authorize_colab.py"
        original = self.root / "original.py"
        auth.rename(original)
        auth.symlink_to(original)
        with self.assertRaises((FixedKernelGuardError, OSError)):
            self.load()
        auth.unlink()
        os.link(original, auth)
        with self.assertRaisesRegex(FixedKernelGuardError, "NOT_REGULAR"):
            self.load()


if __name__ == "__main__":
    unittest.main()
