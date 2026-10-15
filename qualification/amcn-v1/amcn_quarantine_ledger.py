"""Durable, fail-closed, *research-only* Cell quarantine journal.

The authoritative cognitive.store, Learning Artifacts and Neuron Runtime Owners
are external. This POSIX single-host gate is a candidate integration port, NOT
an owner of production authority, a distribution protocol or model unlearning.

Events are immutable, sha256-named, fsynced and hash-chained. Mutations require
both a compare-and-swap head and an *externally* pinned source frontier. Reads
require a separately retained journal-head pin, current source frontier and
full model lineage. They refuse any uncommitted write or corrupt journal.

Holding this local lock does not lock the actual production source store; a
production runtime must use its own authoritative transaction/fencing owner.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from amcn_core import canonical, digest, is_sha, require, shadow_disposition
from amcn_revocation import CellGeneration, revocation_census

PROFILE = "hepta.amcn.quarantine-local-journal.v1"
ZERO_SHA = "0" * 64
MAX_EVENTS = 4096
MAX_EVENT_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_FILENAME = re.compile(r"([0-9]{10})-([0-9a-f]{64})\.json")
_PENDING = ".pending-"


def _duplicates(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate journal JSON field")
        out[key] = value
    return out


def _invalid_constant(value):
    require(False, "invalid journal JSON constant: " + value)


def _directory(path):
    require(not path.is_symlink() and path.is_dir(), "untrusted journal directory")
    require(stat.S_ISDIR(path.lstat().st_mode), "journal directory is not physical")
    require(not path.stat().st_mode & 0o022, "journal directory is writable by other users")


def _file_read(path):
    require(not path.is_symlink() and path.is_file(), "nonregular or linked journal record")
    require(path.stat().st_size <= MAX_EVENT_BYTES, "journal record exceeds resource ceiling")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        inode = os.fstat(fd)
        require(stat.S_ISREG(inode.st_mode) and inode.st_size <= MAX_EVENT_BYTES,
                "journal record changed during read")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_EVENT_BYTES + 1)
    finally:
        os.close(fd)
    require(0 < len(raw) <= MAX_EVENT_BYTES, "empty or truncated journal")
    try:
        record = json.loads(raw, object_pairs_hook=_duplicates,
                            parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, TypeError) as error:
        raise ValueError("invalid journal JSON") from error
    require(isinstance(record, dict) and raw == canonical(record) + b"\n",
            "journal record is not canonical")
    return record, sha256(raw).hexdigest()


def _ledger_manifest(artifacts):
    require(isinstance(artifacts, (list, tuple)) and all(isinstance(a, CellGeneration)
                                                        for a in artifacts), "actual artifact manifests required")
    return digest(sorted(a.manifest_sha256 for a in artifacts))


class ShadowQuarantineLedger:
    """Serializes research revocation decisions in one locally owned directory.

    A caller must retain the last returned event SHA outside this directory.
    No named user, plugin or service can infer execution authorization from an
    unquarantined research record; all outputs set production_accepted=False.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.events = self.root / "events"

    def _bootstrap(self):
        # Explicit bootstrap by the local experimenter. Never silently create
        # an empty 'approved' directory when a previous ledger disappears.
        require(not self.root.exists(), "journal already exists or must be recovered")
        require(not self.root.parent.is_symlink(), "linked journal parent")
        self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.events.mkdir(mode=0o700, exist_ok=False)
        fd = os.open(self.root / "writer.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        self._sync_dir(self.events)
        self._sync_dir(self.root)

    @staticmethod
    def _sync_dir(path):
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def _lock(self):
        _directory(self.root)
        _directory(self.events)
        lock = self.root / "writer.lock"
        require(not lock.is_symlink() and lock.is_file(), "journal writer lock absent")
        fd = os.open(lock, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        try:
            lock_stat = os.fstat(fd)
            require(stat.S_ISREG(lock_stat.st_mode) and not lock_stat.st_mode & 0o077,
                    "journal lock is not a private file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _scan(self, *, pending_is_error=True):
        names = sorted(self.events.iterdir(), key=lambda p: p.name)
        require(len(names) <= MAX_EVENTS + 32, "too many files in journal")
        pending = [x for x in names if x.name.startswith(_PENDING)]
        if pending_is_error:
            require(not pending, "incomplete journal transaction: explicit recovery required")
        committed = []
        for entry in names:
            if entry in pending:
                require(entry.is_file() and not entry.is_symlink(), "unsafe pending record")
                continue
            match = _FILENAME.fullmatch(entry.name)
            require(match is not None, "unknown journal record (fail closed)")
            committed.append((int(match.group(1)), match.group(2), entry))
        require(len(committed) <= MAX_EVENTS, "journal event budget")
        require(sum(path.stat().st_size for _, _, path in committed) <= MAX_JOURNAL_BYTES,
                "journal total bytes exceeded")
        head, prev, quarantine = None, ZERO_SHA, set()
        origin = None
        for index, (sequence, name_sha, path) in enumerate(committed, start=1):
            require(sequence == index, "journal sequence gap/reordering")
            event, record_sha = _file_read(path)
            require(record_sha == name_sha and set(event) == {
                "schema", "sequence", "prev_sha256", "scope", "generation",
                "artifact_manifest_sha256", "source_frontier_sha256",
                "quarantined_artifact_ids", "census_sha256", "production_accepted",
                "recovery_pending_count"
            }, "journal record content/hash drift")
            require(event["schema"] == PROFILE and type(event["sequence"]) is int
                    and event["sequence"] == index and event["prev_sha256"] == prev
                    and event["production_accepted"] is False,
                    "journal chain/authority drift")
            require(all(is_sha(event[k]) for k in (
                "artifact_manifest_sha256", "source_frontier_sha256", "census_sha256")),
                "journal digest malformed")
            require(type(event["recovery_pending_count"]) is int
                    and 0 <= event["recovery_pending_count"] <= 32,
                    "journal recovery counter malformed")
            require(isinstance(event["scope"], str) and event["scope"] and
                    isinstance(event["generation"], str) and event["generation"],
                    "journal scope/generation missing")
            epoch = (event["scope"], event["generation"], event["artifact_manifest_sha256"])
            if origin is None:
                origin = epoch
            require(origin == epoch, "journal lineage changed: reject new-generation reuse")
            ids = event["quarantined_artifact_ids"]
            require(isinstance(ids, list) and all(is_sha(x) for x in ids) and
                    ids == sorted(set(ids)) and quarantine <= set(ids),
                    "journal attempted quarantine rollback")
            quarantine = set(ids)
            head, prev = event, record_sha
        return head, prev, pending

    def _commit(self, event, *, crash_at=None):
        require(crash_at in (None, "prepared", "linked"), "unknown fault-injection site")
        encoded = canonical(event) + b"\n"
        require(len(encoded) <= MAX_EVENT_BYTES, "event exceeds journal budget")
        fingerprint = sha256(encoded).hexdigest()
        name = f"{event['sequence']:010d}-{fingerprint}.json"
        destination = self.events / name
        require(not destination.exists(), "immutable journal record already exists")
        fd, temp = tempfile.mkstemp(prefix=_PENDING, dir=self.events)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as out:
                out.write(encoded)
                out.flush()
                os.fsync(fd)
            if crash_at == "prepared":
                # Emulates process crash after file fsync, before publish.
                # Deliberately leave pending evidence to block future reads.
                return None
            os.link(temp, destination, follow_symlinks=False)
            if crash_at == "linked":
                # Emulates process crash after hard-link publish, before directory
                # fsync. A host restart must detect and recover orphan temp.
                return None
            self._sync_dir(self.events)
            os.unlink(temp)
            self._sync_dir(self.events)
        finally:
            os.close(fd)
        return fingerprint

    def apply(self, artifacts, current_sources, *, scope, generation,
              externally_pinned_frontier_sha256, expected_previous_sha256,
              initialize=False, crash_at=None):
        require(is_sha(expected_previous_sha256), "out-of-band previous journal pin required")
        require(is_sha(externally_pinned_frontier_sha256), "external latest-source pin required")
        if initialize:
            # A malformed source pin/lineage must not leave a half-created
            # journal root that later looks like a valid empty owner.
            require(expected_previous_sha256 == ZERO_SHA,
                    "a fresh journal must start at the all-zero parent")
            revocation_census(
                artifacts, current_sources, scope=scope, generation=generation,
                externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
            )
            self._bootstrap()
        with self._lock():
            old, previous_sha, pending = self._scan()
            require(previous_sha == expected_previous_sha256,
                    "stale writer / expected previous hash differs")
            require(old is None or (old["scope"] == scope and old["generation"] == generation
                    and old["artifact_manifest_sha256"] == _ledger_manifest(artifacts)),
                    "scope/generation/artifact manifest drift")
            report = revocation_census(
                artifacts, current_sources, scope=scope, generation=generation,
                externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
                old_quarantined=old["quarantined_artifact_ids"] if old else (),
            )
            quarantine = report["metrics"]["quarantined_artifact_ids"]
            event = {
                "schema": PROFILE, "sequence": 1 if old is None else old["sequence"] + 1,
                "prev_sha256": previous_sha, "scope": scope, "generation": generation,
                "artifact_manifest_sha256": _ledger_manifest(artifacts),
                "source_frontier_sha256": externally_pinned_frontier_sha256,
                "quarantined_artifact_ids": quarantine,
                "census_sha256": digest(report), "production_accepted": False,
                "recovery_pending_count": 0,
            }
            emitted = self._commit(event, crash_at=crash_at)
            return shadow_disposition(
                profile=PROFILE, recorded=emitted is not None,
                journal_head_sha256=emitted,
                recorded_sequence=event["sequence"],
                quarantined_artifact_ids=quarantine,
                actual_weight_unlearning=False,
                runtime_execution_enabled=False,
                independent_selector_accepted=False,
                crash_simulated=crash_at is not None,
            )

    def recover(self, artifacts, current_sources, *, scope, generation,
                externally_pinned_frontier_sha256, expected_previous_sha256):
        """Recover an interrupted write only by a NEW pinned source census.

        No orphan is automatically 'approved': revalidate the latest source
        inventory, then persist an additional monotonic event before clearing
        any in-flight artifact. If the source pin changed, recovery refuses.
        """
        require(is_sha(expected_previous_sha256) and
                is_sha(externally_pinned_frontier_sha256), "independent recovery pins")
        with self._lock():
            old, previous_sha, pending = self._scan(pending_is_error=False)
            require(len(pending) == 1,
                    "exactly one interrupted transaction required for recovery")
            require(previous_sha == expected_previous_sha256,
                    "stale recovery / previous journal pin changed")
            require(old is not None and old["scope"] == scope and old["generation"] == generation
                    and old["artifact_manifest_sha256"] == _ledger_manifest(artifacts),
                    "recovery lineage changed")
            # A prepared, fsynced event may contain the ONLY observation that
            # a source was revoked before its original bytes reappeared. Never
            # discard its adverse quarantine during crash recovery. A pending
            # event is also untrusted input: accept only the exact canonical
            # event the normal writer could have produced on this lineage.
            attempted, pending_sha = _file_read(pending[0])
            require(set(attempted) == {
                "schema", "sequence", "prev_sha256", "scope", "generation",
                "artifact_manifest_sha256", "source_frontier_sha256",
                "quarantined_artifact_ids", "census_sha256", "production_accepted",
                "recovery_pending_count",
            }, "unrecognized pending journal fields")
            require(attempted["schema"] == PROFILE
                    and attempted["scope"] == scope
                    and attempted["generation"] == generation
                    and attempted["artifact_manifest_sha256"] == _ledger_manifest(artifacts)
                    and attempted["production_accepted"] is False
                    and type(attempted["recovery_pending_count"]) is int
                    and attempted["recovery_pending_count"] == 0
                    and is_sha(attempted["source_frontier_sha256"])
                    and is_sha(attempted["census_sha256"]),
                    "pending journal identity or authority drift")
            if pending_sha == previous_sha:
                # Crash AFTER hard-link publication; it must be byte-identical
                # to the final already-scanned committed event.
                require(attempted == old, "pending hard-link mismatches committed event")
            else:
                # Crash BEFORE hard-link publication. No later write is
                # possible until recovery, so its parent must be the head.
                require(type(attempted["sequence"]) is int
                        and attempted["sequence"] == old["sequence"] + 1
                        and attempted["prev_sha256"] == previous_sha,
                        "pending transaction does not descend from current head")
            old_ids = set(old["quarantined_artifact_ids"])
            pending_ids = attempted["quarantined_artifact_ids"]
            require(isinstance(pending_ids, list)
                    and pending_ids == sorted(set(pending_ids))
                    and all(is_sha(i) for i in pending_ids)
                    and old_ids <= set(pending_ids)
                    and set(pending_ids) <= {a.artifact_id for a in artifacts},
                    "pending journal attempted invalid quarantine rollback")
            report = revocation_census(
                artifacts, current_sources, scope=scope, generation=generation,
                externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
                old_quarantined=pending_ids,
            )
            event = {
                "schema": PROFILE, "sequence": old["sequence"] + 1,
                "prev_sha256": previous_sha, "scope": scope, "generation": generation,
                "artifact_manifest_sha256": _ledger_manifest(artifacts),
                "source_frontier_sha256": externally_pinned_frontier_sha256,
                "quarantined_artifact_ids": report["metrics"]["quarantined_artifact_ids"],
                "census_sha256": digest(report), "production_accepted": False,
                "recovery_pending_count": len(pending),
            }
            new_sha = self._commit(event)
            for item in pending:
                os.unlink(item)
            self._sync_dir(self.events)
            return shadow_disposition(
                profile=PROFILE, recovery_committed=True,
                journal_head_sha256=new_sha, discarded_orphan_count=len(pending),
                recovered_pending_event_sha256=pending_sha,
                pending_quarantine_ids_preserved=len(pending_ids),
                quarantined_artifact_ids=event["quarantined_artifact_ids"],
                production_runtime_reattachment=False,
                actual_source_deletion_verified=False,
            )

    def _check_shadow_candidate_unlocked(self, artifact_id, artifacts, current_sources, *,
                                         scope, generation,
                                         externally_pinned_frontier_sha256,
                                         expected_journal_head_sha256):
        # The caller owns the local ledger lock. This routine does NOT fence
        # a separate authoritative Source Store or the production Runtime.
        require(is_sha(artifact_id) and is_sha(expected_journal_head_sha256),
                "exact candidate ID and independently kept journal head required")
        require(is_sha(externally_pinned_frontier_sha256), "fresh source frontier pin required")
        latest, head_sha, pending = self._scan()
        require(latest is not None and head_sha == expected_journal_head_sha256,
                "empty/rolled-back/stale quarantine head")
        require((latest["scope"], latest["generation"],
                 latest["artifact_manifest_sha256"]) == (
                     scope, generation, _ledger_manifest(artifacts)),
                "unregistered lineage/scope/generation")
        require(latest["source_frontier_sha256"] == externally_pinned_frontier_sha256,
                "source frontier newer than committed quarantine")
        require(artifact_id in {a.artifact_id for a in artifacts}, "unregistered Cell artifact")
        recomputed = revocation_census(
            artifacts, current_sources, scope=scope, generation=generation,
            externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
            old_quarantined=latest["quarantined_artifact_ids"],
        )
        require(recomputed["metrics"]["quarantined_artifact_ids"] ==
                latest["quarantined_artifact_ids"], "new source changes require another journal event")
        require(artifact_id not in latest["quarantined_artifact_ids"],
                "Cell parameter ancestor has been revoked or changed")
        return shadow_disposition(
            profile=PROFILE + ".preflight.v1",
            journal_head_sha256=head_sha,
            source_frontier_sha256=externally_pinned_frontier_sha256,
            artifact_manifest_sha256=latest["artifact_manifest_sha256"],
            candidate_artifact_id=artifact_id,
            eligible_for_local_shadow_replay=True,
            granted_runtime_ability=False,
            independent_source_owner_fenced=False,
            model_weight_reexecution_performed=False,
            production_head_activation_allowed=False,
        )

    @contextmanager
    def hold_shadow_candidate(self, artifact_id, artifacts, current_sources, *,
                              scope, generation, externally_pinned_frontier_sha256,
                              expected_journal_head_sha256):
        """Hold one local owner lock while a bounded SHADOW consumer inspects.

        This blocks competing writes to this journal, not external source-store
        changes or independently running product inference.control requests.
        Product hosts must implement the analogous check in their own CAS
        transaction/fence; this lock must never be described as that host fence.
        """
        with self._lock():
            preflight = self._check_shadow_candidate_unlocked(
                artifact_id, artifacts, current_sources, scope=scope,
                generation=generation,
                externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
                expected_journal_head_sha256=expected_journal_head_sha256,
            )
            yield preflight

    def preflight(self, artifact_id, artifacts, current_sources, *, scope, generation,
                  externally_pinned_frontier_sha256, expected_journal_head_sha256):
        """Return a candidate-study decision; NEVER production execution permission."""
        with self.hold_shadow_candidate(
            artifact_id, artifacts, current_sources,
            scope=scope, generation=generation,
            externally_pinned_frontier_sha256=externally_pinned_frontier_sha256,
            expected_journal_head_sha256=expected_journal_head_sha256,
        ) as receipt:
            return receipt
