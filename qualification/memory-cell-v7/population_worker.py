"""Bounded clean population training; bytes carry no publication authority."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from population_training import train_populations
from training import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, canonical, decode_unique, sha


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("population training input exceeds bound")
    frame = decode_unique(raw)
    if not isinstance(frame, dict) or set(frame) != {"schema", "export", "configuration"} or frame["schema"] != "hepta.memory.population-training-request.v2":
        raise ValueError("invalid population training request")
    result = train_populations(frame["export"], frame["configuration"])
    result["request_digest"] = sha(raw)
    encoded = canonical(result)
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ValueError("population training output exceeds bound")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, TypeError, KeyError) as error:
        print("population training rejected: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(2) from error
