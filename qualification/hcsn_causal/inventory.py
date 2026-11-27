"""Read-only closure checks for a prospective, owner-complete attempt ledger.

Only <id>.start.json and <id>.terminal.json belong in this flat directory.
Starts contain START_FIELDS plus their schema; terminals contain their schema,
the raw start file's SHA256, and every field of an Attempt (including nulls).
JSON must have unique keys. Canonical content hashes use sorted-key compact
ASCII JSON with finite numbers. Raw file hashes additionally bind formatting.

The executor must supply its complete, closed directory, not a selected export.
Two stable reads and verification-time rescanning detect local omissions and
changes; they are neither a filesystem lock nor proof against a malicious
owner/Python caller that hides entire directories or forges its original data.
This module never writes a ledger, repairs a record, or launches an attempt.
"""

from dataclasses import asdict, dataclass, field, fields
import hashlib
import json
import os
from pathlib import Path
import re
import stat


START_SCHEMA = "hcsn-causal-start-v1"
TERMINAL_SCHEMA = "hcsn-causal-terminal-v1"
START_FIELDS = ("attempt_id", "arm", "seed", "design_sha256",
                "shared_initialization_sha256", "active_parameters", "state_scalars")
_NAME = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]{0,79})\.(start|terminal)\.json\Z")
_MAX_FILES, _MAX_FILE_BYTES, _MAX_BYTES = 4096, 65536, 16 * 1024 * 1024
_SCANNED = object()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _version(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(directory):
    before = directory.lstat()
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError("ledger must be a real directory, not a symlink")
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > _MAX_FILES:
                raise ValueError("ledger file limit exceeded")
    if not names or len({name.casefold() for name in names}) != len(names):
        raise ValueError("empty ledger or duplicate portable file names")
    records, total = [], 0
    for name in sorted(names):
        if not _NAME.fullmatch(name):
            raise ValueError("unknown ledger entry: " + name)
        path = directory / name
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= _MAX_FILE_BYTES):
            raise ValueError("expected bounded regular single-link ledger file")
        total += info.st_size
        if total > _MAX_BYTES:
            raise ValueError("ledger byte limit exceeded")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            if _version(os.fstat(handle.fileno())) != _version(info):
                raise ValueError("ledger file changed before read")
            data = handle.read(_MAX_FILE_BYTES + 1)
            if (_version(os.fstat(handle.fileno())) != _version(info)
                    or _version(path.lstat()) != _version(info) or len(data) != info.st_size):
                raise ValueError("ledger file changed during read")
        records.append((name, data, _version(info)))
    if _version(directory.lstat()) != _version(before):
        raise ValueError("ledger directory changed during read")
    return _version(before), tuple(records)


def _attempt_hashes(attempts):
    from .comparison import Attempt
    result = {}
    for attempt in attempts:
        if type(attempt) is not Attempt or attempt.attempt_id in result:
            raise ValueError("duplicate or invalid supplied attempt")
        payload = asdict(attempt)
        Attempt(**payload)  # Revalidate even if a caller bypassed frozen dataclasses.
        result[attempt.attempt_id] = _sha(_canonical(payload))
        if len(result) > _MAX_FILES // 2:
            raise ValueError("attempt limit exceeded")
    return tuple(sorted(result.items()))


@dataclass(frozen=True)
class AttemptInventory:
    """Evidence constructed by scanning files; verify again before qualification."""

    _directory: Path
    design_sha256: str
    starts: tuple
    terminals: tuple
    attempt_hashes: tuple
    _versions: tuple
    _origin: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self._origin is not _SCANNED:
            raise ValueError("use scan_inventory; caller assertions cannot close a ledger")

    def as_dict(self):
        result = {"schema": "hcsn-causal-inventory-v1", "directory": str(self._directory),
                  "design_sha256": self.design_sha256,
                  "starts": [dict(zip(("attempt_id", "file", "sha256"), r)) for r in self.starts],
                  "terminals": [dict(zip(("attempt_id", "file", "sha256"), r)) for r in self.terminals],
                  "attempts": [dict(zip(("attempt_id", "canonical_sha256"), r)) for r in self.attempt_hashes],
                  "version_fields": ["device", "inode", "mode", "links", "size", "mtime_ns", "ctime_ns"],
                  "directory_version": list(self._versions[0]),
                  "file_versions": [{"file": n, "version": list(v)} for n, v in self._versions[1]]}
        result["inventory_sha256"] = _sha(_canonical(result))
        return result

    def verify(self, design, attempts):
        """Raise on stale evidence, omitted/extra attempts, or changed costs/content."""
        _, current = scan_inventory(self._directory, design)
        if current.as_dict() != self.as_dict():
            raise ValueError("ledger changed since inventory construction")
        if _attempt_hashes(attempts) != self.attempt_hashes:
            raise ValueError("supplied attempts differ from the complete ledger")


def scan_inventory(directory, design):
    """Return (all_attempts, inventory), failing closed on pending/unknown records.

    Failed, OOM and unavailable terminals remain present. Unknown cost fields
    remain null for the comparison gate; an unknown *outcome* cannot close a run.
    """
    from .comparison import Attempt, Design
    if type(design) is not Design:
        raise ValueError("validated frozen design required")
    directory = Path(directory).absolute()
    try:
        snapshot = _snapshot(directory)
        if _snapshot(directory) != snapshot:
            raise ValueError("ledger changed between complete reads")
        starts, terminals = {}, {}
        for name, raw, version in snapshot[1]:
            identity, kind = _NAME.fullmatch(name).groups()
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
            if not isinstance(data, dict):
                raise ValueError("ledger record must be a JSON object")
            destination = starts if kind == "start" else terminals
            destination[identity] = (name, raw, data)
        if set(starts) != set(terminals):
            raise ValueError("unclosed ledger: independent start/terminal sets differ")
        if len({identity.casefold() for identity in starts}) != len(starts):
            raise ValueError("duplicate portable attempt identities")
        attempts = []
        for identity in sorted(starts):
            name, raw, start = starts[identity]
            terminal = terminals[identity][2]
            if (set(terminal) != {"schema", "start_sha256", "attempt"}
                    or terminal["schema"] != TERMINAL_SCHEMA
                    or terminal["start_sha256"] != _sha(raw)):
                raise ValueError("terminal schema or original start hash mismatch")
            payload = terminal["attempt"]
            if not isinstance(payload, dict) or set(payload) != {f.name for f in fields(Attempt)}:
                raise ValueError("terminal must contain every Attempt field exactly")
            attempt = Attempt(**payload)
            expected = {"schema": START_SCHEMA, **{k: payload[k] for k in START_FIELDS}}
            if _canonical(start) != _canonical(expected) or attempt.attempt_id != identity:
                raise ValueError("start identity/schema differs from its terminal or filename")
            if (attempt.design_sha256 != design.identity() or attempt.seed not in design.seeds
                    or attempt.active_parameters != design.active_parameters
                    or attempt.state_scalars != design.state_scalars):
                raise ValueError("attempt is outside the frozen design")
            if attempt.status == "unknown":
                raise ValueError("unknown attempt outcome cannot close the ledger")
            attempts.append(attempt)
        inventory = AttemptInventory(
            directory, design.identity(),
            tuple((i, starts[i][0], _sha(starts[i][1])) for i in sorted(starts)),
            tuple((i, terminals[i][0], _sha(terminals[i][1])) for i in sorted(terminals)),
            _attempt_hashes(attempts),
            (snapshot[0], tuple((n, v) for n, raw, v in snapshot[1])), _SCANNED)
        return tuple(attempts), inventory
    except (OSError, UnicodeError, RecursionError, TypeError) as error:
        raise ValueError("unreadable or invalid ledger") from error
