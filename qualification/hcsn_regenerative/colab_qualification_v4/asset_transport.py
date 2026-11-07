"""Exact immutable assets over the existing bounded Colab Contents interface.

No allocation, kernel creation, Engine submission, run, cancellation or release.
The native caller supplies the already verified OfficialSDKProvider and the SAME
authoritative adapter Ledger. Unknown PUT effects are read back, never repeated.
"""
from dataclasses import asdict
import base64
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import zipfile
import zlib

SCHEMA = "hcsn-colab-immutable-assets-v4"
PUBLIC_PATH = "qualification/hcsn_regenerative/colab_qualification_v4/asset_transport.py"
CHUNK = 65536
MAX_ARCHIVE = 134217728
MAX_MEMBERS = 4096
ACTIVE = {"queued", "dispatched", "running", "cancel_requested", "unknown"}
SAFE_ERRORS = {"FileNotFoundError", "TimeoutError", "ReadTimeout", "ConnectTimeout",
               "ConnectionError", "HTTPError", "IntegrityError", "OSError", "AssetError"}


class AssetError(Exception):
    """Fixed, non-sensitive error codes only."""


def require(ok, code):
    if not ok:
        raise AssetError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_error(error):
    name = type(error).__name__
    return name if name in SAFE_ERRORS else "OtherException"


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _relative(value):
    require(isinstance(value, str) and 1 <= len(value.encode()) <= 512,
            "MEMBER_PATH_INVALID")
    require(not value.startswith("/") and "\\" not in value and "\0" not in value
            and all(p not in ("", ".", "..") for p in value.split("/")), "MEMBER_PATH_INVALID")
    return value


def _parent(path):
    path = Path(path).absolute()
    require(".." not in path.parts, "LOCAL_PATH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, path.name
    except BaseException:
        os.close(fd)
        raise


def regular_bytes(path, limit=MAX_ARCHIVE):
    parent, name = _parent(path)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit,
                    "LOCAL_FILE_UNSAFE")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        version = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(version(before) == version(after) and len(raw) == before.st_size, "LOCAL_FILE_CHANGED")
        return raw
    finally:
        os.close(parent)


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "DUPLICATE_JSON_KEY")
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=pairs)
    canonical(value)
    return value


def _new_file(path, raw):
    parent, name = _parent(path)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def validate_manifest(raw, expected_sha):
    require(isinstance(raw, bytes) and len(raw) <= 2097152 and _hash(expected_sha)
            and sha(raw) == expected_sha, "MANIFEST_IDENTITY")
    value = _json(raw)
    require(set(value) == {"schema", "request_id", "remote_root", "archive", "files", "parts", "limits"}
            and value["schema"] == SCHEMA, "MANIFEST_SCHEMA")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["request_id"]) is not None,
            "REQUEST_ID_INVALID")
    root = value["remote_root"]
    require(isinstance(root, str) and root.startswith("/content/")
            and str(PurePosixPath(root)) == root
            and all(p not in ("", ".", "..") for p in root[1:].split("/")), "REMOTE_ROOT_INVALID")
    limits = value["limits"]
    require(set(limits) == {"max_archive_bytes", "max_member_bytes", "max_total_member_bytes"}
            and _integer(limits["max_archive_bytes"], 1, MAX_ARCHIVE)
            and limits["max_member_bytes"] == limits["max_archive_bytes"]
            and limits["max_total_member_bytes"] == limits["max_archive_bytes"] * 4, "ASSET_LIMITS_INVALID")
    archive = value["archive"]
    require(set(archive) == {"bytes", "sha256"} and _hash(archive["sha256"])
            and _integer(archive["bytes"], 1, limits["max_archive_bytes"]), "ARCHIVE_LIMIT")
    files = value["files"]
    require(isinstance(files, dict) and 1 <= len(files) <= MAX_MEMBERS, "MEMBER_COUNT")
    for path, item in files.items():
        _relative(path)
        require(set(item) == {"bytes", "sha256"} and _hash(item["sha256"])
                and _integer(item["bytes"], 0, limits["max_member_bytes"]), "MEMBER_IDENTITY")
        require(not any(str(parent) in files for parent in PurePosixPath(path).parents), "MEMBER_PREFIX_CONFLICT")
    require(sum(item["bytes"] for item in files.values()) <= limits["max_total_member_bytes"], "UNPACKED_LIMIT")
    parts, offset = value["parts"], 0
    require(isinstance(parts, list) and len(parts) == math.ceil(archive["bytes"] / CHUNK), "PART_COUNT")
    prefix = "hepta-asset-v4-" + sha(value["request_id"].encode()) + "-" + archive["sha256"]
    for index, part in enumerate(parts):
        name = "part-" + str(index).zfill(5) + ".bin"
        remote = root + "/" + prefix + "-" + str(index).zfill(5) + ".bin"
        require(set(part) == {"index", "offset", "bytes", "sha256", "local_name", "remote_path"}
                and part["index"] == index and type(part["index"]) is int
                and part["offset"] == offset and type(part["offset"]) is int
                and part["bytes"] == min(CHUNK, archive["bytes"] - offset)
                and type(part["bytes"]) is int and _hash(part["sha256"])
                and part["local_name"] == name and part["remote_path"] == remote, "PART_IDENTITY")
        offset += part["bytes"]
    require(offset == archive["bytes"], "PART_TOTAL")
    return value


def prepare_archive(files, output_dir, request_id, remote_root, max_archive_bytes=33554432):
    """Offline: one deterministic ZIP and independently hashed <=64KiB parts."""
    require(_integer(max_archive_bytes, 1, MAX_ARCHIVE), "ASSET_LIMITS_INVALID")
    require(isinstance(files, dict) and 1 <= len(files) <= MAX_MEMBERS, "MEMBER_COUNT")
    content = {_relative(name): regular_bytes(path, max_archive_bytes) for name, path in files.items()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(content.items()):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type, info.create_system = zipfile.ZIP_DEFLATED, 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    raw = buffer.getvalue()
    manifest = dict(schema=SCHEMA, request_id=request_id, remote_root=remote_root,
                    archive=dict(bytes=len(raw), sha256=sha(raw)),
                    files={n: dict(bytes=len(b), sha256=sha(b)) for n, b in sorted(content.items())},
                    parts=[], limits=dict(max_archive_bytes=max_archive_bytes,
                    max_member_bytes=max_archive_bytes, max_total_member_bytes=max_archive_bytes * 4))
    prefix = "hepta-asset-v4-" + sha(request_id.encode()) + "-" + sha(raw)
    for index, offset in enumerate(range(0, len(raw), CHUNK)):
        piece = raw[offset:offset + CHUNK]
        manifest["parts"].append(dict(index=index, offset=offset, bytes=len(piece), sha256=sha(piece),
            local_name="part-" + str(index).zfill(5) + ".bin",
            remote_path=remote_root + "/" + prefix + "-" + str(index).zfill(5) + ".bin"))
    encoded = canonical(manifest) + b"\n"
    validate_manifest(encoded, sha(encoded))
    output = Path(output_dir).absolute()
    parent, name = _parent(output)
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    finally:
        os.close(parent)
    _new_file(output / "assets.zip", raw)
    (output / "parts").mkdir(mode=0o700)
    for part in manifest["parts"]:
        _new_file(output / "parts" / part["local_name"], raw[part["offset"]:part["offset"] + part["bytes"]])
    _new_file(output / "asset-manifest.json", encoded)
    return dict(manifest_path=str(output / "asset-manifest.json"), manifest_sha256=sha(encoded),
                archive_sha256=sha(raw), parts_dir=str(output / "parts"), manifest=manifest)


def materialize_assets(manifest_bytes, expected_sha, destination):
    """Cloud-side local reads only. Validate every byte before writing members."""
    manifest = validate_manifest(manifest_bytes, expected_sha)
    pieces = []
    for part in manifest["parts"]:
        raw = regular_bytes(part["remote_path"], CHUNK)
        require(len(raw) == part["bytes"] and sha(raw) == part["sha256"], "REMOTE_PART_CHANGED")
        pieces.append(raw)
    raw = b"".join(pieces)
    require(len(raw) == manifest["archive"]["bytes"] and sha(raw) == manifest["archive"]["sha256"],
            "ARCHIVE_IDENTITY")
    verified = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and set(names) == set(manifest["files"]), "ARCHIVE_ROSTER")
        for name in names:
            info, item = archive.getinfo(name), manifest["files"][name]
            require(not info.is_dir() and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                    and info.file_size == item["bytes"], "ARCHIVE_MEMBER_TYPE")
            data = archive.read(info)  # zipfile checks this member's CRC.
            require(len(data) == item["bytes"] and sha(data) == item["sha256"], "ARCHIVE_MEMBER_IDENTITY")
            verified[name] = data
    target = Path(destination).absolute()
    parent, name = _parent(target)
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    finally:
        os.close(parent)
    for name, data in sorted(verified.items()):
        path = target / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _new_file(path, data)
    return dict(schema="hcsn-colab-asset-materialization-v4", status="VERIFIED",
                request_id=manifest["request_id"], manifest_sha256=expected_sha,
                archive=manifest["archive"], files=manifest["files"], member_crc_verified=True,
                destination_name=target.name, network_operations=0, model_executions=0)


def _idle_identity(provider, ledger, expected_root, anchor_job_id, expected_profile):
    profile = provider.profile
    fields = asdict(profile)
    require(sha(canonical(fields)) == profile.fingerprint == expected_profile, "PROFILE_IDENTITY")
    require(Path(ledger.root).absolute() == Path(expected_root).absolute()
            and Path(ledger.path).absolute() == Path(expected_root).absolute() / "jobs.sqlite3",
            "AUTHORITATIVE_LEDGER_PATH")
    regular_bytes(ledger.path, 134217728)
    with ledger.connection() as db:
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (anchor_job_id,)).fetchone()
        require(row is not None, "ANCHOR_JOB_ABSENT")
        anchor = ledger.decoded(row)
        busy = db.execute("SELECT state FROM jobs WHERE endpoint=? AND kernel_id=?",
                          (profile.endpoint, profile.kernel_id)).fetchall()
        require(not any(row["state"] in ACTIVE for row in busy), "ADAPTER_SESSION_BUSY_OR_UNKNOWN")
    receipt = anchor.get("receipt") or {}
    require(anchor["state"] == "succeeded" and receipt.get("cloud_execution_stopped") is True
            and receipt.get("cloud_process_group_alive") is False, "ANCHOR_NOT_STOPPED_SUCCESS")
    require(all(anchor[k] == getattr(profile, k) for k in ("endpoint", "kernel_id", "session_id"))
            and anchor["profile"]["remote_root"] == profile.remote_root
            and anchor["remote_dir"] == profile.remote_root + "/" + anchor_job_id, "ANCHOR_IDENTITY")
    return dict(profile_fingerprint=expected_profile, endpoint=profile.endpoint, kernel_id=profile.kernel_id,
                session_id=profile.session_id, remote_root=profile.remote_root, anchor_job_id=anchor_job_id,
                anchor_code_sha256=anchor["code_sha256"], anchor_payload_sha256=anchor["payload_sha256"],
                authoritative_ledger_root_sha256=sha(str(Path(expected_root).absolute()).encode()))


def stage_assets(provider, manifest_bytes, expected_manifest_sha256, parts_dir, journal_path,
                 expected_profile_fingerprint, *, adapter_ledger, expected_ledger_root,
                 anchor_job_id, reconcile_only=False):
    """One native-owned upload transaction; explicit reconciliation never PUTs."""
    manifest = validate_manifest(manifest_bytes, expected_manifest_sha256)
    identity = _idle_identity(provider, adapter_ledger, expected_ledger_root, anchor_job_id,
                              expected_profile_fingerprint)
    require(manifest["remote_root"] == identity["remote_root"] and
            manifest["limits"]["max_archive_bytes"] <= provider.profile.max_artifact_bytes,
            "PROFILE_ASSET_CONTRACT")
    local = {}
    for part in manifest["parts"]:
        raw = regular_bytes(Path(parts_dir) / part["local_name"], CHUNK)
        require(len(raw) == part["bytes"] and sha(raw) == part["sha256"], "LOCAL_PART_IDENTITY")
        local[part["index"]] = raw
    path = Path(journal_path).absolute()
    parent, name = _parent(str(path) + ".lock")
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
    os.close(parent)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                and info.st_mode & 0o077 == 0, "UPLOAD_LOCK_UNSAFE")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            state = _json(regular_bytes(path, 8388608))
            require(state.get("schema") == "hcsn-colab-asset-upload-journal-v4"
                    and state["manifest_sha256"] == expected_manifest_sha256 and state["identity"] == identity
                    and state["request_id"] == manifest["request_id"] and state["archive"] == manifest["archive"],
                    "UPLOAD_JOURNAL_IDENTITY")
        else:
            require(not reconcile_only, "NO_EXISTING_UPLOAD_TO_RECONCILE")
            state = dict(schema="hcsn-colab-asset-upload-journal-v4", status="PREPARED", identity=identity,
                request_id=manifest["request_id"], manifest_sha256=expected_manifest_sha256,
                archive=manifest["archive"], started_unix=time.time(), observations=[],
                full_physical_energy_joules=None, monetary_cost=None,
                parts=[dict(index=p["index"], remote_path=p["remote_path"], bytes=p["bytes"], sha256=p["sha256"],
                            put_attempts=0, phase="PLANNED") for p in manifest["parts"]])
            _new_file(path, canonical(state) + b"\n")
        def save():
            tmp = path.with_name(path.name + ".tmp")
            _new_file(tmp, canonical(state) + b"\n")
            parent_fd, name = _parent(path)
            try:
                os.replace(tmp.name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        require(len(state["parts"]) == len(manifest["parts"]), "UPLOAD_JOURNAL_ROSTER")
        for part, row in zip(manifest["parts"], state["parts"]):
            require(all(row[k] == part[k] for k in ("index", "remote_path", "bytes", "sha256"))
                    and type(row["put_attempts"]) is int and row["put_attempts"] in (0, 1), "UPLOAD_ROW_IDENTITY")
            require(row.get("phase") != "CONFLICT", "PRIOR_UPLOAD_CONFLICT")
            require(reconcile_only or row["put_attempts"] == 0 or row.get("phase") == "VERIFIED",
                    "UNKNOWN_REQUIRES_READONLY_RECONCILIATION")
        try:
            directory = provider.contents.list_dir(manifest["remote_root"])
        except Exception as error:
            state["observations"].append(dict(kind="parent_read_failed", error_class=safe_error(error), at=time.time()))
            state["status"] = "UNKNOWN"
            save()
            return state
        require(isinstance(directory, dict) and directory.get("type") == "directory", "REMOTE_PARENT_NOT_DIRECTORY")
        state["observations"].append(dict(kind="existing_parent_directory_observed", at=time.time(),
                                          directory_created_by_transport=False, reconcile_only=reconcile_only))
        save()
        for part, row in zip(manifest["parts"], state["parts"]):
            require(all(row[k] == part[k] for k in ("index", "remote_path", "bytes", "sha256"))
                    and type(row["put_attempts"]) is int and row["put_attempts"] in (0, 1), "UPLOAD_ROW_IDENTITY")
            if row.get("phase") == "CONFLICT":
                raise AssetError("PRIOR_UPLOAD_CONFLICT")
            if row["put_attempts"] == 0:
                if reconcile_only:
                    state["status"] = "UNKNOWN"
                    save()
                    return state
                _idle_identity(provider, adapter_ledger, expected_ledger_root, anchor_job_id, expected_profile_fingerprint)
                try:
                    provider.read_bytes(part["remote_path"])
                except FileNotFoundError:
                    pass
                except Exception as error:
                    row.update(last_read_error=safe_error(error), phase="PRECHECK_UNKNOWN")
                    state["status"] = "UNKNOWN"
                    save()
                    return state
                else:
                    row.update(phase="CONFLICT", reason="PREEXISTING_REMOTE_PATH_NEVER_OVERWRITTEN")
                    state["status"] = "UNKNOWN"
                    save()
                    raise AssetError("PREEXISTING_REMOTE_PATH")
                row.update(put_attempts=1, phase="PUT_INTENT", put_intent_unix=time.time())
                save()  # durable intent before the only PUT for this exact path
                try:
                    provider.write_bytes(part["remote_path"], local[part["index"]])
                    row["write_returned"] = True
                except Exception as error:
                    row.update(write_returned=False, write_error=safe_error(error))
                save()
            try:
                observed = provider.read_bytes(part["remote_path"])
                require(len(observed) == part["bytes"] and sha(observed) == part["sha256"], "REMOTE_PART_IDENTITY")
            except Exception as error:
                row.update(phase="UNKNOWN", last_read_error=safe_error(error), last_read_unix=time.time())
                state["status"] = "UNKNOWN"
                save()
                return state
            row.update(phase="VERIFIED", readback_sha256=sha(observed), readback_bytes=len(observed),
                       verified_unix=time.time(), verified_after_uncertain_put=row.get("write_returned") is not True)
            save()
        state.update(status="VERIFIED", finished_unix=time.time(), unknown_put_replayed=False,
                     caller_must_bind_actual_native_job=True, full_physical_energy_joules=None)
        save()
        return state
    finally:
        os.close(fd)


def make_launcher(manifest_bytes, expected_sha, destination_name, entrypoint_logical,
                  transport_source_bytes, argv=(), *, transport_logical=PUBLIC_PATH):
    """Build <=256KiB code. The bound job identity remains external authority."""
    manifest = validate_manifest(manifest_bytes, expected_sha)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", destination_name) is not None,
            "DESTINATION_NAME_INVALID")
    _relative(entrypoint_logical)
    _relative(transport_logical)
    require(entrypoint_logical in manifest["files"] and entrypoint_logical.endswith(".py"), "ENTRYPOINT_ABSENT")
    require(manifest["files"].get(transport_logical) == dict(bytes=len(transport_source_bytes), sha256=sha(transport_source_bytes)),
            "TRANSPORT_SOURCE_NOT_PINNED_IN_ASSETS")
    require(isinstance(argv, (tuple, list)) and all(isinstance(v, str) for v in argv), "ARGV_INVALID")
    source = (
        "import base64,hashlib,json,os,runpy,sys,types,zlib\n"
        "from pathlib import Path\n"
        f"_m=zlib.decompress(base64.b64decode({base64.b64encode(zlib.compress(manifest_bytes,9)).decode()!r},validate=True))\n"
        f"_s=zlib.decompress(base64.b64decode({base64.b64encode(zlib.compress(transport_source_bytes,9)).decode()!r},validate=True))\n"
        f"assert len(_m)=={len(manifest_bytes)} and hashlib.sha256(_m).hexdigest()=={expected_sha!r}\n"
        f"assert len(_s)=={len(transport_source_bytes)} and hashlib.sha256(_s).hexdigest()=={sha(transport_source_bytes)!r}\n"
        "_module=types.ModuleType('_hepta_verified_assets_v4');sys.modules[_module.__name__]=_module\n"
        "exec(compile(_s,'<verified-asset-transport>','exec'),_module.__dict__)\n"
        f"_root=Path.cwd()/{destination_name!r}\n"
        f"_verified=_module.materialize_assets(_m,{expected_sha!r},_root)\n"
        "_module._new_file(Path.cwd()/'asset-materialization.json',_module.canonical(_verified)+b'\\n')\n"
        f"assert hashlib.sha256((_root/{transport_logical!r}).read_bytes()).hexdigest()=={sha(transport_source_bytes)!r}\n"
        "sys.path.insert(0,str(_root))\n"
        f"_entry=_root/{entrypoint_logical!r};sys.argv=[str(_entry),*{list(argv)!r}]\n"
        "runpy.run_path(str(_entry),run_name='__main__')\n")
    require(len(source.encode()) <= 262144, "LAUNCHER_CODE_LIMIT")
    compile(source, "<colab-assets-launcher>", "exec")
    return dict(source_text=source, code_sha256=sha(source.encode()), code_bytes=len(source.encode()),
                manifest_sha256=expected_sha)
