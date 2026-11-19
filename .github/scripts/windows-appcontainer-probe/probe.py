"""Owned-object mechanism experiment; this does not enable production admission."""

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
import uuid

from win32_api import Api
from win32_api import DELETE
from win32_api import DELETE_CHILD
from win32_api import DWORD
from win32_api import HANDLE
from win32_api import MUTATION
from win32_api import PTR
from win32_api import READ
from win32_api import TOKEN_DUPLICATE
from win32_api import TOKEN_IMPERSONATE
from win32_api import TOKEN_QUERY
from win32_api import WAIT_TIMEOUT
from win32_api import WRITE
from win32_api import require


CHILD_SCRIPT = "\r\n".join(
    [
        "@echo off",
        "echo child>child-created.txt",
        "if errorlevel 1 exit /b 21",
        "del child-delete.txt",
        "if errorlevel 1 exit /b 22",
        "if exist child-delete.txt exit /b 23",
        "rmdir child-delete-dir",
        "if errorlevel 1 exit /b 24",
        "if exist child-delete-dir exit /b 25",
        "type ..\\outside\\readable.txt >child-readable.txt",
        "if errorlevel 1 exit /b 26",
        "echo forbidden>..\\outside\\child-write.txt 2>nul",
        "del /q ..\\outside\\child-null-ME.txt 2>nul",
        "del /q ..\\outside\\child-null-LW.txt 2>nul",
        "rmdir .git 2>nul",
        "echo done>child-attempts-done.txt",
        "if errorlevel 1 exit /b 27",
        "exit /b 0",
        "",
    ]
).encode("ascii")


def dacl(user, package, allowed, deny_user=0, deny_package=0):
    deny = ""
    if deny_user:
        deny += f"(D;OICI;0x{deny_user:x};;;{user})"
    if deny_package:
        deny += f"(D;OICI;0x{deny_package:x};;;{package})"
    return f"D:P{deny}(A;OICI;FA;;;{user})(A;OICI;FA;;;SY)(A;OICI;0x{allowed:x};;;{package})"


def relative(root, path):
    # All mutation paths are constructed below this single newly owned directory.
    return path.relative_to(root).as_posix()


def fixture(api, root, user, package, base_token):
    writable = READ | WRITE | DELETE
    api.set_dacl(root, dacl(user, package, READ))
    workspace = root / "workspace"
    outside = root / "outside"
    workspace.mkdir()
    outside.mkdir()
    api.set_dacl(workspace, dacl(user, package, writable))
    api.set_dacl(outside, dacl(user, package, READ))
    operations = []
    retained = []
    for name, data in (
        ("inside-delete.txt", b"inside"),
        ("child-delete.txt", b"child"),
    ):
        (workspace / name).write_bytes(data)
    for name in ("inside-delete-dir", "child-delete-dir", ".git", ".git-package-deny"):
        (workspace / name).mkdir()
    api.set_dacl(workspace / ".git", dacl(user, package, writable, deny_user=MUTATION))
    api.set_dacl(
        workspace / ".git-package-deny",
        dacl(user, package, writable, deny_package=MUTATION),
    )
    for kind, name in (
        ("create", "inside-created.txt"),
        ("delete", "inside-delete.txt"),
        ("remove_dir", "inside-delete-dir"),
    ):
        operations.append(
            {
                "case": "allowed",
                "kind": kind,
                "path": relative(root, workspace / name),
                "expected_success": True,
            }
        )
    operations.append(
        {
            "case": "protected_git_user_deny",
            "kind": "remove_dir",
            "path": "workspace/.git",
            "expected_success": False,
        }
    )
    operations.append(
        {
            "case": "package_deny_observation",
            "kind": "remove_dir",
            "path": "workspace/.git-package-deny",
            "expected_success": None,
        }
    )
    public = outside / "readable.txt"
    public.write_bytes(b"retained")
    (workspace / "child-probe.cmd").write_bytes(CHILD_SCRIPT)
    child_write = outside / "child-write.txt"
    child_write.write_bytes(b"retained")
    retained.append(child_write)
    operations.append(
        {
            "case": "explicit_outside_read",
            "kind": "read",
            "path": relative(root, public),
            "expected_success": True,
        }
    )
    for kind in ("write", "write_dac", "write_owner", "delete"):
        path = outside / f"ordinary-{kind}.txt"
        path.write_bytes(b"retained")
        retained.append(path)
        operations.append(
            {
                "case": "ordinary_outside",
                "kind": kind,
                "path": relative(root, path),
                "expected_success": False,
            }
        )
    operations.append(
        {
            "case": "ordinary_outside",
            "kind": "create",
            "path": "outside/not-created.txt",
            "expected_success": False,
        }
    )
    parent_controls = []
    null_paths = []
    for label in ("ME", "LW"):
        child_null = outside / f"child-null-{label}.txt"
        child_null.write_bytes(b"retained")
        api.make_owner(child_null, base_token)
        api.set_null_dacl(child_null)
        api.set_label(child_null, label)
        null_paths.append((child_null, label))
        retained.append(child_null)
        for kind in ("read", "write", "write_dac", "write_owner", "delete"):
            path = outside / f"null-{label}-{kind}.txt"
            path.write_bytes(b"retained")
            api.make_owner(path, base_token)
            api.set_null_dacl(path)
            api.set_label(path, label)
            null_paths.append((path, label))
            retained.append(path)
            operations.append(
                {
                    "case": f"null_dacl_{label}",
                    "kind": kind,
                    "path": relative(root, path),
                    "expected_success": False,
                }
            )
        path = outside / f"unconfined-control-{label}.txt"
        path.write_bytes(b"retained")
        api.make_owner(path, base_token)
        api.set_null_dacl(path)
        api.set_label(path, label)
        facts = api.security_facts(path)
        result = api.operation(path, "delete")
        require(
            facts["dacl_present"]
            and facts["null_dacl"]
            and result["success"]
            and not path.exists(),
            "unconfined NULL-DACL deletion positive control",
        )
        parent_controls.append({"label": label, "security": facts, "result": result})
    # The original four-cell deletion oracle remains in the Rust suite. This
    # independent matrix measures the corresponding package-side authorization.
    for parent_bit, target_bit in (
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ):
        name = f"matrix-{int(parent_bit)}-{int(target_bit)}"
        parent = root / name
        parent.mkdir()
        api.set_dacl(
            parent, dacl(user, package, READ | (DELETE_CHILD if parent_bit else 0))
        )
        target = parent / "target.txt"
        target.write_bytes(b"retained")
        api.set_dacl(target, dacl(user, package, READ | (DELETE if target_bit else 0)))
        operations.append(
            {
                "case": name,
                "kind": "delete",
                "path": relative(root, target),
                "expected_success": parent_bit or target_bit,
            }
        )
    contaminated = root / "contaminated-parent"
    contaminated.mkdir()
    api.set_dacl(contaminated, dacl(user, package, writable | DELETE_CHILD))
    git = contaminated / ".git"
    git.mkdir()
    api.set_dacl(git, dacl(user, package, READ, deny_user=MUTATION))
    operations.append(
        {
            "case": "parent_delete_child_counterexample",
            "kind": "remove_dir",
            "path": relative(root, git),
            "expected_success": True,
        }
    )
    facts = {}
    for path in [root, *sorted(root.rglob("*"))]:
        facts[relative(root, path)] = api.security_facts(path)
    workspace_grants = [
        entry
        for entry in facts["workspace"]["dacl"]
        if entry["type"] == 0 and entry["sid"] == package
    ]
    require(
        len(workspace_grants) == 1 and workspace_grants[0]["mask"] == writable,
        "readback: workspace package has exact child DELETE, no FILE_DELETE_CHILD",
    )
    require(
        any(
            entry["type"] == 1 and entry["sid"] == user and entry["mask"] == MUTATION
            for entry in facts["workspace/.git"]["dacl"]
        ),
        "readback: protected user deny",
    )
    for path, label in null_paths:
        record = facts[relative(root, path)]
        require(
            record["dacl_present"]
            and record["null_dacl"]
            and record["owner_sid"] == user,
            "readback: owned NULL DACL",
        )
        expected_sid = "S-1-16-4096" if label == "LW" else "S-1-16-8192"
        require(
            len(record["labels"]) == 1
            and record["labels"][0]["sid"] == expected_sid
            and record["labels"][0]["mask"] == 1,
            "readback: exact object integrity",
        )
    return {
        "workspace": workspace,
        "operations": operations,
        "retained": retained,
        "security": facts,
        "unconfined_controls": parent_controls,
    }


def observe(api, token, root, operations):
    impersonation = HANDLE()
    api.checked(
        api.DuplicateTokenEx(
            token,
            TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_IMPERSONATE,
            None,
            2,
            2,
            C.byref(impersonation),
        ),
        "duplicate child token",
    )
    records = []
    try:
        api.checked(
            api.ImpersonateLoggedOnUser(impersonation), "impersonate exact child token"
        )
        try:
            for operation in operations:
                path = root / operation["path"]
                relative(root, path)
                result = api.operation(path, operation["kind"])
                records.append({**operation, **result})
        finally:
            if not api.RevertToSelf():
                # Continuing in an unexpected impersonation context is forbidden.
                os._exit(70)
    finally:
        api.close(impersonation)
    for record in records:
        expected = record["expected_success"]
        if expected is None:
            record["matches_required_hypothesis"] = None
        else:
            record["matches_required_hypothesis"] = (
                record["success"] == expected
                and (expected or record["error"] == 5)
                and (
                    record["kind"] != "read"
                    or not expected
                    or record["expected_contents"]
                )
            )
    return records


def _observe_child_files(workspace):
    # These are parent observations, not the child's failing Win32 operation.
    limit = 4096
    records = []
    for name in (
        "child-created.txt",
        "child-delete.txt",
        "child-delete-dir",
        "child-readable.txt",
        "child-attempts-done.txt",
        "child-probe.cmd",
    ):
        record = {"path": name, "exists": None}
        phase = "lstat"
        try:
            path = workspace / name
            metadata = path.lstat()
            attributes = getattr(metadata, "st_file_attributes", 0)
            record.update(
                exists=True,
                size_bytes=metadata.st_size,
                mode=metadata.st_mode,
                file_attributes=attributes,
            )
            if attributes & 0x400 or stat.S_ISLNK(metadata.st_mode):
                record["sample_status"] = "not_read_reparse_or_symlink"
            elif stat.S_ISREG(metadata.st_mode):
                phase = "read"
                with path.open("rb") as stream:
                    sample = stream.read(limit + 1)
                prefix = sample[:limit]
                record["sample"] = {
                    "limit_bytes": limit,
                    "captured_bytes": len(prefix),
                    "limit_exceeded": len(sample) > limit,
                    "prefix_hex": prefix.hex(),
                    "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
                }
            else:
                record["sample_status"] = "not_read_non_regular"
        except OSError as error:
            if phase == "lstat" and isinstance(error, FileNotFoundError):
                record["exists"] = False
            message = str(error)
            record["observer_error"] = {
                "phase": phase,
                "type": type(error).__name__,
                "errno": error.errno,
                "winerror": getattr(error, "winerror", None),
                "message": message[:1024],
                "message_truncated": len(message) > 1024,
            }
        records.append(record)
    return {"observer": "parent_after_child_exit", "files": records}


def _observe_child_stdio(capture):
    # These are actual cmd standard streams. They do not identify its internal
    # failing Win32 call or convert a failed original predicate into success.
    limit = 65536
    records = []
    for name in ("stdout.bin", "stderr.bin"):
        record = {"name": name, "limit_bytes": limit}
        try:
            path = capture["directory"] / name
            metadata = path.lstat()
            require(
                stat.S_ISREG(metadata.st_mode)
                and not (getattr(metadata, "st_file_attributes", 0) & 0x400),
                "capture must remain an owned regular file",
            )
            with path.open("rb") as stream:
                sample = stream.read(limit + 1)
            prefix = sample[:limit]
            record.update(
                size_bytes=metadata.st_size,
                captured_bytes=len(prefix),
                limit_exceeded=len(sample) > limit,
                prefix_hex=prefix.hex(),
                prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                display_utf8_replacement=prefix.decode("utf-8", errors="replace"),
            )
        except Exception as error:
            record["observer_error"] = {
                "type": type(error).__name__,
                "message": str(error)[:1024],
            }
        records.append(record)
    return {
        "observer": "parent_after_owned_child_exit",
        "transport": "explicit_stdio_handle_list_owned_files",
        "stdin": "empty_read_only_owned_file",
        "handle_facts": capture["handle_facts"],
        "raw_bytes_are_authoritative": True,
        "display_encoding_is_not_a_native_code_page_claim": True,
        "streams": records,
    }


def cleanup_fixture(api, root, user):
    if root is None:
        return
    own_acl = f"D:P(A;OICI;FA;;;{user})(A;OICI;FA;;;SY)"
    api.set_dacl(root, own_acl)
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(parent) / name
            relative(root, path)
            require(
                not (path.lstat().st_file_attributes & 0x400),
                "unexpected fixture reparse point",
            )
            api.set_dacl(path, own_acl)
    shutil.rmtree(root)
    require(not root.exists(), "owned fixture cleanup")


def run_case(api, lpac, user, base_token):
    result = {
        "mode": "lpac" if lpac else "appcontainer",
        "qualification": "owned mechanism only",
        "child_wait_budget_ms": 5000,
        "status": "running",
    }
    profile = "hepta.ci.59d82a47a690." + uuid.uuid4().hex
    result["owned_profile"] = profile
    package_sid = PTR()
    created_profile = False
    root = None
    process = None
    capture = None
    token = HANDLE()
    try:
        code = api.CreateAppContainerProfile(
            profile,
            profile,
            "Owned CI mechanism experiment",
            None,
            0,
            C.byref(package_sid),
        )
        require(
            code == 0 and package_sid.value is not None,
            f"create fresh profile failed: {code}",
        )
        created_profile = True
        package = api.sid_text(package_sid)
        root = Path(tempfile.mkdtemp(prefix="hepta-appcontainer-owned-"))
        result["owned_fixture"] = str(root)
        prepared = fixture(api, root, user, package, base_token)
        result["fixture_security"] = prepared["security"]
        result["unconfined_controls"] = prepared["unconfined_controls"]
        result["child_script_sha256"] = hashlib.sha256(CHILD_SCRIPT).hexdigest()
        capture = api.open_child_stdio(prepared["workspace"])
        process = api.create_suspended(
            package_sid, prepared["workspace"], lpac, capture["handles"]
        )
        # The child owns its copies; the parent closes every inheritable copy
        # before token observation and resume, without affecting the child's copy.
        api.close_child_stdio(capture)
        result["child_pid"] = process.dwProcessId
        api.checked(
            api.OpenProcessToken(
                process.hProcess, TOKEN_QUERY | TOKEN_DUPLICATE, C.byref(token)
            ),
            "query suspended child token",
        )
        token_facts = api.token_facts(token)
        result["child_token"] = token_facts
        require(
            token_facts
            == {
                "is_appcontainer": 1,
                "package_sid": package,
                "integrity_sid": "S-1-16-4096",
                "user_sid": user,
                "capability_count": 0,
            },
            "actual child token differs from requested identity",
        )
        query = api.lpac_token_query(token)
        result["lpac_information_class_query"] = query
        access = api.lpac_access_check(token)
        result["lpac_native_access_check"] = access
        expected_access = 2 if lpac else 3
        require(
            access["access_status"]
            and access["granted_access"] == expected_access
            and access["privilege_count"] == 0,
            "actual child application-package access differs from requested mode",
        )
        if query["status"] == "observed":
            require(query["value"] == int(lpac), "LPAC query and access check disagree")
        else:
            require(
                query["status"] == "unavailable"
                and query["information_class"] == 46
                and query["error"] == 87
                and query["value"] is None,
                "unknown LPAC query result",
            )
        result["lpac_identity_basis"] = "actual child token AccessCheck"
        records = observe(api, token, root, prepared["operations"])
        result["native_operations_with_child_token"] = records
        resume = api.ResumeThread(process.hThread)
        require(resume == 1, f"resume suspended child returned {resume}")
        wait = api.WaitForSingleObject(process.hProcess, 5000)
        result["child_wait_result"] = wait
        require(
            wait == 0, f"child did not exit within fixed 5-second probe budget: {wait}"
        )
        code = DWORD()
        api.checked(
            api.GetExitCodeProcess(process.hProcess, C.byref(code)), "child exit code"
        )
        result["child_exit_code"] = code.value
        result["child_stdio"] = _observe_child_stdio(capture)
        workspace = prepared["workspace"]
        result["child_file_observations"] = _observe_child_files(workspace)
        child_postconditions = (
            code.value == 0
            and (workspace / "child-created.txt").read_bytes().strip() == b"child"
            and not (workspace / "child-delete.txt").exists()
            and not (workspace / "child-delete-dir").exists()
            and (workspace / "child-readable.txt").read_bytes() == b"retained"
            and (workspace / "child-attempts-done.txt").read_bytes().strip() == b"done"
            and (workspace / "child-probe.cmd").read_bytes() == CHILD_SCRIPT
        )
        retained = all(
            path.is_file() and path.read_bytes() == b"retained"
            for path in prepared["retained"]
        )
        result["postconditions"] = {
            "actual_child_ordinary_operations": child_postconditions,
            "native_allowed_bytes_and_deletions": (
                workspace / "inside-created.txt"
            ).read_bytes()
            == b"changed"
            and not (workspace / "inside-delete.txt").exists()
            and not (workspace / "inside-delete-dir").exists(),
            "outside_original_bytes_retained": retained,
            "protected_git_retained": (workspace / ".git").is_dir(),
            "outside_new_file_absent": not (root / "outside/not-created.txt").exists(),
        }
        require(
            all(value for value in result["postconditions"].values()),
            "postcondition failure",
        )
        require(
            all(row["matches_required_hypothesis"] is not False for row in records),
            "AppContainer access hypothesis failed; retain every observation",
        )
        result["status"] = "passed_bounded_hypotheses"
    except Exception as error:
        result["status"] = "failed"
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        result["error_traceback"] = traceback.format_exc()
    finally:
        cleanup = {}
        if process is not None:
            try:
                if api.WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT:
                    api.checked(
                        api.TerminateProcess(process.hProcess, 71),
                        "stop owned probe child",
                    )
                    require(
                        api.WaitForSingleObject(process.hProcess, 5000) == 0,
                        "owned child stopped",
                    )
                api.close(process.hThread)
                api.close(process.hProcess)
                cleanup["owned_child_closed"] = True
            except Exception as error:
                cleanup["owned_child_error"] = str(error)
                result["status"] = "failed"
        if capture is not None:
            try:
                api.close_child_stdio(capture)
                cleanup["owned_stdio_handles_closed"] = True
            except Exception as error:
                cleanup["owned_stdio_error"] = str(error)
                result["status"] = "failed"
            if "child_stdio" not in result and cleanup.get("owned_child_closed"):
                result["child_stdio"] = _observe_child_stdio(capture)
        try:
            api.close(token)
            cleanup["owned_token_closed"] = True
        except Exception as error:
            cleanup["owned_token_error"] = str(error)
            result["status"] = "failed"
        try:
            cleanup_fixture(api, root, user)
            cleanup["fixture_removed"] = True
        except Exception as error:
            cleanup["fixture_error"] = str(error)
            result["status"] = "failed"
        if created_profile:
            code = api.DeleteAppContainerProfile(profile)
            cleanup["profile_delete_hresult"] = code
            if code != 0:
                result["status"] = "failed"
        if package_sid.value:
            api.FreeSid(package_sid)
        result["cleanup"] = cleanup
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    require(
        os.name == "nt",
        "this experiment requires native Windows; other platforms are not a pass",
    )
    require(not args.output.exists(), "output must be a new receipt")
    actual_head = subprocess.check_output(
        ["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True
    ).strip()
    require(
        actual_head == args.source_head,
        "checked-out head differs from the requested source pin",
    )
    sources = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), Path(__file__).with_name("win32_api.py"))
    }
    report = {
        "source_head": actual_head,
        "source_sha256_before": sources,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "windows": platform.win32_ver(),
        "python": sys.version,
        "scope": "owned AppContainer/LPAC filesystem mechanism and actual cmd child; no production admission or Root+Read/WFP qualification",
    }
    api = Api()
    base = HANDLE()
    api.checked(
        api.OpenProcessToken(api.GetCurrentProcess(), TOKEN_QUERY, C.byref(base)),
        "base query token",
    )
    try:
        user = api.user_sid(base)
        report["cases"] = [run_case(api, lpac, user, base) for lpac in (False, True)]
    finally:
        api.close(base)
    report["source_sha256_after"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), Path(__file__).with_name("win32_api.py"))
    }
    report["source_unchanged"] = (
        report["source_sha256_before"] == report["source_sha256_after"]
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["all_bounded_hypotheses_passed"] = report["source_unchanged"] and all(
        case["status"] == "passed_bounded_hypotheses" for case in report["cases"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "all_bounded_hypotheses_passed": report[
                    "all_bounded_hypotheses_passed"
                ],
            }
        )
    )
    return 0 if report["all_bounded_hypotheses_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
