#!/usr/bin/env python3
"""Observe fixed Windows OpenSSH; original operator failures remain failures.

Only the existing operator-native group is replayed. Fixture contrasts do not
grant authority, replace its security assertions, or establish a sandbox pass.
"""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import windows_current_ci as original


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise ValueError(f"file changed while reading: {path}")
    return {
        "path": str(path),
        "sha256": digest,
        **{key: getattr(after, key) for key in fields},
    }


def source(root: Path) -> dict:
    result = original.source(root)
    result["allChanges"] = original.git(
        root, "status", "--porcelain", "--untracked-files=all"
    )
    return result


def host_facts() -> tuple[dict, Path]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < size < len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    system = Path(buffer.value)
    if not system.is_absolute():
        raise ValueError("OS system directory must be absolute")
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetConsoleMode.restype = wintypes.BOOL
    kernel.GetHandleInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    handles = {}
    for name, selector in (("stdin", -10), ("stdout", -11), ("stderr", -12)):
        handle = kernel.GetStdHandle(selector & 0xFFFFFFFF)
        mode, flags = wintypes.DWORD(), wintypes.DWORD()
        ctypes.set_last_error(0)
        console = bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)))
        console_error = ctypes.get_last_error() if not console else 0
        ctypes.set_last_error(0)
        info = bool(kernel.GetHandleInformation(handle, ctypes.byref(flags)))
        info_error = ctypes.get_last_error() if not info else 0
        handles[name] = {
            "handle": handle,
            "fileType": kernel.GetFileType(handle),
            "consoleMode": mode.value if console else None,
            "consoleError": console_error,
            "handleFlags": flags.value if info else None,
            "handleError": info_error,
        }
    # Deliberately no complete environment dump, credentials or process list.
    allow = (
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "PROGRAMDATA",
        "APPDATA",
        "LOCALAPPDATA",
        "PROCESSOR_ARCHITECTURE",
        "ImageOS",
        "ImageVersion",
    )
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "systemDirectory": str(system),
        "environmentAllowlist": {key: os.environ.get(key) for key in allow},
        "coordinatorStandardHandles": handles,
        "standardHandlesAreNotChildHandleMeasurements": True,
    }, system


def capture(
    output: Path,
    name: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict | None = None,
    data: bytes = b"",
    mode: str = "pipes",
) -> dict:
    """Capture disposable diagnostic children only; never invoked for Rust."""
    started = time.monotonic()
    row = {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "stdio": mode,
        "status": "not_run",
        "exitCode": None,
        "timeoutSeconds": 30,
    }
    stdout, stderr = output / f"{name}.stdout.bin", output / f"{name}.stderr.bin"
    try:
        if mode == "pipes":
            process = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            stdout.write_bytes(process.stdout)
            stderr.write_bytes(process.stderr)
        else:
            with stdout.open("xb") as out, stderr.open("xb") as err:
                process = subprocess.run(
                    command,
                    cwd=cwd,
                    env=env,
                    input=data,
                    stdout=out,
                    stderr=err,
                    timeout=30,
                    check=False,
                )
        row.update(status="completed", exitCode=process.returncode)
    except subprocess.TimeoutExpired as error:
        row.update(status="diagnostic_timeout", error=str(error))
        if mode == "pipes":
            stdout.write_bytes(error.stdout or b"")
            stderr.write_bytes(error.stderr or b"")
    except OSError as error:
        row.update(status="launch_error", error=f"{type(error).__name__}: {error}")
    row["wallSeconds"] = time.monotonic() - started
    row["streams"] = [fingerprint(path) for path in (stdout, stderr) if path.exists()]
    write_json(output / f"{name}.json", row)
    return row


def fixture_contrasts(output: Path, fixture: Path, system: Path) -> dict:
    executable = system / "OpenSSH/ssh-keygen.exe"
    binary_before = fingerprint(executable)
    result = {
        "scope": "disposable_fixture_contrasts_only",
        "runs": [],
        "productionInputPinsAndDaclReproduced": False,
        "fixedBinaryBefore": binary_before,
        "complete": False,
    }
    key, statement = fixture / "key", fixture / "statement"
    namespace, principal = "hepta-windows-probe", "hepta-probe"
    statement.write_bytes(b"independent Windows SSHSIG diagnostic fixture\n")
    for name, command in (
        (
            "fixture-keygen",
            [str(executable), "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        ),
        (
            "fixture-sign",
            [
                str(executable),
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                namespace,
                str(statement),
            ],
        ),
    ):
        row = capture(output, name, command, cwd=system)
        result["runs"].append(row)
        if row["status"] != "completed" or row["exitCode"] != 0:
            return result
    allowed, signature = fixture / "allowed_signers", fixture / "statement.sig"
    allowed.write_bytes(
        principal.encode() + b" " + key.with_suffix(".pub").read_bytes()
    )
    result["fixtureInputs"] = [
        fingerprint(path) for path in (statement, allowed, signature)
    ]
    # Same objects, alternative path spellings; no PATH lookup or binary swap.
    normal = [str(path) for path in (executable, allowed, signature)]
    normal = [path[4:] if path.startswith("\\\\?\\") else path for path in normal]
    if any(path.startswith("\\\\") for path in normal):
        raise ValueError("this diagnostic expects local drive paths, not UNC")
    verbatim = ["\\\\?\\" + path for path in normal]
    for left, right in zip(normal, verbatim, strict=True):
        if not os.path.samefile(left, right):
            raise ValueError("path contrast does not identify the same file")
    minimal = {"SystemRoot": str(system.parent), "LANG": "C", "LC_ALL": "C"}
    result["clearedEnvironment"] = minimal
    for environment, env in (("cleared", minimal), ("inherited", None)):
        for spelling, paths in (("normal", normal), ("verbatim", verbatim)):
            for mode in ("pipes", "files"):
                for control, requested_namespace in (
                    ("exact", namespace),
                    ("wrong", namespace + "-wrong"),
                ):
                    name = f"verify-{environment}-{spelling}-{mode}-{control}"
                    command = [
                        paths[0],
                        "-vvv",
                        "-Y",
                        "verify",
                        "-f",
                        paths[1],
                        "-I",
                        principal,
                        "-n",
                        requested_namespace,
                        "-s",
                        paths[2],
                    ]
                    row = capture(
                        output,
                        name,
                        command,
                        cwd=system,
                        env=env,
                        data=statement.read_bytes(),
                        mode=mode,
                    )
                    result["runs"].append(row)
    result["fixedBinaryAfter"] = fingerprint(executable)
    result["binaryUnchanged"] = result["fixedBinaryAfter"] == binary_before
    result["inputsUnchanged"] = result["fixtureInputs"] == [
        fingerprint(path) for path in (statement, allowed, signature)
    ]
    result["complete"] = (
        result["binaryUnchanged"]
        and result["inputsUnchanged"]
        and all(row["status"] == "completed" for row in result["runs"])
    )
    return result


def retain_junit(
    root: Path, path: Path, group: dict, started: float, ended: float
) -> dict:
    # The generic execution collector is POSIX-only. Reuse its hardened XML
    # parser, without fabricating a source-head hepta_ci_exec record on Windows.
    sys.path.insert(0, str(root / "scripts"))
    from hepta_ci_junit import NoDoctypeTreeBuilder

    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(64 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        not started <= after.st_mtime <= ended
        or len(data) > 64 * 1024 * 1024
        or any(getattr(before, key) != getattr(after, key) for key in fields)
    ):
        raise ValueError(
            "JUnit is stale, changed, or exceeds the existing 64 MiB bound"
        )
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("JUnit declarations are forbidden")
    xml = ET.fromstring(data, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    if xml.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected JUnit root")
    cases = list(xml.iter("testcase"))
    names = [case.get("name") for case in cases]
    if (
        len(cases) != group["expectedTestCount"]
        or len(set(names)) != len(names)
        or sorted(names) != sorted(group["requiredTests"])
    ):
        raise ValueError("JUnit does not contain the exact original operator cases")
    failures = sum(
        case.find("failure") is not None or case.find("error") is not None
        for case in cases
    )
    skipped = sum(case.find("skipped") is not None for case in cases)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "cases": names,
        "executed": len(cases) - skipped,
        "failures": failures,
        "skipped": skipped,
        "passed": failures == skipped == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--expected-observer-head")
    parser.add_argument("--original-only", action="store_true")
    args = parser.parse_args()
    observer_root = Path(__file__).resolve().parents[2]
    root = args.source_root.resolve(strict=True) if args.source_root else observer_root
    output = args.output.resolve()
    if sys.platform != "win32" or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise ValueError("requires actual Windows and a full source SHA")
    observer_head = args.expected_observer_head or args.expected_head
    if not re.fullmatch(r"[0-9a-f]{40}", observer_head):
        raise ValueError("requires the full observer source SHA")
    if args.original_only and (
        args.source_root is None
        or args.expected_observer_head is None
        or any(
            os.environ.get(key) != args.expected_head
            for key in ("SOURCE_SHA", "TESTED_SHA")
        )
    ):
        raise ValueError(
            "original-only requires explicit matching source/observer bindings"
        )
    if root != observer_root and not args.original_only:
        raise ValueError("an independent source checkout requires original-only mode")
    if output.is_relative_to(root) or output.is_relative_to(observer_root):
        raise ValueError("records must stay outside checkout")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        "schema": "hepta.windows-probe.v1",
        "status": "running",
        "sourceSha": args.expected_head,
        "testedSha": args.expected_head,
        "observerSha": observer_head,
        "originalOnly": args.original_only,
        "originalOperatorScope": "not_run",
        "owningPackageLint": {"status": "not_run"},
        "fixtureContrasts": "not_run",
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
        "researchAdvancement": False,
        "fullCost": None,
        "testsRetried": 0,
    }
    write_json(output / "started.json", receipt)
    exit_code = 1
    try:
        observer_before = source(observer_root)
        write_json(output / "observer-before.json", observer_before)
        if observer_before["head"] != observer_head or observer_before["allChanges"]:
            raise ValueError("observer differs from the requested clean head")
        before = source(root)
        write_json(output / "source-before.json", before)
        if before["head"] != args.expected_head or before["allChanges"]:
            raise ValueError("requested source is not the complete clean checkout")
        # The original command builder and assessor belong to the tested source,
        # even when this separately recorded observer schedules the execution.
        runner_path = root / ".github/scripts/windows_current_ci.py"
        spec = importlib.util.spec_from_file_location(
            "tested_windows_current_ci", runner_path
        )
        if spec is None or spec.loader is None:
            raise ValueError("tested source command builder cannot be loaded")
        native_runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native_runner)
        write_json(
            output / "execution-sources.json",
            {
                "sourceRoot": str(root),
                "observerRoot": str(observer_root),
                "sourceSha": args.expected_head,
                "testedSha": args.expected_head,
                "observerSha": observer_head,
                "files": [
                    fingerprint(path)
                    for path in (
                        Path(__file__),
                        observer_root / ".github/scripts/windows_current_ci.py",
                        runner_path,
                        root / ".github/fixtures/windows-current-ci-scope.json",
                        root / "scripts/hepta_ci_junit.py",
                    )
                ],
            },
        )
        compiler = subprocess.check_output(
            ["rustc", "--version", "--verbose"], text=True
        )
        (output / "compiler.txt").write_text(compiler, encoding="utf-8")
        if not compiler.startswith("rustc 1.96.0 "):
            raise ValueError("compiler differs from the original native lane")
        fixture = output.with_name(output.name + "-private-fixtures")
        fixture.mkdir(mode=0o700, exist_ok=False)
        fixture = fixture.resolve(strict=True)
        os.environ["TEMP"] = os.environ["TMP"] = str(fixture)
        try:
            facts, system = host_facts()
            write_json(output / "host.json", facts)
            receipt["fixedBinaryBefore"] = fingerprint(
                system / "OpenSSH/ssh-keygen.exe"
            )
            if args.original_only:
                receipt["fixtureContrasts"] = {
                    "status": "not_run",
                    "reason": "original_native_scope_only",
                }
            else:
                receipt["tokenObservation"] = capture(
                    output,
                    "token-whoami",
                    [str(system / "whoami.exe"), "/all"],
                    cwd=system,
                )
                contrasts = fixture_contrasts(output, fixture, system)
                receipt["fixtureContrasts"] = contrasts
                write_json(output / "fixture-contrasts.json", contrasts)
        except Exception as error:
            receipt["fixtureContrasts"] = {
                "error": f"{type(error).__name__}: {error}",
                "complete": False,
            }
        manifest = json.loads(
            (root / ".github/fixtures/windows-current-ci-scope.json").read_text()
        )
        groups = [
            group for group in manifest["groups"] if group["id"] == "operator-native"
        ]
        if len(groups) != 1:
            raise ValueError("original operator scope must occur exactly once")
        group = groups[0]
        write_json(output / "original-scope.json", group)
        store, config = output / "nextest-store", output / "nextest.toml"
        config.write_text(
            "[store]\ndir = "
            + json.dumps(str(store))
            + '\n[profile.local.junit]\npath = "junit.xml"\n',
            encoding="utf-8",
        )
        invocation = {}

        def invoke(command: list[str]) -> tuple[int, str]:
            command.extend(
                [
                    "--tool-config-file",
                    f"hepta-windows-probe:{config}",
                    "--success-output",
                    "immediate",
                    "--failure-output",
                    "immediate",
                ]
            )
            invocation.update(
                command=command, startedAt=datetime.now(timezone.utc).isoformat()
            )
            receipt["originalOperatorScope"] = "running"
            write_json(
                output / "original-execution-started.json",
                {**invocation, "status": "running"},
            )
            start = time.time()
            # No native timeout or retry added: the original Nextest watchdogs apply.
            with (
                (output / "operator.stdout.bin").open("xb") as out,
                (output / "operator.stderr.bin").open("xb") as err,
            ):
                process = subprocess.run(
                    command, cwd=root / "codex-rs", stdout=out, stderr=err, check=False
                )
            end = time.time()
            invocation.update(
                exitCode=process.returncode,
                finishedAt=datetime.now(timezone.utc).isoformat(),
                startedUnix=start,
                finishedUnix=end,
            )
            write_json(output / "original-execution.json", invocation)
            streams = [
                (output / name).read_bytes()
                for name in ("operator.stdout.bin", "operator.stderr.bin")
            ]
            return process.returncode, b"\n".join(streams).decode(
                "utf-8", errors="replace"
            )

        results = native_runner.execute_groups(root, output, groups, invoke=invoke)
        receipt["originalOperatorScope"] = results
        junit = retain_junit(
            root,
            store / "local/junit.xml",
            group,
            invocation["startedUnix"],
            invocation["finishedUnix"],
        )
        write_json(output / "original-junit.json", junit)
        if args.original_only:
            lint = {
                "status": "running",
                "command": [
                    "just",
                    "fix",
                    "--locked",
                    "-p",
                    "codex-hepta-operator-acceptance",
                    "--",
                    "-D",
                    "warnings",
                ],
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "exitCode": None,
            }
            receipt["owningPackageLint"] = lint
            write_json(output / "package-lint-started.json", lint)
            lint_started = time.monotonic()
            with (
                (output / "package-lint.stdout.bin").open("xb") as out,
                (output / "package-lint.stderr.bin").open("xb") as err,
            ):
                process = subprocess.run(
                    lint["command"],
                    cwd=root / "codex-rs",
                    stdout=out,
                    stderr=err,
                    check=False,
                )
            lint.update(
                status="completed",
                exitCode=process.returncode,
                wallSeconds=time.monotonic() - lint_started,
                finishedAt=datetime.now(timezone.utc).isoformat(),
            )
            write_json(output / "package-lint.json", lint)
            # A fixer mutation invalidates the candidate binding. Never rerun the
            # tests on that dirty source or relabel their earlier source SHA.
            (output / "source-after-lint.diff").write_bytes(
                subprocess.check_output(
                    ["git", "--no-pager", "diff", "--binary", "HEAD"], cwd=root
                )
            )
        after = source(root)
        write_json(output / "source-after.json", after)
        observer_after = source(observer_root)
        write_json(output / "observer-after.json", observer_after)
        intact = (
            native_runner.valid_source(args.expected_head, before, after)
            and not after["allChanges"]
            and original.valid_source(observer_head, observer_before, observer_after)
            and not observer_after["allChanges"]
        )
        receipt.update(sourceUnchanged=intact, originalJunit=junit)
        passed = intact and all(row["passed"] for row in results) and junit["passed"]
        receipt["originalOperatorPassed"] = passed
        # Contrasts never rescue a failed native oracle. Original-only mode
        # requires the owning-package strict lint instead of fixture contrasts.
        auxiliaries_passed = (
            receipt["owningPackageLint"].get("status") == "completed"
            and receipt["owningPackageLint"].get("exitCode") == 0
            if args.original_only
            else receipt["fixtureContrasts"].get("complete")
        )
        exit_code = 0 if passed and auxiliaries_passed else 1
        receipt["status"] = (
            "original_operator_passed_observation_only"
            if exit_code == 0
            else "failed_or_incomplete"
        )
    except Exception as error:
        receipt.update(
            status="failed_or_incomplete", error=f"{type(error).__name__}: {error}"
        )
    finally:
        if not (output / "source-after.json").exists():
            try:
                write_json(output / "source-after.json", source(root))
            except Exception as error:
                receipt["sourceAfterError"] = f"{type(error).__name__}: {error}"
        if not (output / "observer-after.json").exists():
            try:
                write_json(output / "observer-after.json", source(observer_root))
            except Exception as error:
                receipt["observerAfterError"] = f"{type(error).__name__}: {error}"
        receipt.update(exitCode=exit_code, wallSeconds=time.monotonic() - started)
        write_json(output / "receipt.json", receipt)
        write_json(
            output / "manifest.json",
            [fingerprint(path) for path in sorted(output.rglob("*")) if path.is_file()],
        )
        print(json.dumps(receipt, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
