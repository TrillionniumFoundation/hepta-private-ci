"""Supplementary target-free ASR on real inputs and learned output waveforms."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

from ...abc_next.temporal.external import ExternalObserver


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def digits(transcript):
    """Strict declared parse; no target-conditioned transcript repair."""
    tokens = re.findall(r"[a-z]+|[0-9]+", transcript.lower())
    if len(tokens) != 2:
        return None
    result = []
    for token in tokens:
        if token in WORDS:
            result.append(WORDS.index(token))
        elif len(token) == 1 and token.isdigit():
            result.append(int(token))
        else:
            return None
    return result


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    with Path(path).open("x") as stream:
        json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("evaluation", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, process = time.perf_counter_ns(), time.process_time_ns()
    summary = json.loads((args.evaluation / "summary.json").read_text())
    if summary["status"] != "completed":
        raise ValueError("Only closed generation results may enter supplementary ASR")
    records = [json.loads(path.read_text()) for path in sorted(args.evaluation.glob("row-*-text-hard.json"))]
    save(args.output / "registration.json", {"source_sha256": file_sha(__file__),
         "generation_summary_sha256": file_sha(args.evaluation / "summary.json"),
         "phase": summary["phase"], "pairs": len(records), "selection": "all text-input hard-condition rows",
         "input_and_output_same_sources": True, "target_or_prompt_supplied_to_asr": False,
         "scope": "Supplementary independent pretrained ASR; no model selection or full human perceptual claim"})
    observer = ExternalObserver(args.assets)
    save(args.output / "observer.json", observer.load_receipt)
    rows = []
    for record in records:
        observed = {"input": observer.observe(record["input_files"]["audio"]["path"]),
                    "output": observer.observe(record["output"]["files"]["audio"]["path"])}
        expected = record["audit"]["expected_labels"]
        parsed = {name: digits(value["transcript"]) for name, value in observed.items()}
        row = {"index": record["index"], "observed": observed, "parsed": parsed,
               "expected_after_observation": expected,
               "pair_correct": {name: value == expected for name, value in parsed.items()},
               "digits_correct": {name: sum(x == y for x, y in zip(value, expected)) if value is not None else 0 for name, value in parsed.items()}}
        rows.append(row)
        save(args.output / f"row-{record['index']:03d}.json", row)
        print(json.dumps({"pairs": len(rows), "input": observed["input"]["transcript"], "output": observed["output"]["transcript"]}), flush=True)
    save(args.output / "summary.json", {"status": "completed", "pairs": len(rows),
         "pair_accuracy": {name: sum(r["pair_correct"][name] for r in rows) / len(rows) for name in ("input", "output")},
         "digit_accuracy": {name: sum(r["digits_correct"][name] for r in rows) / (2 * len(rows)) for name in ("input", "output")},
         "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - process,
         "not_a_preregistered_primary_gate": True,
         "interpretation": "Judge observer qualification against real input accuracy before treating output disagreement as a generator failure"})


if __name__ == "__main__":
    main()
