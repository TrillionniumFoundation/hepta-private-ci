"""Bounded development-only rendition pilot, never evaluation sources."""

import argparse
import json
from pathlib import Path
import time

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import write_json
from experiments.multimodal_output_portfolio.abc_next.temporal.external import ExternalObserver
from experiments.multimodal_output_portfolio.abc_next.temporal.speech import SpeechBackend
from .tasks import manifest, parse, sentence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--external-assets", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    backend, external = SpeechBackend(args.assets), ExternalObserver(args.external_assets)
    rows = []
    for index, source in enumerate(manifest()["roles"]["development"]):
        for template in range(3):
            for style in ("compact", "explicit", "redundant"):
                text = sentence(source["fact"], style, template)
                path = args.output / f"{index}-{template}-{style}.wav"
                tts = backend.synthesize(text, path)
                online, offline = backend.observe(path), external.observe(path)
                row = {"source_id": source["source_id"], "fact": source["fact"],
                       "template": template, "style": style, "text": text,
                       "tts": tts, "online": online, "offline": offline,
                       "online_correct": parse(online["transcript"]) == tuple(source["fact"]),
                       "offline_correct": parse(offline["transcript"]) == tuple(source["fact"])}
                rows.append(row)
    result = {"role": "development", "rows": rows, "wall_ns": time.perf_counter_ns() - start,
              "cpu_ns": time.process_time_ns() - cpu}
    write_json(args.output / "result.json", result)
    for style in ("compact", "explicit", "redundant"):
        subset = [r for r in rows if r["style"] == style]
        print(json.dumps({"style": style, "n": len(subset),
                          "online_correct": sum(r["online_correct"] for r in subset),
                          "offline_correct": sum(r["offline_correct"] for r in subset),
                          "mean_tts_ms": sum(r["tts"]["wall_ns"] for r in subset) / len(subset) / 1e6}), flush=True)


if __name__ == "__main__":
    main()
