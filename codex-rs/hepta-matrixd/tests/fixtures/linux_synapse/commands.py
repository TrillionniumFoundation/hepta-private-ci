"""Actual command execution with immutable executable authority and failure logs."""

from datetime import datetime, timezone
import os
from pathlib import Path
import resource
import re
import subprocess
import time

from .files import describe, physical, verify, write_json


PUBLIC_ENVIRONMENT = {
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TZ",
    "PYTHONDONTWRITEBYTECODE",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_OPTIONAL_LOCKS",
    "GIT_INDEX_FILE",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "RUSTC",
    "RUSTDOC",
    "CARGO_TARGET_DIR",
    "CARGO_NET_OFFLINE",
    "CARGO_INCREMENTAL",
    "CARGO_BUILD_JOBS",
    "CARGO_BUILD_TARGET",
    "CARGO_PROFILE_DEV_DEBUG",
    "CARGO_PROFILE_TEST_DEBUG",
    "CARGO_TERM_COLOR",
    "CC",
    "CXX",
    "AR",
    "RANLIB",
    "CMAKE",
    "MAKE",
    "PKG_CONFIG",
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "NEXTEST_PROFILE",
    "HEPTA_R4_FIXTURE_MANIFEST",
    "HEPTA_R4_COMPLETION_DIRECTORY",
    "HEPTA_R4_COMPLETION_NONCE_FILE",
}


class Commands:
    def __init__(self, directory, tools, environment, cwd):
        self.directory = physical(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.tools = tools
        self.environment = dict(environment)
        self.cwd = Path(cwd)
        self.records = []

    def run(
        self,
        tool,
        args,
        *,
        label,
        required=True,
        environment=None,
        input_bytes=None,
        timeout_seconds=None,
    ):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", label):
            raise ValueError("Invalid command evidence label")
        if not isinstance(args, (tuple, list)) or not all(
            isinstance(arg, str) and "\0" not in arg for arg in args
        ):
            raise ValueError("Command arguments must be explicit strings")
        actual_environment = {**self.environment, **(environment or {})}
        if not set(actual_environment) <= PUBLIC_ENVIRONMENT or not all(
            isinstance(value, str) and "\0" not in value
            for value in actual_environment.values()
        ):
            raise ValueError(
                "Command environment is not the reviewed nonsecret allowlist"
            )
        authority = self.tools[tool]
        executable = Path(authority["path"])
        identity = {key: authority[key] for key in ("bytes", "sha256")}
        verify(executable, identity)
        number = len(self.records)
        stdout = self.directory / f"{number:03d}-{label}.stdout"
        stderr = self.directory / f"{number:03d}-{label}.stderr"
        record = {
            "tool": tool,
            "executable": authority,
            "arguments": list(args),
            "cwd": str(self.cwd),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "environment": actual_environment,
            "exit_code": None,
            "cost_scope": "direct command and children; Docker client CPU excludes daemon/container CPU",
            "stdin": "private bytes, never retained"
            if input_bytes is not None
            else "none",
            "timeout_seconds": timeout_seconds,
        }
        self.records.append(record)
        write_json(self.directory / f"{number:03d}-START.json", record)
        start = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            with stdout.open("xb") as out, stderr.open("xb") as err:
                for stream in (out, err):
                    os.fchmod(stream.fileno(), 0o600)
                result = subprocess.run(
                    [str(executable), *args],
                    cwd=self.cwd,
                    env=actual_environment,
                    input=input_bytes,
                    stdout=out,
                    stderr=err,
                    timeout=timeout_seconds,
                )
                for stream in (out, err):
                    stream.flush()
                    os.fsync(stream.fileno())
            record["exit_code"] = result.returncode
        except OSError as error:
            record["launch_error"] = str(error)
            raise
        except subprocess.TimeoutExpired as error:
            record["timeout_expired"] = True
            raise RuntimeError(
                f"Bounded control command {label} timed out; output retained"
            ) from error
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            record.update(
                wall_seconds=time.monotonic() - start,
                child_cpu_seconds=(
                    after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
                ),
            )
            for label_name, path in (("stdout", stdout), ("stderr", stderr)):
                if path.exists():
                    with path.open("rb") as stream:
                        os.fsync(stream.fileno())
                    record[label_name] = {"path": path.name, **describe(path)}
            try:
                record["executable_unchanged"] = describe(executable) == identity
            except (OSError, ValueError) as error:
                record["executable_unchanged"] = False
                record["executable_readback_error"] = str(error)
            write_json(self.directory / f"{number:03d}-END.json", record)
        if not record["executable_unchanged"]:
            raise ValueError("Executed control tool changed during the command")
        if required and record["exit_code"] != 0:
            raise RuntimeError(
                f"{label} failed with exit {record['exit_code']}; raw output retained"
            )
        return record, stdout

    def text(self, tool, args, *, label):
        _, path = self.run(tool, args, label=label)
        return path.read_text().strip()
