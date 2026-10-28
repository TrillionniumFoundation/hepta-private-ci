"""One bounded V9 paired intervention; no future task or evaluation input."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve()
sys.path.insert(0, str(ROOT.parents[2] / "memory-cell-v7"))
sys.path.insert(0, str(ROOT.parents[1]))

from training import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, canonical, decode_unique, sha
from learning.paired import CONFIG as CATALOG_CONFIG
from learning.paired import paired_catalog
from learning.byte_model import CONFIG as BYTE_CONFIG
from learning.byte_model import paired_bytes


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("bounded nonempty paired request required")
    frame = decode_unique(raw)
    if not isinstance(frame, dict) or set(frame) != {"schema", "representation", "configuration", "export", "parents"}:
        raise ValueError("future tasks or unrecognized training fields are forbidden")
    if frame["schema"] != "hepta.memory.v9.paired-fit.v1":
        raise ValueError("unknown paired training schema")
    if frame["representation"] == "catalog" and frame["configuration"] == CATALOG_CONFIG:
        result = paired_catalog(frame["export"], frame["parents"])
    elif frame["representation"] == "byte" and frame["configuration"] == BYTE_CONFIG:
        result = paired_bytes(frame["export"], frame["parents"])
    else:
        raise ValueError("unrecognized or changed frozen configuration")
    result["request_digest"] = sha(raw)
    output = canonical(result)
    if len(output) > MAX_OUTPUT_BYTES:
        raise ValueError("paired response exceeds original 16 MiB worker bound")
    sys.stdout.buffer.write(output + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
