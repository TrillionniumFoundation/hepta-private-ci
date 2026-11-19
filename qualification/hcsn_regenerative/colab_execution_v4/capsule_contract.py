"""Full single-group study capsules for an external, unique sequential owner.

This module does not launch, import, or run the training implementation. Capsules
retain all claimed attempts, both LR checkpoints, evaluations, block evidence,
exports and history receipts. They are complete snapshots, not operation deltas.
The manifest is canonical JSON plus one newline; parent_manifest_sha256 hashes
those exact bytes. A metadata transition check alone does not authenticate bytes.
"""

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
import time


SCHEMA = "hcsn-mechanism-study-capsule-v1"
MAX_FILES = 20000
MAX_TOTAL_BYTES = 2 * 1024**3
MAX_FILE_BYTES = 512 * 1024**2
MAX_MANIFEST_BYTES = 16 * 1024**2
MAX_ARCHIVE_BYTES = 2 * 1024**3
CATEGORIES = {"attempts", "evaluations", "blocks", "exports", "history-imports"}


class CapsuleError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _blob(value):
    return _canonical(value) + b"\n"


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _strict(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise CapsuleError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    def bad(value):
        raise CapsuleError("Nonfinite JSON number: " + str(value))
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
        _canonical(result)  # Also rejects exponent overflow converted to infinity.
        return result
    except (ValueError, TypeError, UnicodeError) as error:
        raise CapsuleError("Invalid strict JSON: " + str(error)) from error


def _version(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _safe_parents(path):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise CapsuleError("Parent traversal in an input/output path")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise CapsuleError("Symlink path component: " + str(component))
    return path


def _regular(path, limit=MAX_FILE_BYTES, content=False):
    path = _safe_parents(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise CapsuleError("Non-regular, hard-linked, or oversized file: " + str(path))
    hasher, chunks, count = hashlib.sha256(), [], 0
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        if _version(os.fstat(stream.fileno())) != _version(before):
            raise CapsuleError("File replaced before reading: " + str(path))
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            count += len(chunk)
            if count > limit:
                raise CapsuleError("File exceeds fixed size bound")
            hasher.update(chunk)
            if content:
                chunks.append(chunk)
    if _version(path.lstat()) != _version(before):
        raise CapsuleError("File changed while reading: " + str(path))
    return dict(bytes=count, sha256=hasher.hexdigest()), _version(before), b"".join(chunks) if content else None


def _name(value, directory=False):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise CapsuleError("Invalid relative path")
    if directory and value.endswith("/"):
        value = value[:-1]
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or str(PurePosixPath(value)) != value:
        raise CapsuleError("Path traversal or noncanonical path: " + value)
    if any(re.fullmatch(r"[A-Za-z0-9_.@+-]+", part) is None for part in parts):
        raise CapsuleError("Unsupported path component: " + value)
    return value


def _fit_ids(values):
    values = list(values)
    if not values or len(values) > 160 or len(values) != len(set(values)):
        raise CapsuleError("Expected fit roster is empty, duplicated, or too large")
    if any(not isinstance(v, str) or re.fullmatch(r"fit-[0-9]{3}", v) is None for v in values):
        raise CapsuleError("Invalid stable fit ID")
    return values


def _semantic(study, identity):
    if not isinstance(study, dict) or study.get("identity") != identity or not isinstance(study.get("created_at"), str):
        raise CapsuleError("Study identity differs")
    return _sha(_canonical({key: value for key, value in study.items() if key != "created_at"}))


def _group_roster(study, identity, group, expected):
    roster = study.get("ordered_fit_roster")
    if not isinstance(roster, list) or not roster or len(roster) != identity.get("registered_fit_count"):
        raise CapsuleError("Study lacks its full registered ordered roster")
    if _sha(_canonical(roster)) != identity.get("ordered_fit_roster_sha256"):
        raise CapsuleError("Study ordered roster differs from frozen identity")
    _fit_ids(row.get("fit_id") for row in roster)
    if [row.get("fit_id") for row in roster if row.get("group_id") == group] != expected:
        raise CapsuleError("Capsule group differs from the full registered roster")


def _validate_manifest(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise CapsuleError("Unsupported capsule manifest")
    try:
        _canonical(value)
    except (ValueError, TypeError) as error:
        raise CapsuleError("Manifest is not finite JSON") from error
    group = _name(value.get("group_id"))
    if "/" in group:
        raise CapsuleError("Group identity must be one component")
    expected = set(_fit_ids(value.get("expected_group_fit_ids", [])))
    files, directories = value.get("files"), value.get("directories")
    if (not isinstance(files, dict) or not isinstance(directories, list) or len(files) > MAX_FILES
            or len(directories) > MAX_FILES or len(directories) != len(set(directories))):
        raise CapsuleError("Missing, duplicated, or oversized inventory")
    dirs = set(directories)
    if not isinstance(value.get("identity"), dict) or "study.json" not in files:
        raise CapsuleError("Missing study identity or study.json")
    if set(files) & dirs:
        raise CapsuleError("A path cannot be both file and directory")
    total = 0
    for path in list(files) + directories:
        _name(path)
        parts = path.split("/")
        if parts[0] not in CATEGORIES and path != "study.json":
            raise CapsuleError("Unexpected study root member: " + path)
        if path == "study.json" and path in dirs:
            raise CapsuleError("study.json is not a file")
        if parts[0] in CATEGORIES and len(parts) == 1 and path in files:
            raise CapsuleError("Study category must be a directory")
        for count in range(1, len(parts)):
            if "/".join(parts[:count]) not in dirs:
                raise CapsuleError("Missing parent directory: " + path)
        if parts[0] in ("attempts", "evaluations") and len(parts) >= 2:
            if parts[1] not in expected or "/".join(parts[:2]) not in dirs:
                raise CapsuleError("Attempt/evaluation outside this statistical group: " + path)
        if parts[0] == "blocks" and len(parts) >= 2:
            if parts[1] != group or "/".join(parts[:2]) not in dirs:
                raise CapsuleError("Block outside this statistical group or not a directory")
        if path in files:
            entry = files[path]
            if (not isinstance(entry, dict) or type(entry.get("bytes")) is not int
                    or not 0 <= entry["bytes"] <= MAX_FILE_BYTES
                    or not isinstance(entry.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None):
                raise CapsuleError("Malformed file inventory entry: " + path)
            total += entry["bytes"]
    if total > MAX_TOTAL_BYTES:
        raise CapsuleError("Total study bytes exceed bound; no truncated capsules")
    claims = {kind: sorted(path.split("/")[1] for path in dirs if path.startswith(kind + "/") and path.count("/") == 1)
              for kind in ("attempts", "evaluations")}
    if value.get("claimed_fit_ids") != claims["attempts"] or value.get("claimed_evaluation_ids") != claims["evaluations"]:
        raise CapsuleError("Claim lists disagree with directory inventory")
    if not set(claims["evaluations"]).issubset(claims["attempts"]):
        raise CapsuleError("An evaluation lacks its training attempt")
    for field in ("study_semantic_sha256",):
        if not isinstance(value.get(field), str) or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
            raise CapsuleError("Missing study semantic digest")
    archive = value.get("archive", {})
    if (type(archive.get("bytes")) is not int or not 0 < archive["bytes"] <= MAX_ARCHIVE_BYTES
            or re.fullmatch(r"[0-9a-f]{64}", str(archive.get("sha256", ""))) is None):
        raise CapsuleError("Malformed archive binding")
    return value


def _manifest(value):
    if isinstance(value, dict):
        return _validate_manifest(value)
    _, _, raw = _regular(Path(value), MAX_MANIFEST_BYTES, content=True)
    return _validate_manifest(_strict(raw))


def validate_transition(prior_manifest, current_manifest, ever_claimed_fit_ids=(), ever_claimed_evaluation_ids=()):
    """Validate monotonic metadata. The caller must also verify capsule bytes."""
    current = _manifest(current_manifest)
    if not set(ever_claimed_fit_ids).issubset(current["claimed_fit_ids"]):
        raise CapsuleError("A previously claimed fit disappeared")
    if not set(ever_claimed_evaluation_ids).issubset(current["claimed_evaluation_ids"]):
        raise CapsuleError("A previously claimed evaluation disappeared")
    if prior_manifest is None:
        if current.get("parent_manifest_sha256") is not None:
            raise CapsuleError("Initial capsule unexpectedly names an unverified parent")
        return True
    prior = _manifest(prior_manifest)
    for name in ("identity", "group_id", "expected_group_fit_ids", "study_semantic_sha256"):
        if current[name] != prior[name]:
            raise CapsuleError("Frozen capsule field changed: " + name)
    if current.get("parent_manifest_sha256") != _sha(_blob(prior)):
        raise CapsuleError("Capsule parent manifest hash differs")
    if not set(prior["directories"]).issubset(current["directories"]):
        raise CapsuleError("Prior directory/empty claim disappeared")
    for path, entry in prior["files"].items():
        if path not in current["files"]:
            raise CapsuleError("Previously recorded file disappeared: " + path)
        if path != "study.json" and current["files"][path] != entry:
            raise CapsuleError("Immutable history changed: " + path)
    if not set(prior["claimed_fit_ids"]).issubset(current["claimed_fit_ids"]) or not set(prior["claimed_evaluation_ids"]).issubset(current["claimed_evaluation_ids"]):
        raise CapsuleError("Previously claimed operation disappeared")
    return True


def _inventory(study):
    study = _safe_parents(study)
    if not study.is_dir():
        raise CapsuleError("Study root is not a directory")
    files, versions, directories, total = {}, {}, [], 0
    for path in sorted(study.rglob("*")):
        relative = _name(path.relative_to(study).as_posix())
        item = path.lstat()
        if stat.S_ISDIR(item.st_mode):
            directories.append(relative)
        elif stat.S_ISREG(item.st_mode):
            files[relative], versions[relative], _ = _regular(path)
            total += files[relative]["bytes"]
        else:
            raise CapsuleError("Study contains a symlink or special file")
        if len(files) > MAX_FILES or len(directories) > MAX_FILES or total > MAX_TOTAL_BYTES:
            raise CapsuleError("Study inventory exceeds bounds; no truncation")
    return files, versions, directories


def _exclusive_json(path, value):
    raw = _blob(value)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise CapsuleError("Manifest exceeds bound")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def create_capsule(study, archive, manifest, identity, group_id, expected_group_fit_ids, prior_manifest=None):
    """Create exclusive new archive/manifest outside study; never mutate study."""
    began, cpu = time.monotonic(), time.process_time()
    study, archive, manifest = map(_safe_parents, (study, archive, manifest))
    if archive == manifest or archive.is_relative_to(study) or manifest.is_relative_to(study):
        raise CapsuleError("Capsule outputs must be distinct and outside the study")
    if archive.exists() or manifest.exists():
        raise CapsuleError("Capsule outputs already exist; never overwrite")
    expected = _fit_ids(expected_group_fit_ids)
    files, versions, directories = _inventory(study)
    _, _, raw = _regular(study / "study.json", MAX_MANIFEST_BYTES, content=True)
    study_record = _strict(raw)
    semantic = _semantic(study_record, identity)
    _group_roster(study_record, identity, group_id, expected)
    result = dict(schema=SCHEMA, identity=identity, group_id=group_id, expected_group_fit_ids=expected,
        created_at=datetime.now(timezone.utc).isoformat(), files=files, directories=directories,
        claimed_fit_ids=sorted(p.split("/")[1] for p in directories if p.startswith("attempts/") and p.count("/") == 1),
        claimed_evaluation_ids=sorted(p.split("/")[1] for p in directories if p.startswith("evaluations/") and p.count("/") == 1),
        study_semantic_sha256=semantic, parent_manifest_sha256=_sha(_blob(_manifest(prior_manifest))) if prior_manifest is not None else None,
        archive=dict(bytes=1, sha256="0" * 64), scope="Complete single-group study; full160 roster remains in study.json; no training authority or global mutex")
    validate_transition(prior_manifest, result)
    archive.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".capsule-", dir=archive.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with temporary_path.open("wb") as destination, gzip.GzipFile(fileobj=destination, mode="wb", mtime=0, filename="") as zipped, tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for name in directories:
                member = tarfile.TarInfo(name)
                member.type, member.mode = tarfile.DIRTYPE, 0o700
                tar.addfile(member)
            for name, entry in files.items():
                path = study / name
                if _version(path.lstat()) != versions[name]:
                    raise CapsuleError("Study changed during capsule assembly")
                member = tarfile.TarInfo(name)
                member.size, member.mode = entry["bytes"], 0o600
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
                    tar.addfile(member, source)
        final_files, _, final_directories = _inventory(study)
        if files != final_files or directories != final_directories:
            raise CapsuleError("Study changed during capsule assembly")
        result["archive"], _, _ = _regular(temporary_path, MAX_ARCHIVE_BYTES)
        validate_transition(prior_manifest, result)
        _verify_archive(temporary_path, result)
        result["creation_wall_seconds"] = time.monotonic() - began
        result["creation_process_cpu_seconds"] = time.process_time() - cpu
        result["cost_scope"] = "Assembly, full inventory and archive validation through prepublication; excludes publication; nested in provider job"
        result["full_physical_energy_joules"] = None
        os.link(temporary_path, archive)  # Exclusive publication, then remove only this helper's staging link.
        temporary_path.unlink()
        _exclusive_json(manifest, result)
    finally:
        temporary_path.unlink(missing_ok=True)
    return result


def _verify_archive(archive, manifest):
    entry, version, _ = _regular(archive, MAX_ARCHIVE_BYTES)
    if entry != manifest["archive"]:
        raise CapsuleError("Archive bytes or SHA256 differ")
    seen, study_raw = set(), None
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = _name(member.name, member.isdir())
            if name in seen or len(seen) >= MAX_FILES * 2:
                raise CapsuleError("Duplicate or excessive tar members")
            seen.add(name)
            if member.isdir():
                if name not in manifest["directories"] or member.size != 0:
                    raise CapsuleError("Unexpected tar directory")
            elif member.isreg():
                expected = manifest["files"].get(name)
                if expected is None or member.size != expected["bytes"]:
                    raise CapsuleError("Unexpected/oversized tar file")
                hasher, chunks, count = hashlib.sha256(), [], 0
                with tar.extractfile(member) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        count += len(chunk)
                        hasher.update(chunk)
                        if name == "study.json":
                            if count > MAX_MANIFEST_BYTES:
                                raise CapsuleError("study.json too large")
                            chunks.append(chunk)
                if count != expected["bytes"] or hasher.hexdigest() != expected["sha256"]:
                    raise CapsuleError("Tar file hash differs: " + name)
                if name == "study.json":
                    study_raw = b"".join(chunks)
            else:
                raise CapsuleError("Symlink, hardlink or special tar member rejected")
    if seen != set(manifest["files"]) | set(manifest["directories"]):
        raise CapsuleError("Tar inventory differs from complete manifest")
    study_record = _strict(study_raw)
    if _semantic(study_record, manifest["identity"]) != manifest["study_semantic_sha256"]:
        raise CapsuleError("Study semantic identity differs")
    _group_roster(study_record, manifest["identity"], manifest["group_id"], manifest["expected_group_fit_ids"])
    if _version(archive.lstat()) != version:
        raise CapsuleError("Archive changed during validation")
    return version


def restore_capsule(archive, manifest, destination, expected_identity, group_id, expected_group_fit_ids,
                    ever_claimed_fit_ids=(), ever_claimed_evaluation_ids=()):
    """Validate every member before writing a new empty destination, then copy.

Any exception means no permission to use/replay the destination. A concurrent
mutation during copying may leave partial diagnostic files; never reuse them.
"""
    archive, destination = map(_safe_parents, (archive, destination))
    value = _manifest(manifest)
    if (value["identity"] != expected_identity or value["group_id"] != group_id
            or value["expected_group_fit_ids"] != _fit_ids(expected_group_fit_ids)):
        raise CapsuleError("Capsule belongs to another frozen study/group")
    if not set(ever_claimed_fit_ids).issubset(value["claimed_fit_ids"]) or not set(ever_claimed_evaluation_ids).issubset(value["claimed_evaluation_ids"]):
        raise CapsuleError("Capsule omits a previously claimed operation")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise CapsuleError("Restore requires a new empty directory, never last-wins")
    try:
        version = _verify_archive(archive, value)
    except (tarfile.TarError, OSError, EOFError) as error:
        raise CapsuleError("Invalid archive: " + str(error)) from error
    if not destination.exists():
        destination.mkdir(parents=True, exist_ok=False)
    elif any(destination.iterdir()):
        raise CapsuleError("Destination changed after verification")
    for name in sorted(value["directories"], key=lambda x: (x.count("/"), x)):
        (destination / name).mkdir(mode=0o700, exist_ok=False)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if member.isdir():
                continue
            name = _name(member.name)
            if not member.isreg() or name not in value["files"]:
                raise CapsuleError("Archive mutated after verification")
            path, hasher, count = destination / name, hashlib.sha256(), 0
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as target, tar.extractfile(member) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    count += len(chunk)
                    if count > value["files"][name]["bytes"]:
                        raise CapsuleError("Archive file grew after verification")
                    target.write(chunk)
                    hasher.update(chunk)
            if dict(bytes=count, sha256=hasher.hexdigest()) != value["files"][name]:
                raise CapsuleError("Archive file changed after verification")
    if _version(archive.lstat()) != version:
        raise CapsuleError("Archive changed during materialization")
    files, _, directories = _inventory(destination)
    if files != value["files"] or directories != value["directories"]:
        raise CapsuleError("Restored tree differs from manifest")
    return value
