"""Root-only metadata bootstrap. Copies retained rows; never solves or forwards."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

RETAINED_SHA = "81dc97a289e3f00089998deea5094fe46591b7736d946e98b77e4bed7378b263"
PROFILE_IO_SHA = "3c6d4d0d6ad478460e3b422bfb22220406080c48a5ef1d33e2cb3479e43e738f"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, cap):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= cap:
            raise ValueError("bounded regular bootstrap input required")
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if stamp(before) != stamp(after) or len(raw) != before.st_size:
            raise ValueError("bootstrap input changed during capture")
        return raw


def write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
    if path.read_bytes() != raw:
        raise ValueError("bootstrap readback differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", required=True)
    parser.add_argument("--profile-io", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = read(args.retained, 262144)
    if sha(raw) != RETAINED_SHA:
        raise ValueError("wrong retained actual two-row record")
    retained = json.loads(raw)
    environment = json.loads(read(args.environment, 4096))
    if set(environment) != {"hostnames", "python_versions", "transport"}:
        raise ValueError("environment may contain metadata only")
    rows = retained["local_retained_rows"]
    if len(rows) != 2:
        raise ValueError("exactly the two retained rows required")
    old = retained["common"]
    root = Path(args.output)
    root.mkdir(mode=0o700)
    code = root / "code"
    code.mkdir(mode=0o700)
    source_pins = {}
    for name, source in (("profile_io.py", Path(args.profile_io)),
                         ("exact_equations.py", Path(__file__).with_name("exact_equations.py")),
                         ("peer.py", Path(__file__).with_name("peer.py"))):
        data = read(source, 65536)
        if name == "profile_io.py" and sha(data) != PROFILE_IO_SHA:
            raise ValueError("invalid bounded protocol source")
        write(code / name, data)
        source_pins[name] = sha(data)
    row_pins = {}
    for node, row in zip(("ai395", "pocket4"), rows):
        folder = root / node
        folder.mkdir(mode=0o700)
        data = canonical(row)
        write(folder / "row.json", data)
        row_pins[node] = sha(data)
    common = {"schema": "hepta.fixed-peer-common.v1", "active": False, "root_admission_sha256": None,
              "round": "pft-v5-rational-usb4-20261126-8a32-01", "roster": ["ai395", "pocket4"],
              "objective": "sum half weighted residual squares; binary64 ridge once globally",
              "ridge_binary64": old["ridge"], "linearization": old["linearization"],
              "candidate_sha256": old["candidate_sha256"], "profile_sha256": old["profile_sha256"],
              "source_binding_sha256": old["source_binding_sha256"], "source_sha256": source_pins,
              "source_linearization_sha256": rows[0]["source_linearization_sha256"],
              "accepted_central_result_sha256": rows[0]["accepted_result_sha256"],
              "original_failed_result_sha256": rows[0]["batch"]["original_failed_result_sha256"],
              "retained_peer_record_sha256": RETAINED_SHA, "row_sha256": row_pins, **environment}
    write(root / "common.inactive.json", canonical(common))
    write(root / "bootstrap.json", canonical({"whole_record_stays_with_root": True,
          "row_sha256": row_pins, "source_sha256": source_pins, "model_forwards": 0,
          "rational_solves": 0, "active": False}))


if __name__ == "__main__":
    main()
