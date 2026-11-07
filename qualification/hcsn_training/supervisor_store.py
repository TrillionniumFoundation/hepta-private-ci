"""Private Linux job receipts; uncertainty is never evidence of absence."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

MAX_REQUEST = 8 * 1024 * 1024
MAX_RECEIPT = 1024 * 1024
MAX_CANCELLATIONS = 4096
REPO = Path(__file__).resolve().parents[2]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite JSON number")
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite)


def read_bytes(path, limit=MAX_RECEIPT):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("file identity or byte bound rejected")
        value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError("file byte bound exceeded")
        return value


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(path, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def initialize(root):
    if sys.platform != "linux" or not root.is_absolute() or root.parent.resolve() != root.parent:
        raise ValueError("Linux supervisor requires a canonical absolute private root")
    root.mkdir(mode=0o700)
    for name in ("jobs", "cancellations"):
        (root/name).mkdir(mode=0o700)
        sync_directory(root/name)
    write_new(root/"store.json", dict(schema_version=1, host_id=sha(Path("/etc/machine-id").read_bytes()),
                                    layout="hepta.hcsn.linux-supervisor.v1"))
    sync_directory(root)
    sync_directory(root.parent)


def open_store(root):
    if (sys.platform != "linux" or not root.is_absolute() or root.resolve() != root
            or root.stat().st_mode & 0o077 or root.stat().st_uid != os.geteuid()):
        raise ValueError("Linux supervisor requires its existing private store")
    store = decode(read_bytes(root/"store.json", 4096))
    if (set(store) != {"schema_version", "host_id", "layout"} or store["schema_version"] != 1
            or store["layout"] != "hepta.hcsn.linux-supervisor.v1"
            or store["host_id"] != sha(Path("/etc/machine-id").read_bytes())):
        raise ValueError("supervisor store/host identity changed")
    for name in ("jobs", "cancellations"):
        if ((root/name).resolve() != root/name or not (root/name).is_dir()
                or (root/name).stat().st_mode & 0o077 or (root/name).stat().st_uid != os.geteuid()):
            raise ValueError("supervisor namespace is missing or redirected")
    return store


@contextmanager
def dispatch_lock(root):
    """Serialize first key binding with cancellation, never an external job run."""
    descriptor = os.open(root/"dispatch.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError("invalid dispatch lock")
        deadline = time.monotonic()+2
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("dispatch serialization deadline")
                time.sleep(.01)
        yield
    finally:
        os.close(descriptor)


def identity(key, payload_sha256):
    if not re.fullmatch(r"provider-effect:v1:[0-9a-f]{64}", key) or not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
        raise ValueError("invalid native job identity")
    value = (key+"\0"+payload_sha256).encode()
    return dict(key=key, payload_sha256=payload_sha256,
                job_id=sha(b"hepta.hcsn.job.v1\0"+value), output_id=sha(b"hepta.hcsn.output.v1\0"+value))


def validate_command(command):
    if (set(command) != {"schema_version", "action", "dispatch", "target", "payload"}
            or type(command["schema_version"]) is not int or command["schema_version"] != 1):
        raise ValueError("unknown supervisor command")
    for key in ("dispatch", "target"):
        value = command[key]
        if value != identity(value["key"], value["payload_sha256"]):
            raise ValueError("native identity mismatch")
    action, payload = command["action"], command["payload"]
    if action == "start":
        if (command["dispatch"] != command["target"] or not isinstance(payload, str)
                or len(payload.encode()) > MAX_REQUEST or sha(payload.encode()) != command["dispatch"]["payload_sha256"]
                or not isinstance(decode(payload), dict)):
            raise ValueError("start payload identity mismatch")
    elif action in ("status", "cancel"):
        if payload is not None or (action == "cancel" and command["dispatch"]["key"] == command["target"]["key"]):
            raise ValueError("invalid lookup/cancel command")
    else:
        raise ValueError("unsupported supervisor action")


def job_path(root, target):
    path = root/"jobs"/sha(target["key"].encode())
    if path.resolve() != path:
        raise ValueError("job namespace redirected")
    return path


def retained_cancellation(root, target):
    """Recover pre-start intents without a crash-sensitive secondary index."""
    matching = None
    for index, path in enumerate((root/"cancellations").iterdir()):
        if index >= MAX_CANCELLATIONS:
            raise ValueError("cancellation reconciliation scan budget exceeded")
        record = decode(read_bytes(path, 4096))
        if set(record) != {"dispatch", "target"}:
            raise ValueError("invalid retained cancellation")
        validate_command(dict(schema_version=1, action="cancel", payload=None, **record))
        if path.name != sha(record["dispatch"]["key"].encode()):
            raise ValueError("retained cancellation key differs")
        if record["target"]["key"] == target["key"]:
            if record["target"] != target:
                raise ValueError("retained cancellation binds a conflicting payload")
            matching = record
    return matching


def sources():
    base = REPO/"qualification"
    paths = []
    for iterator in ((base/"hcsn").rglob("*.py"), (base/"hcsn_training").glob("*.py")):
        for path in iterator:
            if path.parent == base/"hcsn_training" and path.name.startswith("test"):
                continue
            if len(paths) >= 512:
                raise ValueError("execution source count budget exceeded")
            paths.append(path)
    result, size = {}, 0
    for path in sorted(paths):
        raw = read_bytes(path)
        size += len(raw)
        if size > 16*1024*1024:
            raise ValueError("execution source byte budget exceeded")
        result[str(path.relative_to(base))] = sha(raw)
    return result


def process_identity(pid, host_id):
    if type(pid) is not int or pid <= 0:
        raise ValueError("positive process ID required")
    # /proc comm may contain spaces and ')' characters; split after its last ')'.
    raw = Path(f"/proc/{pid}/stat").read_text()
    tail = raw[raw.rfind(")")+2:].split()
    if tail[0] in ("Z", "X"):
        raise ProcessLookupError("process is terminal")
    birth = Path("/proc/sys/kernel/random/boot_id").read_bytes()+b"\0"+tail[19].encode()
    return dict(host_id=host_id, process_id=pid, incarnation=sha(birth))


def alive(process, host_id):
    try:
        return process_identity(process["process_id"], host_id) == process
    except (OSError, ValueError, KeyError, IndexError):
        return False


def validate_outputs(job, reservation):
    output = job/reservation["identity"]["output_id"]
    if output.resolve() != output or not output.is_dir():
        raise ValueError("worker output directory redirected")
    request = decode(read_bytes(job/"request.json", MAX_REQUEST))
    receipt_raw = read_bytes(output/"receipt.json")
    receipt = decode(receipt_raw)
    handoff = read_bytes(output/"handoff.bin", 439)
    candidate = read_bytes(output/"candidate.pt", 32*1024*1024)
    magic = b"hepta.hcsn.task-bp-handoff.v1\0\0"
    if len(handoff) != 439 or not handoff.startswith(magic):
        raise ValueError("native task-BP handoff missing")
    hashes = [handoff[len(magic)+32*i:len(magic)+32*(i+1)].hex() for i in range(11)]
    expected = {0: sha(request["operation_id"].encode()), 1: sha(encoded(request)),
                2: sha(encoded(reservation["sources"])), 3: sha(encoded(receipt["runtime_tuple"])),
                4: receipt["graph_digest"], 5: request["binding"]["profile_digest"],
                6: request["base_checkpoint"]["sha256"],
                7: sha(encoded({key: request[key] for key in ("inputs", "targets", "target_time_micros")})),
                8: sha(candidate), 9: sha(encoded(receipt["gradients"])), 10: sha(receipt_raw)}
    counts = [int.from_bytes(handoff[len(magic)+11*32+8*i:len(magic)+11*32+8*(i+1)], "big") for i in range(7)]
    receipt_hashes = {"request_digest": 1, "execution_source_digest": 2, "runtime_tuple_digest": 3,
                      "graph_digest": 4, "base_checkpoint_sha256": 6, "dataset_digest": 7,
                      "checkpoint_sha256": 8, "gradient_digest": 9}
    count_names = ("logical_cells", "trainable_parameters", "completed_optimizer_steps",
                   "gradient_cells", "gradient_parameters")
    if (any(hashes[index] != value or value == "0"*64 for index, value in expected.items())
            or any(receipt[name] != hashes[index] for name, index in receipt_hashes.items())
            or receipt["execution_sources"] != reservation["sources"]
            or receipt["binding"] != request["binding"] or receipt["mechanism"] != "task_mse_bp_v1"
            or receipt["runtime_tuple"]["device"] != "cpu" or receipt["checkpoint_bytes"] != len(candidate)
            or receipt["candidate_only"] is not True or receipt["evaluation_passed"] is not False
            or receipt["optimizer"] != dict(kind="sgd", momentum=0, learning_rate=request["learning_rate"],
                                             steps=request["optimizer_steps"])
            or counts[0] != request["binding"]["generation"] or counts[1] != request["optimizer_steps"]
            or any(type(receipt[name]) is not int or receipt[name] != count
                   for name, count in zip(count_names, counts[2:]))
            or len(receipt["gradients"]) != counts[1]
            or counts[4] != counts[1] or counts[5] != counts[2] or counts[6] != counts[3]
            or not 2 <= counts[2] <= 16 or counts[3] == 0):
        raise ValueError("worker output does not match retained dispatch")
    return dict(receipt_sha256=sha(receipt_raw), candidate_sha256=sha(candidate), handoff_sha256=sha(handoff))


def observe(root, store, command):
    result = dict(schema_version=1, dispatch=command["dispatch"], target=command["target"],
                  state="unknown", process=None, evidence=None)
    try:
        job = job_path(root, command["target"])
        reservation = decode(read_bytes(job/"reservation.json", 2*MAX_RECEIPT))
        if reservation["identity"] != command["target"]:
            return result
        if sha(read_bytes(job/"request.json", MAX_REQUEST)) != command["target"]["payload_sha256"]:
            return result
        if command["dispatch"] != command["target"]:
            cancel = decode(read_bytes(root/"cancellations"/sha(command["dispatch"]["key"].encode()), 4096))
            if cancel != {"dispatch": command["dispatch"], "target": command["target"]}:
                return result
        process = decode(read_bytes(job/"worker.json", 4096)) if (job/"worker.json").exists() else None
        if process is not None:
            result["process"] = process
        if (job/"terminal.json").exists():
            raw = read_bytes(job/"terminal.json")
            terminal = decode(raw)
            if terminal["identity"] != command["target"] or terminal["process"] != process:
                return dict(result, process=None)
            state = terminal["state"]
            if state == "succeeded":
                evidence = validate_outputs(job, reservation)
                if evidence != terminal["evidence"] or process is None:
                    return result
            elif state in ("failed", "cancelled"):
                if terminal.get("termination_confirmed") is not True:
                    return result
                evidence = dict(receipt_sha256=sha(raw), candidate_sha256=None, handoff_sha256=None)
            else:
                return result
            return dict(result, state=state, evidence=evidence)
        runner = decode(read_bytes(job/"runner.json", 4096))
        if process is not None and alive(process, store["host_id"]) and alive(runner, store["host_id"]):
            return dict(result, state="running")
        if process is None and alive(runner, store["host_id"]):
            return dict(result, state="reserved")
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        pass
    return result
