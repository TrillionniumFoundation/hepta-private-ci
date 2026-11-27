"""Process-local guard for an already authenticated, fixed Colab kernel.

The installed account, session, job adapter and runner remain unchanged.  During
OfficialSDKProvider.execute only the exact kernel model GET is allowed.  A 404
is rejected before jupyter-kernel-client can clear its model and auto-create a
replacement kernel.  No response body, URL, header value or exception message is
written to the trace.  This module performs no provider operation on import.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import traceback
import types
from urllib.parse import urlsplit


class FixedKernelGuardError(Exception):
    """Only a fixed, non-sensitive error code is stored in args."""


_ADAPTER_CACHE = {}


def require(condition, code):
    if not condition:
        raise FixedKernelGuardError(code)


def _pinned_bytes(path, expected):
    """Read one regular file without following any symlink component."""
    path = Path(path)
    require(path.is_absolute() and str(path) == os.path.normpath(str(path))
            and ".." not in path.parts, "INSTALLED_SOURCE_PATH_INVALID")
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
            "INSTALLED_SOURCE_HASH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        source_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        with os.fdopen(source_fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and before.st_size <= 1048576, "INSTALLED_SOURCE_NOT_REGULAR")
            raw = stream.read(1048577)
            after = os.fstat(stream.fileno())
        version = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(version(before) == version(after) and len(raw) == before.st_size,
                "INSTALLED_SOURCE_CHANGED_DURING_READ")
        require(hashlib.sha256(raw).hexdigest() == expected, "INSTALLED_SOURCE_SHA_MISMATCH")
        return raw
    finally:
        os.close(fd)


def load_pinned_adapter(adapter_path, *, adapter_sha256, runner_sha256,
                        authorizer_sha256):
    """Memory-import exact installed adapter and its exact authorizer dependency.

    This fixes the standalone entrypoint's missing release import path without
    trusting another authorize_colab on sys.path, changing the installed files,
    reading credentials, creating a Ledger or constructing a provider. The
    authorizer is registered under its required lazy-import name only after its
    exact bytes have been verified. Foreign preloaded modules are rejected.
    """
    path = Path(adapter_path)
    sources = {
        "adapter": (path, adapter_sha256),
        "runner": (path.with_name("remote_runner.py"), runner_sha256),
        "authorizer": (path.with_name("authorize_colab.py"), authorizer_sha256),
    }
    raw = {key: _pinned_bytes(p, sha) for key, (p, sha) in sources.items()}
    key = (str(path), adapter_sha256, runner_sha256, authorizer_sha256)
    cached = _ADAPTER_CACHE.get(key)
    if cached is not None:
        adapter, authorizer = cached
        require(sys.modules.get("authorize_colab") is authorizer
                and sys.modules.get(adapter.__name__) is adapter,
                "PINNED_MODULE_REPLACED")
        return adapter
    require("authorize_colab" not in sys.modules, "FOREIGN_AUTHORIZER_ALREADY_LOADED")
    name = "_hcsn_fixed_colab_adapter_" + adapter_sha256[:20]
    require(name not in sys.modules, "FOREIGN_ADAPTER_ALREADY_LOADED")
    authorizer = types.ModuleType("authorize_colab")
    authorizer.__file__ = str(sources["authorizer"][0])
    adapter = types.ModuleType(name)
    adapter.__file__ = str(path)
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules["authorize_colab"] = authorizer
    sys.modules[name] = adapter
    try:
        exec(compile(raw["authorizer"], authorizer.__file__, "exec"), authorizer.__dict__)
        exec(compile(raw["adapter"], adapter.__file__, "exec"), adapter.__dict__)
        require(Path(adapter.RUNNER) == sources["runner"][0], "ADAPTER_RUNNER_PATH_CHANGED")
        adapter._hcsn_verified_source_pins = {
            k: {"path": str(p), "sha256": sha} for k, (p, sha) in sources.items()
        }
    except BaseException:
        sys.modules.pop(name, None)
        sys.modules.pop("authorize_colab", None)
        raise
    finally:
        sys.dont_write_bytecode = old_bytecode
    _ADAPTER_CACHE[key] = (adapter, authorizer)
    return adapter


def safe_exception(exc):
    name = type(exc).__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", name):
        name = "OtherException"
    result = {
        "exception_class": name,
        "traceback_locations": [
            {"file": Path(frame.filename).name, "line": frame.lineno,
             "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)[-16:]
        ],
    }
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        result["http_status"] = status
    if isinstance(exc, FixedKernelGuardError):
        result["guard_code"] = exc.args[0]
    return result


class FixedKernelHTTPGuard(AbstractContextManager):
    """Allow exact fixed-kernel GET; prohibit every kernel/session mutation.

    ``session_class`` is injectable only for local tests. Production callers
    leave it unset to guard requests.sessions.Session.request in this process.
    Authentication is constructed before entering this scope; no account guard
    is replaced and no authorization header is added, removed or rewritten.
    """

    def __init__(self, runtime_url, kernel_id, sink, *, session_class=None,
                 clock=time.monotonic):
        origin = urlsplit(runtime_url)
        require(origin.scheme == "https" and bool(origin.hostname)
                and origin.username is None and origin.password is None
                and origin.port in (None, 443) and not origin.query
                and not origin.fragment, "INVALID_FIXED_RUNTIME_ORIGIN")
        require(isinstance(kernel_id, str) and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", kernel_id),
            "INVALID_FIXED_KERNEL_ID")
        self.origin = origin
        self.kernel_id = kernel_id
        self.expected_path = origin.path.rstrip("/") + "/api/kernels/" + kernel_id
        self.sink, self.clock = sink, clock
        self.session_class = session_class
        self.calls = 0
        self.original = None
        self.wrapped = None

    def __enter__(self):
        if self.session_class is None:
            from requests.sessions import Session
            self.session_class = Session
        original = self.session_class.request
        require(not getattr(original, "_hcsn_fixed_kernel_guard", False),
                "NESTED_FIXED_KERNEL_GUARD")
        self.original = original
        owner = self

        def guarded(session, method, url, **kwargs):
            owner.calls += 1
            started = owner.clock()
            record = {"schema": "hcsn-colab-fixed-kernel-http-v2",
                      "sequence": owner.calls, "stage": "before_dispatch",
                      "method": str(method).upper() if str(method).upper() in
                                ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
                                else "OTHER",
                      "request_delegated": False,
                      "fixed_kernel_id": owner.kernel_id}
            try:
                target = urlsplit(url)
                require(record["method"] == "GET", "HTTP_MUTATION_FORBIDDEN")
                require(target.scheme == owner.origin.scheme
                        and target.netloc == owner.origin.netloc
                        and target.username is None and target.password is None,
                        "FOREIGN_HTTP_ORIGIN_FORBIDDEN")
                require(target.path == owner.expected_path and not target.query
                        and not target.fragment, "NON_FIXED_KERNEL_ROUTE_FORBIDDEN")
                params = kwargs.get("params")
                require(params is None or isinstance(params, dict), "HTTP_PARAMS_SHAPE_INVALID")
                record.update(route="/api/kernels/" + owner.kernel_id,
                              authorization_header_present=bool(
                                  (kwargs.get("headers") or {}).get("Authorization")),
                              proxy_header_present=bool(
                                  (kwargs.get("headers") or {}).get("X-Colab-Runtime-Proxy-Token")),
                              authuser_parameter_present=bool(
                                  (params or {}).get("authuser") == "0"),
                              redirects_allowed=False)
                owner.sink(dict(record))
                # This independent guard never follows a redirect with runtime
                # credentials. The installed SDK implementation is not edited.
                kwargs["allow_redirects"] = False
                record["request_delegated"] = True
                response = original(session, method, url, **kwargs)
                status = response.status_code
                require(type(status) is int and 100 <= status <= 599,
                        "HTTP_STATUS_INVALID")
                raw = response.content
                require(isinstance(raw, bytes) and len(raw) <= 65536,
                        "KERNEL_MODEL_RESPONSE_OVERSIZED")
                record.update(http_status=status, response_bytes=len(raw),
                              response_sha256=hashlib.sha256(raw).hexdigest())
                require(status == 200, "FIXED_KERNEL_HTTP_" + str(status))
                model = json.loads(raw)
                require(isinstance(model, dict) and model.get("id") == owner.kernel_id,
                        "FIXED_KERNEL_MODEL_ID_MISMATCH")
                state = model.get("execution_state")
                if isinstance(state, str) and re.fullmatch(r"[a-z_]{1,32}", state):
                    record["kernel_execution_state"] = state
                if type(model.get("connections")) is int:
                    record["kernel_connections"] = model["connections"]
                record["stage"] = "returned_verified_fixed_kernel"
                return response
            except BaseException as exc:
                record.update(stage="failed_closed", **safe_exception(exc))
                raise
            finally:
                record["elapsed_seconds"] = max(0.0, owner.clock() - started)
                owner.sink(dict(record))

        guarded._hcsn_fixed_kernel_guard = True
        self.wrapped = guarded
        self.session_class.request = guarded
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        unchanged = self.session_class.request is self.wrapped
        self.session_class.request = self.original
        require(unchanged, "HTTP_GUARD_REPLACED_DURING_EXECUTION")
        return False


class GuardedOfficialSDKProvider:
    """Delegate to the pinned provider, adding only a local execution guard."""

    def __init__(self, original_factory, profile, sink):
        self.underlying = original_factory(profile)
        self.profile = profile
        self.sink = sink
        require(self.underlying.session.endpoint == profile.endpoint
                and self.underlying.session.kernel_id == profile.kernel_id
                and self.underlying.session.session_id == profile.session_id,
                "GUARDED_PROVIDER_FIXED_IDENTITY_MISMATCH")

    def execute(self, job, code_wrapper, output_hook):
        require(all(job[k] == getattr(self.profile, k)
                    for k in ("endpoint", "kernel_id", "session_id")),
                "GUARDED_EXECUTION_JOB_IDENTITY_MISMATCH")
        event = {"schema": "hcsn-colab-guarded-sdk-execute-v2",
                 "job_id": job["job_id"], "stage": "starting",
                 "code_wrapper_sha256": hashlib.sha256(code_wrapper.encode()).hexdigest(),
                 "implicit_kernel_creation_allowed": False}
        self.sink(dict(event))
        try:
            with FixedKernelHTTPGuard(self.underlying.session.url,
                                      self.profile.kernel_id, self.sink):
                result = self.underlying.execute(job, code_wrapper, output_hook)
            event["stage"] = "sdk_returned"
            if isinstance(result, list):
                raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
                event.update(sdk_output_count=len(result), sdk_outputs_sha256=hashlib.sha256(raw).hexdigest(),
                             sdk_error_classes=[x.get("ename") if isinstance(x.get("ename"), str)
                                                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", x["ename"])
                                                else "OtherException"
                                                for x in result if isinstance(x, dict)
                                                and x.get("output_type") == "error"])
            return result
        except BaseException as exc:
            event.update(stage="sdk_exception", **safe_exception(exc))
            raise
        finally:
            self.sink(dict(event))

    def read_bytes(self, path):
        return self.underlying.read_bytes(path)

    @property
    def contents(self):
        """The original bounded Contents client, for audited asset GET/PUT."""
        return self.underlying.contents

    def write_bytes(self, path, data):
        return self.underlying.write_bytes(path, data)

    def close(self):
        return self.underlying.close()


def guarded_provider_factory(adapter_module, sink):
    """Use with Engine(..., provider_factory=guarded_provider_factory(m, sink))."""
    original = adapter_module.OfficialSDKProvider
    return lambda profile: GuardedOfficialSDKProvider(original, profile, sink)
