"""Trace actual primary-token Win32 calls in a separate, owned fixture.

The original cmd experiment and all of its pass predicates remain unchanged.
This receipt is diagnostic evidence, never a production qualification result.
"""

import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import traceback
import uuid

from probe import _observe_child_stdio, cleanup_fixture, dacl, fixture
from win32_api import (
    Api,
    DELETE,
    DWORD,
    HANDLE,
    PTR,
    READ,
    SecurityCapabilities,
    StartupInfo,
    StartupInfoEx,
    ProcessInfo,
    TOKEN_DUPLICATE,
    TOKEN_QUERY,
    WAIT_TIMEOUT,
    WRITE,
    require,
)


def create_suspended(api, package_sid, binary, workspace, lpac, handles):
    """Same security-capability/LPAC/explicit-stdio attributes as cmd probe."""
    require(
        len(handles) == 3 and len(set(handles)) == 3,
        "three distinct owned stdio handles",
    )
    require(
        all(value not in (None, 0, PTR(-1).value) for value in handles),
        "valid stdio handles",
    )
    require(
        binary.parent == workspace and binary.name == "child-trace.exe",
        "fixed owned executable",
    )
    count = 3 if lpac else 2
    size = C.c_size_t()
    api.InitializeProcThreadAttributeList(None, count, 0, C.byref(size))
    require(
        C.get_last_error() == 122 and 0 < size.value <= 65536, "bounded attribute list"
    )
    attributes = C.create_string_buffer(size.value)
    api.checked(
        api.InitializeProcThreadAttributeList(attributes, count, 0, C.byref(size)),
        "trace attributes",
    )
    try:
        capabilities = SecurityCapabilities(package_sid, None, 0, 0)
        api.checked(
            api.UpdateProcThreadAttribute(
                attributes,
                0,
                0x20009,
                C.byref(capabilities),
                C.sizeof(capabilities),
                None,
                None,
            ),
            "trace security capabilities",
        )
        opt_out = DWORD(1)
        if lpac:
            api.checked(
                api.UpdateProcThreadAttribute(
                    attributes,
                    0,
                    0x2000F,
                    C.byref(opt_out),
                    C.sizeof(opt_out),
                    None,
                    None,
                ),
                "trace all packages opt-out",
            )
        inherited = (HANDLE * 3)(*handles)
        api.checked(
            api.UpdateProcThreadAttribute(
                attributes, 0, 0x20002, inherited, C.sizeof(inherited), None, None
            ),
            "trace exact stdio list",
        )
        system = C.create_unicode_buffer(32768)
        length = api.GetSystemDirectoryW(system, len(system))
        require(0 < length < len(system), "system directory")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        require(
            local_app_data
            and "\0" not in local_app_data
            and Path(local_app_data).is_absolute(),
            "LOCALAPPDATA must identify an absolute profile path",
        )
        environment = C.create_unicode_buffer(
            "\0".join(
                [
                    f"LOCALAPPDATA={local_app_data}",
                    f"SystemRoot={Path(system.value).parent}",
                    f"TEMP={workspace}",
                    f"TMP={workspace}",
                    f"windir={Path(system.value).parent}",
                    "",
                    "",
                ]
            )
        )
        command = C.create_unicode_buffer(f'"{binary}"')
        startup, process = StartupInfoEx(), ProcessInfo()
        startup.StartupInfo.cb = C.sizeof(startup)
        startup.StartupInfo.dwFlags = 0x100
        (
            startup.StartupInfo.hStdInput,
            startup.StartupInfo.hStdOutput,
            startup.StartupInfo.hStdError,
        ) = handles
        startup.lpAttributeList = C.cast(attributes, PTR)
        api.checked(
            api.CreateProcessW(
                str(binary),
                command,
                None,
                None,
                True,
                0x80000 | 0x4 | 0x08000000 | 0x400,
                environment,
                str(workspace),
                C.cast(C.byref(startup), C.POINTER(StartupInfo)),
                C.byref(process),
            ),
            "CreateProcessW actual diagnostic child",
        )
        return process
    finally:
        api.DeleteProcThreadAttributeList(attributes)


def run_case(api, lpac, user, base, executable, executable_sha256):
    record = {
        "mode": "lpac" if lpac else "appcontainer",
        "diagnostic_only": True,
        "production_qualification": False,
        "child_wait_budget_ms": 5000,
    }
    profile = "hepta.ci.child-trace." + uuid.uuid4().hex
    package_sid, token = PTR(), HANDLE()
    created = False
    root = process = capture = None
    try:
        code = api.CreateAppContainerProfile(
            profile, profile, "Owned native child trace", None, 0, C.byref(package_sid)
        )
        require(
            code == 0 and package_sid.value is not None, f"fresh profile HRESULT {code}"
        )
        created = True
        package = api.sid_text(package_sid)
        root = Path(tempfile.mkdtemp(prefix="hepta-child-trace-owned-"))
        prepared = fixture(api, root, user, package, base)
        workspace = prepared["workspace"]
        record["parent_fixture_security"] = prepared["security"]
        # Separate allowed targets isolate inherited vs explicit package ACE
        # and default Medium vs explicit Low labels. The original denied
        # targets and all original cmd experiment objects are unmodified.
        for inherited in (True, False):
            for low in (False, True):
                name = f"trace-{'inherited' if inherited else 'explicit'}-{'low' if low else 'medium'}.txt"
                path = workspace / name
                path.write_bytes(b"diagnostic-owned-target")
                if not inherited:
                    api.set_dacl(path, dacl(user, package, READ | WRITE | DELETE))
                if low:
                    api.set_label(path, "LW")
                facts = api.security_facts(path)
                if low:
                    require(
                        len(facts["labels"]) == 1
                        and facts["labels"][0]["sid"] == "S-1-16-4096"
                        and facts["labels"][0]["mask"] == 1,
                        "exact Low no-write-up comparison label",
                    )
                else:
                    require(
                        facts["labels"] == [],
                        "original unlabeled Medium comparison target",
                    )
                record["parent_fixture_security"]["workspace/" + name] = facts
        binary = workspace / "child-trace.exe"
        shutil.copyfile(executable, binary)
        require(
            hashlib.sha256(binary.read_bytes()).hexdigest() == executable_sha256,
            "copied executable identity",
        )
        api.set_dacl(binary, dacl(user, package, READ))
        record["parent_fixture_security"]["workspace/child-trace.exe"] = (
            api.security_facts(binary)
        )
        capture = api.open_child_stdio(workspace)
        process = create_suspended(
            api, package_sid, binary, workspace, lpac, capture["handles"]
        )
        api.close_child_stdio(capture)
        api.checked(
            api.OpenProcessToken(
                process.hProcess, TOKEN_QUERY | TOKEN_DUPLICATE, C.byref(token)
            ),
            "trace child token",
        )
        facts = api.token_facts(token)
        record["parent_observed_child_token"] = facts
        require(
            facts
            == {
                "is_appcontainer": 1,
                "package_sid": package,
                "integrity_sid": "S-1-16-4096",
                "user_sid": user,
                "capability_count": 0,
            },
            "actual trace child token identity",
        )
        access = api.lpac_access_check(token)
        record["parent_observed_package_access"] = access
        require(
            access["access_status"]
            and access["granted_access"] == (2 if lpac else 3)
            and access["privilege_count"] == 0,
            "actual trace child package mode",
        )
        require(api.ResumeThread(process.hThread) == 1, "resume trace child once")
        wait = api.WaitForSingleObject(process.hProcess, 5000)
        record["child_wait_result"] = wait
        require(wait == 0, "trace child five-second bound")
        exit_code = DWORD()
        api.checked(
            api.GetExitCodeProcess(process.hProcess, C.byref(exit_code)),
            "trace exit code",
        )
        record["child_exit_code"] = exit_code.value
        record["child_stdio"] = _observe_child_stdio(capture)
        stdout = capture["directory"] / "stdout.bin"
        with stdout.open("rb") as trace_stream:
            raw = trace_stream.read(65537)
        require(len(raw) <= 65536, "bounded actual child trace output")
        record["child_records"] = [
            json.loads(line) for line in raw.decode("ascii").splitlines()
        ]
        record["child_trace_completed"] = bool(record["child_records"]) and record[
            "child_records"
        ][-1] == {
            "kind": "complete",
            "diagnostic_only": True,
        }
        record["executable_unchanged"] = (
            hashlib.sha256(binary.read_bytes()).hexdigest() == executable_sha256
        )
        require(record["executable_unchanged"], "owned executable drift")
        record["status"] = "observed"
    except Exception as error:
        record["status"] = "trace_error"
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        record["traceback"] = traceback.format_exc()
    finally:
        cleanup = {}
        if process is not None:
            try:
                if api.WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT:
                    api.checked(
                        api.TerminateProcess(process.hProcess, 71),
                        "terminate owned trace child",
                    )
                    require(
                        api.WaitForSingleObject(process.hProcess, 5000) == 0,
                        "trace child terminated",
                    )
                api.close(process.hThread)
                api.close(process.hProcess)
                cleanup["child_closed"] = True
            except Exception as error:
                cleanup["child_error"] = str(error)
        if capture is not None:
            try:
                api.close_child_stdio(capture)
                cleanup["stdio_closed"] = True
                if cleanup.get("child_closed") and "child_stdio" not in record:
                    record["child_stdio"] = _observe_child_stdio(capture)
            except Exception as error:
                cleanup["stdio_error"] = str(error)
        try:
            api.close(token)
            cleanup["token_closed"] = True
        except Exception as error:
            cleanup["token_error"] = str(error)
        try:
            cleanup_fixture(api, root, user)
            cleanup["fixture_removed"] = True
        except Exception as error:
            cleanup["fixture_error"] = str(error)
        if created:
            cleanup["profile_delete_hresult"] = api.DeleteAppContainerProfile(profile)
        if package_sid.value:
            api.FreeSid(package_sid)
        record["cleanup"] = cleanup
        if (
            any(key.endswith("error") for key in cleanup)
            or cleanup.get("profile_delete_hresult", 0) != 0
        ):
            record["status"] = "trace_error"
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(os.name == "nt", "native Windows required")
    require(not args.output.exists(), "new diagnostic receipt required")
    actual = subprocess.check_output(
        ["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True
    ).strip()
    require(actual == args.source_head, "exact checked-out source head")
    sources = [
        Path(__file__).with_name(name)
        for name in ("child_trace.py", "child_trace.c", "probe.py", "win32_api.py")
    ]
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
    }
    executable_sha = hashlib.sha256(args.executable.read_bytes()).hexdigest()
    report = {
        "source_head": actual,
        "source_sha256_before": before,
        "executable_sha256": executable_sha,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "windows": platform.win32_ver(),
        "scope": "independent primary-token Win32 trace; original cmd predicates remain required",
        "diagnostic_only": True,
        "production_qualification": False,
    }
    api, base = Api(), HANDLE()
    api.checked(
        api.OpenProcessToken(api.GetCurrentProcess(), TOKEN_QUERY, C.byref(base)),
        "base query token",
    )
    try:
        user = api.user_sid(base)
        report["cases"] = [
            run_case(api, mode, user, base, args.executable, executable_sha)
            for mode in (False, True)
        ]
    finally:
        api.close(base)
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
    }
    report["source_sha256_after"] = after
    report["source_unchanged"] = before == after
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(report, destination, indent=2)
        destination.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "diagnostic_only": True,
                "production_qualification": False,
            }
        )
    )
    # Success means the diagnostic invocation completed. It does not replace
    # the original experiment, and no security pass condition is inferred.
    return (
        0
        if before == after
        and all(
            case["status"] == "observed"
            and case["child_exit_code"] == 0
            and case["child_trace_completed"]
            for case in report["cases"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
