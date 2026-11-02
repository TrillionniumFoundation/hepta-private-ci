"""Bounded authenticated envelopes; keys and host custody are explicit assumptions."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat

CAP = 2**20


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse(data):
    if len(data) > CAP:
        raise ValueError("object capacity")
    return json.loads(data, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def keyfile(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
            raise ValueError("key custody admission")
        data = os.read(fd, 33)
        if len(data) != 32:
            raise ValueError("key size")
        return data
    finally:
        os.close(fd)


def mac(key, domain, body):
    return hmac.new(key, domain.encode() + b"\0" + canonical(body), hashlib.sha256).hexdigest()


def seal(key, domain, body):
    return canonical({"body": body, "tag": mac(key, domain, body)})


def open_seal(key, domain, data):
    obj = parse(data)
    if not isinstance(obj, dict) or set(obj) != {"body", "tag"} or not isinstance(obj["tag"], str):
        raise ValueError("envelope shape")
    if not hmac.compare_digest(obj["tag"], mac(key, domain, obj["body"])):
        raise ValueError("authentication failed")
    return obj["body"]


def exact_fields(obj, fields):
    if not isinstance(obj, dict) or set(obj) != set(fields):
        raise ValueError("object fields")


def hex64(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("digest encoding")
    return value


def count(value):
    if type(value) is not int or value < 0 or value > 2**53:
        raise ValueError("sequence admission")
    return value


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("regular file required")
        data = os.read(fd, CAP + 1)
        if len(data) > CAP:
            raise ValueError("file capacity")
        return data
    finally:
        os.close(fd)


def private_directory(path, create=False):
    path = Path(path)
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
        raise ValueError("private directory custody admission")
    return path


def durable_new(path, data, mode=0o600):
    path = Path(path)
    if len(data) > CAP:
        raise ValueError("file capacity")
    # Caller owns a private, admitted directory. O_EXCL/O_NOFOLLOW refuse substitution.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    if read_regular(path) != data:
        raise ValueError("durable readback mismatch")


def encode_states(owner, provider):
    return {"owner": base64.b64encode(owner).decode(),
            "provider": base64.b64encode(provider).decode()}


def decode_states(states):
    exact_fields(states, ("owner", "provider"))
    if any(not isinstance(x, str) for x in states.values()):
        raise ValueError("state encoding")
    return {name: base64.b64decode(value, validate=True) for name, value in states.items()}
