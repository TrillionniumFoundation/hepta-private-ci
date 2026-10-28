"""One bounded V3 training request per isolated host-launched process."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve()
sys.path.insert(0, str(ROOT.parents[2] / "memory-cell-v7"))
sys.path.insert(0, str(ROOT.parents[1]))

from learning.population_training import process_peak_rss_bytes, train_populations
from population_training import train_populations as train_fixed
from training import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, canonical, decode_unique, sha


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("bounded training request required")
    frame = decode_unique(raw)
    if not isinstance(frame, dict) or set(frame) != {"schema", "export", "configuration", "routing_mode", "routing_trace"}:
        raise ValueError("invalid prospective population training request")
    if frame["schema"] != "hepta.memory.prospective-population-fit.v1":
        raise ValueError("unknown training schema")
    if frame["routing_mode"] == "fixed" and frame["routing_trace"] is None:
        result = train_fixed(frame["export"], frame["configuration"])
    elif frame["routing_mode"] == "learned" and isinstance(frame["routing_trace"], dict):
        result = train_populations(frame["export"], frame["configuration"], frame["routing_trace"])
    else:
        raise ValueError("routing mode and trace disagree")
    result["receipt"]["process_peak_rss_bytes"] = process_peak_rss_bytes()
    result["request_digest"] = sha(raw)
    output = canonical(result)
    if len(output) > MAX_OUTPUT_BYTES:
        raise ValueError("bounded training response required")
    sys.stdout.buffer.write(output + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
