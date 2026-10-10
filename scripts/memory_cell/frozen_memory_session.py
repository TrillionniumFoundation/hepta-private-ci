"""Read-only experimental memory state committed BEFORE task exposure.

This is a local experiment journal, not a new cognitive.store or serving owner.
Externally declared event times are not independently attested future windows.
Reader/policy artifacts cannot be updated at query time. Current revocations also
apply on replay, and an interrupted attempt never silently becomes a second call.
"""

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time

from evidence_bundle import MAX_INDEX_BYTES, observed_time
from native import Document, digest
from reviewed_bundle import strict_read

SCHEMA = "hepta.frozen-experience-session.v1"
MAX_RECEIPT = 16 * 1024 * 1024


def publish(path, value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_RECEIPT:
        raise ValueError("experiment receipt byte budget")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Directory fsync is available on the Linux experiment hosts.
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(raw).hexdigest()


def freeze(output, documents, *, through, policy_bytes, policy_roots,
           reader_identity, source_commit, predecessor=None):
    """Persist past experience and an already produced policy; no Query argument.

    Policy bytes are opaque, hashed artifacts, not pickle/code executed here.
    Their training provenance/authority must still be checked by existing owners.
    """
    cutoff = observed_time(through)
    if (
        not 1 <= len(documents) <= 10000
        or len({d.identity for d in documents}) != len(documents)
        or len({d.scope for d in documents}) != 1
        or not isinstance(policy_bytes, bytes)
        or not 1 <= len(policy_bytes) <= 4 * 1024 * 1024
        or not re.fullmatch(r"[0-9a-f]{64}", reader_identity)
        or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or predecessor is not None and not re.fullmatch(r"[0-9a-f]{64}", predecessor)
    ):
        raise ValueError("bounded immutable experience/policy/reader required")
    total = sum(len(d.content.encode()) for d in documents)
    if total > MAX_INDEX_BYTES or any(observed_time(d.observed_at) > cutoff for d in documents):
        raise ValueError("unobserved future experience or write budget exceeded")
    roots = {d.root for d in documents}
    if not isinstance(policy_roots, (set, frozenset)) or not policy_roots <= roots:
        raise ValueError("policy has unbound training ancestors")
    documents = tuple(sorted(documents, key=lambda d: d.identity))
    value = dict(
        schema=SCHEMA, through=through, documents=[asdict(d) for d in documents],
        source_frontier=digest([asdict(d) for d in documents]),
        policy_sha256=hashlib.sha256(policy_bytes).hexdigest(),
        policy_roots=sorted(policy_roots), reader_identity=reader_identity,
        source_commit=source_commit, predecessor_snapshot=predecessor,
        input_source_bytes=total, policy_bytes=len(policy_bytes),
        committed_at_unix_ns=time.time_ns(), clock_independently_attested=False,
        production_accepted=False,
    )
    output.mkdir(mode=0o700)
    with (output / "policy.bin").open("xb") as stream:
        stream.write(policy_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    # READY is the only commit point. Crashes before it cannot open a session.
    snapshot_sha = publish(output / "snapshot.json", value)
    publish(output / "READY.json", dict(snapshot_sha256=snapshot_sha, schema=SCHEMA))
    return snapshot_sha


@contextmanager
def exclusive(directory):
    import fcntl

    fd = os.open(directory / "writer.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class FrozenMemorySession:
    def __init__(self, directory, *, expected_snapshot):
        self.directory = Path(directory)
        self.expected_snapshot = expected_snapshot
        self.state = strict_read(self.directory / "snapshot.json", expected_snapshot, MAX_RECEIPT)
        ready = json.loads((self.directory / "READY.json").read_text())
        if ready != dict(snapshot_sha256=expected_snapshot, schema=SCHEMA) or self.state["schema"] != SCHEMA:
            raise ValueError("uncommitted or incompatible memory snapshot")
        self.documents = tuple(Document(**(d | {"assets": tuple(d["assets"])}))
                               for d in self.state["documents"])
        self.originals = {d.identity: d for d in self.documents}
        if len(self.originals) != len(self.documents) or digest(self.state["documents"]) != self.state["source_frontier"]:
            raise ValueError("source frontier mismatch")
        self.roots = {d.root for d in self.documents} | set(self.state["policy_roots"])
        self._current(lambda: set())

    def _current(self, withdrawals):
        current = withdrawals()
        if not isinstance(current, (set, frozenset)) or any(not isinstance(r, str) for r in current):
            raise ValueError("explicit current owner withdrawal view required")
        if self.roots & current:
            raise ValueError("revoked snapshot requires owner rebuild")
        strict_read(self.directory / "snapshot.json", self.expected_snapshot, MAX_RECEIPT)
        path = self.directory / "policy.bin"
        if path.is_symlink() or path.stat().st_size != self.state["policy_bytes"]:
            raise ValueError("policy artifact changed")
        policy = path.read_bytes()
        if hashlib.sha256(policy).hexdigest() != self.state["policy_sha256"]:
            raise ValueError("query-time policy mutation")
        return policy, set(current)

    def answer(self, query, selector, reader, *, withdrawals, token_limit=2048):
        """Only query-time reads. The selector gets no gold labels or optimizer.

        The hash lock checks declared artifacts, not all possible Python globals;
        actual isolation and authorized effect fencing remain existing owners' work.
        """
        if query.scope != self.documents[0].scope or observed_time(query.observed_at) <= observed_time(self.state["through"]):
            raise ValueError("task must follow the frozen source cutoff in the same scope")
        if reader.identity != self.state["reader_identity"]:
            raise ValueError("shared reader identity changed")
        with exclusive(self.directory):
            policy, revoked = self._current(withdrawals)
            key = digest(asdict(query))
            started = self.directory / (key + ".started.json")
            completed = self.directory / (key + ".result.json")
            if started.exists():
                # Do not regenerate after lost acknowledgement or crash. Caller may
                # inspect the retained result, but never bypass current withdrawal.
                raise ValueError("duplicate or indeterminate task; no implicit replay")
            if len(list(self.directory.glob("*.started.json"))) >= 256:
                raise ValueError("bounded stream session exhausted")
            publish(started, dict(query=asdict(query), snapshot_sha256=self.expected_snapshot,
                                  exposed_at_unix_ns=time.time_ns(), policy_sha256=self.state["policy_sha256"]))
            begin = time.perf_counter()
            try:
                reader.verify_frozen()
                bundle = selector(query, self.documents, self.state["source_frontier"], policy, revoked)
                if bundle.mode not in ("ranked", "coverage", "empty", "stream_policy"):
                    raise ValueError("oracle/review projection is not an online selector")
                bundle.validate(query, self.originals, frontier=self.state["source_frontier"], revoked=revoked)
                answer, receipt = reader.answer(query, bundle, self.originals,
                    frontier=self.state["source_frontier"], revoked=revoked, token_limit=token_limit)
                if (
                    not isinstance(answer, str) or not answer.strip()
                    or receipt["reader_identity"] != reader.identity
                    or receipt["bundle_digest"] != bundle.seal()
                    or receipt["delivered_evidence"] != bundle.delivered()
                ):
                    raise ValueError("reader result detached from frozen evidence")
                reader.verify_frozen()
                _, revoked = self._current(withdrawals)
                bundle.validate(query, self.originals, frontier=self.state["source_frontier"], revoked=revoked)
                result = dict(status="succeeded", query_id=query.identity, answer=answer,
                              receipt=receipt, snapshot_sha256=self.expected_snapshot,
                              query_train_tokens=0, elapsed_seconds=time.perf_counter()-begin,
                              production_accepted=False, prospective_window_attested=False)
            except Exception as error:
                publish(completed, dict(status="failed", query_id=query.identity,
                    snapshot_sha256=self.expected_snapshot, error_type=type(error).__name__,
                    error=str(error)[:1024], elapsed_seconds=time.perf_counter()-begin))
                raise
            result_sha = publish(completed, result)
            return dict(record=result, result_sha256=result_sha)

    def replay(self, query, *, withdrawals, expected_result_sha256):
        with exclusive(self.directory):
            self._current(withdrawals)
            key = digest(asdict(query))
            result = self.directory / (key + ".result.json")
            if not result.is_file() or result.is_symlink() or result.stat().st_size > MAX_RECEIPT:
                raise ValueError("missing/indeterminate result; recovery cannot regenerate")
            value = strict_read(result, expected_result_sha256, MAX_RECEIPT)
            if value.get("snapshot_sha256") != self.expected_snapshot or value.get("query_id") != query.identity:
                raise ValueError("result identity mismatch")
            # Replay is a local diagnostic record read, not authenticated user delivery.
            return dict(record=value, result_sha256=expected_result_sha256)
