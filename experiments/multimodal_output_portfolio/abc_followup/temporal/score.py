"""Offline target-free Whisper observation of the completed serial corpus."""

import argparse
import json
from pathlib import Path
import resource
import time

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from experiments.multimodal_output_portfolio.abc_next.temporal.external import ExternalObserver
from experiments.multimodal_output_portfolio.abc_next.temporal.stream import verify_output
from .state import metrics
from .tasks import manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--external-assets", type=Path, required=True)
    args = parser.parse_args()
    complete = json.loads((args.run / "complete.json").read_text())
    start = json.loads((args.run / "start.json").read_text())
    if complete["role"] != "evaluation" or not complete["complete"] or complete["requests"] != 768:
        raise ValueError("All 768 serial requests must close before any offline scoring")
    if complete["index_sha256"] != sha256(args.run / "index.jsonl"):
        raise ValueError("Completed corpus identity changed")
    if start["external_assets_manifest_sha256"] != sha256(args.external_assets / "manifest.json"):
        raise ValueError("Frozen offline observer assets changed")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "observations").mkdir()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    observer = ExternalObserver(args.external_assets)
    truths = {row["source_id"]: row["fact"] for row in manifest()["roles"]["evaluation"]}
    cache, count, cache_hits = {}, 0, 0
    with (args.output / "scores.jsonl").open("x") as stream:
        for line in (args.run / "index.jsonl").read_text().splitlines():
            entry = json.loads(line)
            if sha256(entry["case"]) != entry["sha256"]:
                raise ValueError("Generation receipt changed")
            row = json.loads(Path(entry["case"]).read_text())
            directory = Path(entry["case"]).parent
            verified = verify_output(directory / "output")
            if verified != row["verification"]:
                raise ValueError("Output differs from its serial-generation identity")
            for acquisition in row["acquisitions"]:
                if sha256(acquisition["tts"]["path"]) != acquisition["observation"]["input_sha256"]:
                    raise ValueError("Actual acoustic cue no longer matches observed input")
            identity = verified["wave_sha256"]
            reused = identity in cache
            if not reused:
                observation = observer.observe(directory / "output" / "output.wav")
                if observation["input_sha256"] != identity:
                    raise ValueError("Offline observer read different output")
                cache[identity] = observation
                write_json(args.output / "observations" / f"{identity}.json", observation)
            else:
                cache_hits += 1
            # Target is only used after the target-free exact-WAV observation.
            outcome = metrics(truths[row["source_id"]], row["actual_text"], cache[identity]["transcript"], True)
            result = {**entry, "wave_sha256": identity, "metrics": outcome,
                      "observation_sha256": sha256(args.output / "observations" / f"{identity}.json"),
                      "exact_wave_observation_reused": reused}
            stream.write(json.dumps(result) + "\n")
            stream.flush()
            count += 1
            if count % 96 == 0:
                print(json.dumps({"scored": count, "unique_waves": len(cache)}), flush=True)
    result = {"complete": True, "scored_requests": count, "unique_observed_waves": len(cache),
              "exact_wave_cache_hits": cache_hits, "failures": 0,
              "generation_complete_sha256": sha256(args.run / "complete.json"),
              "scores_sha256": sha256(args.output / "scores.jsonl"),
              "observer": observer.load_receipt,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "self_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "scope": "all final selected-policy outputs; target-free transcription reused only on exact complete-WAV identity; metrics recomputed for each source target"}
    write_json(args.output / "complete.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
