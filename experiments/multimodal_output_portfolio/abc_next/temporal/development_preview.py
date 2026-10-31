"""Unscored development-only synthesis probe before any evaluation is frozen."""

import argparse
import json
from pathlib import Path
import time

from .speech import SpeechBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    backend = SpeechBackend(args.assets)
    rows = []
    for index, text in enumerate(("There are three red boxes.", "There are seven blue books.",
                                "The number is eight. The color is green.", "I will describe the package.")):
        path = args.output / f"probe-{index}.wav"
        receipt = backend.synthesize(text, path)
        observation = backend.observe(path)
        rows.append({"development_text": text, "speech": receipt, "independent_observation": observation})
    result = {"status": "completed", "scope": "development only; no qualification/evaluation claim",
              "load": backend.load_receipt, "rows": rows,
              "wall_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu}
    (args.output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "completed", "wall_seconds": result["wall_ns"] / 1e9,
                      "pairs": [{"text": row["development_text"], "asr": row["independent_observation"]["transcript"],
                                 "tts_ms": row["speech"]["wall_ns"] / 1e6,
                                 "asr_ms": row["independent_observation"]["wall_ns"] / 1e6} for row in rows]}))


if __name__ == "__main__":
    main()
