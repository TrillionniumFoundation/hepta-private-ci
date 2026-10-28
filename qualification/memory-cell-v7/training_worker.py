"""One bounded, configured training job; stdout contains only candidate bytes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from training import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, canonical, decode_unique, sha, train


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("training input exceeds bound")
    outcome = train(decode_unique(raw))
    outcome["request_digest"] = sha(raw)
    result = canonical(outcome)
    if len(result) > MAX_OUTPUT_BYTES:
        raise ValueError("training output exceeds bound")
    sys.stdout.buffer.write(result + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, TypeError, KeyError) as error:
        print("memory training rejected: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(2) from error
