"""Prospectively frozen independent-observer checks on separate fact groups."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from experiments.multimodal_output_portfolio.abc_next.temporal.external import ExternalObserver
from experiments.multimodal_output_portfolio.abc_next.temporal.speech import SpeechBackend, read_pcm, write_pcm
from experiments.multimodal_output_portfolio.abc_next.temporal.stream import AppendOnlyOutput
from .state import Frame, PREFIX, chunk_text, initial_frame, metrics
from .tasks import manifest


GATES = {"external_fact_accuracy": .90, "external_exact_success": .75,
         "online_fact_accuracy": .85, "online_exact_success": .65,
         "wrong_fact_exact_acceptance": 0, "silent_or_truncated_semantic_completion": 0}


def hashes():
    root = Path(__file__).parent
    old = root.parents[1] / "abc_next" / "temporal"
    files = {f"new/{name}": root / name for name in ("tasks.py", "state.py", "qualification.py")}
    files.update({f"reused/{name}": old / name for name in ("audit.py", "speech.py", "stream.py", "facts.py", "external.py")})
    return {name: sha256(path) for name, path in files.items()}


def register(args):
    args.freeze.mkdir(parents=True, exist_ok=False)
    write_json(args.freeze / "sources.json", manifest())
    protocol = {"schema": "hepta.abc4.temporal-observer-qualification.v1", "gates": GATES,
                "source_hashes": hashes(), "source_manifest_sha256": sha256(args.freeze / "sources.json"),
                "assets_sha256": sha256(args.assets / "manifest.json"),
                "external_assets_sha256": sha256(args.external_assets / "manifest.json"),
                "sources": 8, "templates": 2, "controls": ["correct", "wrong", "silent", "truncated"],
                "failure_rule": "retain failures; do not open final evaluation or change thresholds/parser/observer",
                "scope": "constructed source groups, fixed templates and one pretrained voice; point qualification only"}
    write_json(args.freeze / "qualification_protocol.json", protocol)
    print(json.dumps({"protocol_sha256": sha256(args.freeze / "qualification_protocol.json")}), flush=True)


def run(args):
    protocol = json.loads((args.freeze / "qualification_protocol.json").read_text())
    if protocol["source_hashes"] != hashes() or protocol["gates"] != GATES:
        raise ValueError("Frozen qualification source or thresholds changed")
    if protocol["source_manifest_sha256"] != sha256(args.freeze / "sources.json"):
        raise ValueError("Qualification source roles changed")
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    backend, external = SpeechBackend(args.assets), ExternalObserver(args.external_assets)
    if backend.load_receipt["manifest_sha256"] != protocol["assets_sha256"] or external.load_receipt["manifest_sha256"] != protocol["external_assets_sha256"]:
        raise ValueError("Frozen models changed")
    rows = []
    for index, source in enumerate(manifest()["roles"]["qualification"]):
        for template in range(2):
            directory = args.output / f"{index}-{template}"
            directory.mkdir()
            paths = {}
            for kind in ("correct", "wrong"):
                fact = list(source["fact"])
                if kind == "wrong":
                    fact[0] = (fact[0] + 1) % 8
                frame = initial_frame(tuple(fact), template)
                prefix = backend.synthesize(PREFIX, directory / f"{kind}-prefix.wav")
                output = AppendOnlyOutput(directory / kind, prefix["sample_rate"])
                output.append(PREFIX, directory / f"{kind}-prefix.wav", "neutral")
                for stage in range(2):
                    values = frame.detached()
                    values["stage"] = stage
                    text = chunk_text(Frame(**values))
                    path = directory / f"{kind}-{stage}.wav"
                    backend.synthesize(text, path)
                    output.append(text, path, f"stage-{stage}")
                output.finish()
                paths[kind] = (directory / kind / "output.wav", (directory / kind / "output.txt").read_text())
            rate, samples = read_pcm(paths["correct"][0])
            write_pcm(directory / "silent.wav", rate, np.zeros_like(samples))
            prefix_rate, prefix_samples = read_pcm(directory / "correct-prefix.wav")
            write_pcm(directory / "truncated.wav", prefix_rate, prefix_samples)
            paths["silent"] = (directory / "silent.wav", paths["correct"][1])
            paths["truncated"] = (directory / "truncated.wav", PREFIX)
            for kind, (path, text) in paths.items():
                online, offline = backend.observe(path), external.observe(path)
                rows.append({"source_id": source["source_id"], "target_fact": source["fact"], "template": template, "kind": kind,
                             "wave_sha256": sha256(path), "online": online, "offline": offline,
                             "online_metrics": metrics(source["fact"], text, online["transcript"], True),
                             "offline_metrics": metrics(source["fact"], text, offline["transcript"], True)})
    correct = [r for r in rows if r["kind"] == "correct"]
    measurements = {"external_fact_accuracy": float(np.mean([r["offline_metrics"]["audio_accuracy"] for r in correct])),
                    "external_exact_success": float(np.mean([r["offline_metrics"]["success"] for r in correct])),
                    "online_fact_accuracy": float(np.mean([r["online_metrics"]["audio_accuracy"] for r in correct])),
                    "online_exact_success": float(np.mean([r["online_metrics"]["success"] for r in correct])),
                    "wrong_fact_exact_acceptance": sum(tuple(r["offline_metrics"]["audio_fact"]) == tuple(r["target_fact"])
                                                       for r in rows if r["kind"] == "wrong"),
                    "silent_or_truncated_semantic_completion": sum(None not in r["offline_metrics"]["audio_fact"]
                                                                  for r in rows if r["kind"] in ("silent", "truncated"))}
    passed = all(measurements[k] >= threshold for k, threshold in GATES.items() if k.endswith("accuracy") or k.endswith("success"))
    passed = passed and measurements["wrong_fact_exact_acceptance"] == 0 and measurements["silent_or_truncated_semantic_completion"] == 0
    result = {"schema": "hepta.abc4.temporal-observer-qualification-result.v1", "passed": bool(passed),
              "protocol_sha256": sha256(args.freeze / "qualification_protocol.json"), "measurements": measurements,
              "gates": GATES, "rows": rows, "wall_ns": time.perf_counter_ns() - wall,
              "cpu_ns": time.process_time_ns() - cpu, "sources": 8, "normal_outputs": 16}
    write_json(args.output / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("register", "run"))
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--external-assets", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    (register if args.mode == "register" else run)(args)


if __name__ == "__main__":
    main()
