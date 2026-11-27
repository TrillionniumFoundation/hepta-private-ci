"""Observe cmd path spelling without changing original Windows probe predicates."""

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import traceback

from cmd_entry_probe import cmd_image, run_inline
from probe import run_case
from win32_api import Api, HANDLE, TOKEN_DUPLICATE, TOKEN_IMPERSONATE, TOKEN_QUERY
from win32_api import require


FROZEN_SOURCES = {
    "probe.py": "d73d8d51a6121efe0463304ece9832d9ba121a8cb5b4dc1fd71f706cdb5bd192",
    "win32_api.py": "74da42fd9a09ff09e9b5e16f15a5d8176582fc7cc85da383dbcfce11b3bc6208",
    "cmd_entry_probe.py": "c3b5d892a4305d2d8709ab6b42350f0d5bf6346f12220366de057670a6ff5fe5",
}


class PathObservationApi(Api):
    def __init__(self, spelling):
        super().__init__()
        require(spelling in ("original", "long"), "fixed path spelling comparison")
        self.spelling = spelling
        self.observation = {
            "spelling": spelling,
            "observer": "parent_impersonating_exact_suspended_child_token",
            "internal_cmd_trace": False,
            "path_queries": [],
        }
        self._create_process = self.CreateProcessW
        self.CreateProcessW = self.create_process_observed
        self._resume_thread = self.ResumeThread
        self.ResumeThread = self.resume_observed
        for name in ("GetLongPathNameW", "GetShortPathNameW"):
            function = getattr(self.kernel, name)
            function.restype = W.DWORD
            function.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD]
            setattr(self, name, function)

    def path_query(self, operation, path):
        buffer = C.create_unicode_buffer(32768)
        C.set_last_error(0)
        size = getattr(self, operation)(str(path), buffer, len(buffer))
        error = C.get_last_error() if size == 0 else 0
        return {
            "operation": operation,
            "input": str(path),
            "returned_length": size,
            "winerror": error,
            "bounded_success": 0 < size < len(buffer),
            "output": buffer.value if 0 < size < len(buffer) else None,
        }

    def create_suspended(self, package_sid, cwd, lpac, stdio_handles, **kwargs):
        self.original_cwd = Path(cwd)
        self.command_variant = kwargs.get("diagnostic_command", "original-batch")
        host = self.path_query("GetLongPathNameW", cwd)
        self.observation["host_long_path"] = host
        require(host["bounded_success"], "host must resolve the owned long path")
        self.long_cwd = Path(host["output"])
        require(self.original_cwd.samefile(self.long_cwd), "same owned cwd identity")
        require(
            not (self.long_cwd.lstat().st_file_attributes & 0x400),
            "owned cwd must not be a reparse object",
        )
        self.observation["same_owned_cwd"] = True
        self.observation["spelling_differs"] = str(cwd) != str(self.long_cwd)
        process = super().create_suspended(
            package_sid, cwd, lpac, stdio_handles, **kwargs
        )
        self.process = process
        return process

    def create_process_observed(self, *args):
        require(len(args) == 10, "exact CreateProcessW arguments")
        require(args[7] == str(self.original_cwd), "original cwd is unchanged upstream")
        # Only lpCurrentDirectory changes. Keep command, environment, token
        # attributes, inherited handles and creation flags exactly as constructed.
        chosen = self.long_cwd if self.spelling == "long" else self.original_cwd
        self.observation["launch"] = {
            "executable": args[0],
            "command": args[1].value,
            "environment": str(args[6][:]).split("\0"),
            "creation_flags": args[5],
            "inherit_handles": bool(args[4]),
            "original_cwd": args[7],
            "actual_cwd": str(chosen),
            "changed_argument": "lpCurrentDirectory"
            if str(chosen) != args[7]
            else None,
        }
        return self._create_process(*args[:7], str(chosen), *args[8:])

    def resume_observed(self, thread):
        require(thread == self.process.hThread, "observe only the owned child")
        token, impersonation = HANDLE(), HANDLE()
        try:
            self.checked(
                self.OpenProcessToken(
                    self.process.hProcess, TOKEN_QUERY | TOKEN_DUPLICATE, C.byref(token)
                ),
                "query the original suspended child",
            )
            self.checked(
                self.DuplicateTokenEx(
                    token,
                    TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_IMPERSONATE,
                    None,
                    2,
                    2,
                    C.byref(impersonation),
                ),
                "duplicate only the original child token for read-only observation",
            )
            self.checked(
                self.ImpersonateLoggedOnUser(impersonation), "observe child paths"
            )
            try:
                children = [None, "child-probe.cmd", "child-delete.txt"]
                if self.command_variant == "minimal-batch-exit71":
                    children.append("cmd-entry-minimal.cmd")
                for root in (self.original_cwd, self.long_cwd):
                    for child in children:
                        path = root if child is None else root / child
                        for operation in ("GetLongPathNameW", "GetShortPathNameW"):
                            self.observation["path_queries"].append(
                                self.path_query(operation, path)
                            )
            finally:
                if not self.RevertToSelf():
                    os._exit(70)
        finally:
            try:
                self.close(impersonation)
            finally:
                self.close(token)
        # These observations are not an internal cmd trace. Preserve every
        # original matrix and child postcondition, including positive failures.
        return self._resume_thread(thread)


def source_facts(repo):
    status = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        text=True,
    )
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in (*FROZEN_SOURCES, Path(__file__).name)
    }
    return {"head": head, "status": status, "sha256": hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(os.name == "nt", "native Windows is required; no substitute pass")
    require(
        re.fullmatch(r"[0-9a-f]{40}", args.source_head), "exact source commit required"
    )
    repo, output = args.repo.resolve(), args.output.resolve()
    require(
        not output.exists() and not output.is_relative_to(repo), "new external receipt"
    )
    require(
        Path(__file__).resolve()
        == repo / ".github/scripts/windows-appcontainer-probe/cmd_path_probe.py",
        "diagnostic belongs to the exact checkout",
    )
    before = source_facts(repo)
    require(
        before["head"] == args.source_head and not before["status"],
        "exact clean source",
    )
    require(
        all(
            before["sha256"][name] == digest for name, digest in FROZEN_SOURCES.items()
        ),
        "original probe, launcher and minimal batch checks must remain exact",
    )
    report = {
        "schema": "hepta.windows-cmd-path-observation.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "windows": platform.win32_ver(),
        "python": sys.version,
        "source_before": before,
        "diagnostic_only": True,
        "production_qualification": False,
        "all_original_predicates_preserved": True,
        "cases": [],
    }
    try:
        for spelling in ("original", "long"):
            for kind in (
                "appcontainer-original-batch",
                "lpac-original-batch",
                "lpac-minimal-batch",
            ):
                api, base = PathObservationApi(spelling), HANDLE()
                try:
                    report.setdefault("cmd_image_before", cmd_image(api))
                    api.checked(
                        api.OpenProcessToken(
                            api.GetCurrentProcess(), TOKEN_QUERY, C.byref(base)
                        ),
                        "base query token",
                    )
                    user = api.user_sid(base)
                    result = (
                        run_inline(api, "minimal-batch-exit71", user, base)
                        if kind == "lpac-minimal-batch"
                        else run_case(api, kind.startswith("lpac"), user, base)
                    )
                    report["cases"].append(
                        {"kind": kind, "paths": api.observation, "result": result}
                    )
                finally:
                    api.close(base)
                    report["cmd_image_after"] = cmd_image(api)
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        report["error_traceback"] = traceback.format_exc()
    finally:
        report["source_after"] = source_facts(repo)
        report["source_unchanged"] = report["source_after"] == before
        report["cmd_image_unchanged"] = report.get("cmd_image_before") == report.get(
            "cmd_image_after"
        )
        report["all_expected_results_observed"] = (
            len(report["cases"]) == 6
            and "error" not in report
            and report["source_unchanged"]
            and report["cmd_image_unchanged"]
            and all(
                (
                    row["result"].get("status") == "observed"
                    and row["result"].get("diagnostic_expected_result", False)
                )
                if row["kind"] == "lpac-minimal-batch"
                else row["result"].get("status") == "passed_bounded_hypotheses"
                for row in report["cases"]
            )
        )
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "all_expected_results_observed": report[
                    "all_expected_results_observed"
                ],
            }
        )
    )
    return 0 if report["all_expected_results_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
