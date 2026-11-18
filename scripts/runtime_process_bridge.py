"""A fixed-profile Cell worker adapter for the existing runtime process owner.

The owner is the actual hepta-runtime MCP process_start/status/read API.  This
adapter never retries process_start, even under its original key, after durable
submission intent exists.  An acknowledgement lost before job identity is
retained therefore stays UNKNOWN.  A restarted adapter observes known jobs.

This public MCP adapter uses administrator-configured process authority.  It is
not the Rust native::execute_or_observe_with_entry FinalUse capability API and
does not claim that stronger in-process boundary or learning qualification.
"""

import argparse
import os
from pathlib import Path
import re
import sqlite3
import stat

from runtime_process_contract import process_digest, terminal_proof
from runtime_stdio import (
    StdioRuntime,
    canonical,
    digest,
    file_digest,
    require,
    strict_json,
)


class RuntimeProcessBridge:
    """A durable no-resubmission adapter; call is an actual MCP owner callback."""

    def __init__(self, profile, database, call, *, transport_identity):
        # Retain values, not references that can change the admitted command or
        # transport identity after their joint digest has been computed.
        profile = strict_json(canonical(profile))
        transport_identity = strict_json(canonical(transport_identity))
        require(
            profile.get("schema") == "hepta.cell.runtime-process-bridge.v1",
            "unknown bridge profile",
        )
        require(
            isinstance(profile.get("namespace"), str) and profile["namespace"],
            "namespace missing",
        )
        fixed = profile.get("process", {})
        require(
            set(fixed)
            <= {
                "host",
                "executable",
                "args",
                "cwd",
                "env",
                "timeout_seconds",
                "nice",
                "cpu_quota_percent",
                "memory_max_bytes",
            },
            "unknown process field",
        )
        require(
            isinstance(fixed.get("host"), str)
            and re.fullmatch("[A-Za-z0-9_.-]{1,128}", fixed["host"]),
            "process host must be a configured alias",
        )
        require(
            isinstance(fixed.get("executable"), str)
            and fixed["executable"].startswith("/"),
            "process executable must be a fixed absolute path",
        )
        require(
            isinstance(fixed.get("args", []), list)
            and all(
                isinstance(a, str) and "\0" not in a for a in fixed.get("args", [])
            ),
            "process argv must contain strings",
        )
        self.profile, self.call, self.identity = profile, call, transport_identity
        self.profile_sha = digest(
            canonical({"profile": profile, "runtime": transport_identity})
        )
        self.max_output = profile.get("max_output_bytes", 4 * 1024 * 1024)
        require(
            type(self.max_output) is int and 1 <= self.max_output <= 16 * 1024 * 1024,
            "output budget outside bounds",
        )
        path = Path(database).absolute()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = path.parent.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and not stat.S_IMODE(info.st_mode) & 0o077,
            "bridge parent must be private",
        )
        if path.exists() or path.is_symlink():
            info = path.lstat()
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600,
                "unsafe bridge database",
            )
        else:
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS operations (request_id TEXT PRIMARY KEY, binding TEXT NOT NULL, params TEXT NOT NULL, job_id TEXT, observation TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS terminal_observations (request_id TEXT PRIMARY KEY, observation TEXT NOT NULL)"
        )
        self.db.commit()

    def _event(self, request_id, kind, value):
        self.db.execute(
            "INSERT INTO events(request_id,kind,body) VALUES(?,?,?)",
            (request_id, kind, canonical(value).decode()),
        )

    def _save(self, request_id, value):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if value["state"] == "TERMINAL":
                encoded = canonical(value).decode()
                original = self.db.execute(
                    "SELECT observation FROM terminal_observations WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if original is None:
                    # Existing journals already retain complete observations.
                    # Recover their first terminal, even if their latest view is
                    # UNKNOWN, instead of trusting a new post-restart result.
                    history = self.db.execute(
                        "SELECT body FROM events WHERE request_id=? AND kind='observation' ORDER BY sequence",
                        (request_id,),
                    )
                    for (body,) in history:
                        if strict_json(body).get("state") == "TERMINAL":
                            original = (body,)
                            break
                    original = original or (encoded,)
                    self.db.execute(
                        "INSERT INTO terminal_observations VALUES(?,?)",
                        (request_id, original[0]),
                    )
                if canonical(strict_json(original[0])).decode() != encoded:
                    self._event(request_id, "terminal_conflict", value)
                    value = {
                        key: value[key]
                        for key in (
                            "request_id",
                            "host",
                            "job_id",
                            "automatic_replay",
                            "profile_sha256",
                            "domain_success",
                        )
                    } | {
                        "state": "UNKNOWN",
                        "reason": "original_terminal_observation_changed",
                        "original_terminal_retained": True,
                        "original_terminal_sha256": digest(original[0].encode()),
                        "observed_terminal_sha256": digest(encoded.encode()),
                    }
            self.db.execute(
                "UPDATE operations SET observation=? WHERE request_id=?",
                (canonical(value).decode(), request_id),
            )
            self._event(request_id, "observation", value)
            self.db.commit()
            return value
        except BaseException:
            self.db.rollback()
            raise

    def execute(self, request):
        require(
            isinstance(request, dict)
            and set(request) == {"request_id", "cell_id", "operation", "payload"},
            "worker request fields changed",
        )
        request_id = request["request_id"]
        require(
            isinstance(request_id, str) and 0 < len(request_id.encode()) <= 256,
            "invalid request identity",
        )
        require(
            all(
                isinstance(request[k], str) and request[k]
                for k in ("cell_id", "operation")
            ),
            "cell identity or operation missing",
        )
        stdin = canonical(request).decode() + "\n"
        require(
            len(stdin.encode()) <= 1024 * 1024,
            "worker request exceeds runtime stdin bound",
        )
        key = "cell_joint_" + digest(canonical([self.profile["namespace"], request_id]))
        params = strict_json(
            canonical(
                {**self.profile["process"], "stdin": stdin, "idempotency_key": key}
            )
        )
        binding = digest(
            canonical({"profile_sha256": self.profile_sha, "params": params})
        )
        initial = {
            "state": "UNKNOWN",
            "reason": "submission_intent_without_acknowledgement",
            "request_id": request_id,
            "idempotency_key": key,
            "job_id": None,
            "automatic_replay": False,
            "profile_sha256": self.profile_sha,
            "domain_success": False,
        }
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT binding,job_id,observation FROM operations WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is not None:
                require(
                    row[0] == binding,
                    "request identity is already bound to different input/profile",
                )
                self.db.commit()
                return self.observe(request_id) if row[1] else strict_json(row[2])
            self.db.execute(
                "INSERT INTO operations VALUES(?,?,?,NULL,?)",
                (
                    request_id,
                    binding,
                    canonical(params).decode(),
                    canonical(initial).decode(),
                ),
            )
            self._event(
                request_id, "submission_intent", {"binding": binding, "params": params}
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        try:
            started = self.call("process_start", strict_json(canonical(params)))
            job = started.get("job", {})
            require(
                isinstance(job.get("id"), str)
                and re.fullmatch("[A-Za-z0-9_.-]{1,128}", job["id"]),
                "runtime did not return an original job identity",
            )
            require(
                job.get("host") == params["host"]
                and job.get("idempotency_key") == key
                and job.get("request_digest") == process_digest(params)
                and job.get("executable") == params["executable"]
                and job.get("args") == params.get("args", [])
                and job.get("cwd") == params.get("cwd"),
                "runtime job differs from exact fixed request",
            )
            self.db.execute(
                "UPDATE operations SET job_id=? WHERE request_id=?",
                (job["id"], request_id),
            )
            self._event(request_id, "runtime_admission", started)
            self.db.commit()
            return self.observe(request_id)
        except Exception as error:
            current = self.db.execute(
                "SELECT job_id FROM operations WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._save(
                request_id,
                {
                    **initial,
                    "job_id": current[0],
                    "reason": "runtime_submission_or_observation_unavailable",
                    "error_type": type(error).__name__,
                },
            )

    def observe(self, request_id):
        row = self.db.execute(
            "SELECT params,job_id,observation,binding FROM operations WHERE request_id=?",
            (request_id,),
        ).fetchone()
        require(row is not None, "unknown local request identity")
        params, job_id = strict_json(row[0]), row[1]
        require(
            digest(canonical({"profile_sha256": self.profile_sha, "params": params}))
            == row[3],
            "observation profile differs from the original candidate/runtime binding",
        )
        if not job_id:
            return strict_json(row[2])
        reference = {"host": params["host"], "job_id": job_id}
        base = {
            "request_id": request_id,
            **reference,
            "automatic_replay": False,
            "profile_sha256": self.profile_sha,
            "domain_success": False,
        }
        try:
            status = self.call("process_status", reference)
            self._event(request_id, "runtime_status", status)
            self.db.commit()
            proof = terminal_proof(status, job_id)
            if proof is None:
                return self._save(
                    request_id,
                    {
                        **base,
                        "state": "UNKNOWN",
                        "runtime_state": status.get("state"),
                        "reason": "original_job_has_no_complete_terminal_witness",
                    },
                )
            require(
                sum(proof["counts"].values()) <= self.max_output,
                "runtime output exceeds profile bound",
            )
            streams = {"stdout": bytearray(), "stderr": bytearray()}
            while any(len(streams[name]) < proof["counts"][name] for name in streams):
                result = self.call(
                    "process_read",
                    {
                        **reference,
                        "limit": 16384,
                        **{name + "_offset": len(streams[name]) for name in streams},
                    },
                )
                require(
                    result.get("job_id") == job_id,
                    "output page identifies a different job",
                )
                for name in streams:
                    page, offset, size = (
                        result[name],
                        len(streams[name]),
                        proof["counts"][name],
                    )
                    encoded = page["bytes_hex"]
                    require(
                        isinstance(encoded, str)
                        and re.fullmatch("(?:[0-9a-fA-F]{2})*", encoded),
                        "output page does not contain exact hexadecimal bytes",
                    )
                    raw = bytes.fromhex(encoded)
                    require(
                        len(raw) <= 16384
                        and page.get("offset") == offset
                        and page.get("size") == size
                        and page.get("next_offset") == offset + len(raw) <= size
                        and page.get("eof") is (offset + len(raw) == size)
                        and (raw or offset == size),
                        "output page changed its lossless byte cursor",
                    )
                    streams[name].extend(raw)
            final = self.call("process_status", reference)
            require(
                terminal_proof(final, job_id) == proof,
                "terminal publication changed during output read",
            )
            return self._save(
                request_id,
                {
                    **base,
                    "state": "TERMINAL",
                    "runtime_state": proof["state"],
                    "exit_code": proof["exit_code"],
                    "terminal_proof": proof,
                    "streams": {
                        name: {
                            "bytes": len(raw),
                            "sha256": digest(raw),
                            "bytes_hex": raw.hex(),
                        }
                        for name, raw in streams.items()
                    },
                    "actual_runtime_transport": self.identity.get("transport")
                    == "actual_mcp_stdio",
                },
            )
        except Exception as error:
            return self._save(
                request_id,
                {
                    **base,
                    "state": "UNKNOWN",
                    "reason": "original_observation_incomplete",
                    "error_type": type(error).__name__,
                },
            )

    def cancel(self, request_id):
        row = self.db.execute(
            "SELECT params,job_id,binding FROM operations WHERE request_id=?",
            (request_id,),
        ).fetchone()
        require(
            row is not None and row[1] is not None,
            "cancellation requires the original known job",
        )
        params = strict_json(row[0])
        require(
            digest(canonical({"profile_sha256": self.profile_sha, "params": params}))
            == row[2],
            "cancellation profile differs from the original candidate/runtime binding",
        )
        reference = {"host": params["host"], "job_id": row[1]}
        self._event(request_id, "cancel_intent", reference)
        self.db.commit()
        try:
            result = self.call("process_cancel", reference)
            self._event(request_id, "cancel_response", result)
            self.db.commit()
        except Exception as error:
            self._event(
                request_id, "cancel_unknown", {"error_type": type(error).__name__}
            )
            self.db.commit()
        return self.observe(request_id)

    def close(self):
        self.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--observe")
    parser.add_argument("--cancel")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(
        sum(x is not None for x in (args.request, args.observe, args.cancel)) == 1,
        "select exactly one request, observe or cancel",
    )
    profile = strict_json(args.profile.read_bytes())
    runtime = StdioRuntime(profile["runtime"])
    bridge = None
    try:
        bridge = RuntimeProcessBridge(
            profile, args.database, runtime.call, transport_identity=runtime.identity
        )
        result = (
            bridge.execute(strict_json(args.request.read_bytes()))
            if args.request
            else bridge.cancel(args.cancel)
            if args.cancel
            else bridge.observe(args.observe)
        )
        report = {
            "schema": "hepta.cell.runtime-bridge.observation.v1",
            "runtime": runtime.identity,
            "observation": result,
            "protocol": runtime.records,
            "final_use_capability_boundary_qualified": False,
            "worker_domain_result_requires_independent_validation": True,
        }
        with args.output.open("xb") as stream:
            stream.write(canonical(report) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(
            canonical(
                {
                    "state": result["state"],
                    "job_id": result.get("job_id"),
                    "report_sha256": file_digest(args.output),
                }
            ).decode()
        )
        return 0 if result["state"] == "TERMINAL" else 2
    finally:
        if bridge:
            bridge.close()
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
