"""Register, then run only 16 qualification groups with frozen ASR gates."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from .external import DECODE, ExternalObserver
from .facts import PREFIX, WORDS, canonical, observed_metrics, parse_facts, sentences, source_manifest
from .speech import SpeechBackend, read_pcm, sha256, write_pcm


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_hashes(names):
    root = Path(__file__).parent
    return {name: sha256(root / name) for name in names}


def register(args):
    args.freeze.mkdir(parents=True, exist_ok=False)
    manifest = source_manifest()
    write_json(args.freeze / "sources.json", manifest)
    protocol = {"schema": "hepta.abc3.text-speech-qualification.v1",
                "source_manifest_sha256": sha256(args.freeze / "sources.json"),
                "tts_online_assets_sha256": sha256(args.assets / "manifest.json"),
                "external_assets_sha256": sha256(args.external_assets / "manifest.json"),
                "source_hashes": source_hashes(("qualification.py", "speech.py", "external.py", "facts.py")),
                "external_decode": DECODE, "length_scales": {"normal": 1.0, "slow": 1.2},
                "groups": 16, "role": "qualification", "allow_template_or_threshold_adaptation": False,
                "gates": {"minimum_external_fact_accuracy_each_speed": .90,
                          "minimum_external_exact_each_speed": .75,
                          "minimum_online_fact_accuracy_each_speed": .85,
                          "minimum_online_exact_each_speed": .65,
                          "maximum_wrong_fact_exact_acceptance": 0,
                          "maximum_silent_or_truncated_semantic_completion": 0},
                "controls": ["new normal speech", "new slow speech", "new intentionally wrong number speech",
                             "actual silent PCM", "actual truncated speech containing no complete fact"],
                "observer_boundary": "Whisper only qualification/offline final; never value fit, feature, fixed-policy or hyperparameter selection",
                "qualification_failure": "preserve result; do not evaluate or silently change the registered observer, parser or thresholds"}
    write_json(args.freeze / "qualification_protocol.json", protocol)
    print(json.dumps({"freeze": str(args.freeze), "protocol_sha256": sha256(args.freeze / "qualification_protocol.json"),
                      "sources_sha256": protocol["source_manifest_sha256"]}))


def run(args):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    protocol_path = args.freeze / "qualification_protocol.json"
    protocol = json.loads(protocol_path.read_text())
    if source_hashes(protocol["source_hashes"]) != protocol["source_hashes"]:
        raise ValueError("Qualification code changed after registration")
    for path, expected in ((args.freeze / "sources.json", protocol["source_manifest_sha256"]),
                           (args.assets / "manifest.json", protocol["tts_online_assets_sha256"]),
                           (args.external_assets / "manifest.json", protocol["external_assets_sha256"])):
        if sha256(path) != expected:
            raise ValueError("Qualification input identity changed")
    args.output.mkdir(parents=True, exist_ok=False)
    backend, external = SpeechBackend(args.assets), ExternalObserver(args.external_assets)
    rows = []
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"]["qualification"]
    for index, source in enumerate(sources):
        fact = tuple(source["fact"])
        text = " ".join((PREFIX, *sentences(fact)))
        for control in ("normal", "slow", "wrong", "silent", "truncated"):
            path = args.output / f"{index:02d}-{control}.wav"
            tts = None
            if control in ("normal", "slow", "wrong"):
                spoken = fact if control != "wrong" else ((fact[0] + 1) % len(WORDS[0]), *fact[1:])
                tts = backend.synthesize(" ".join((PREFIX, *sentences(spoken))), path,
                                         protocol["length_scales"].get(control, 1.0))
            else:
                rate, original = read_pcm(args.output / f"{index:02d}-normal.wav")
                samples = np.zeros(rate * 2, dtype=np.int16) if control == "silent" else original[:rate // 3]
                write_pcm(path, rate, samples)
            online, independent = backend.observe(path), external.observe(path)
            physical = control not in ("silent", "truncated")
            row = {"source_id": source["source_id"], "control": control, "tts": tts,
                   "online": online, "external": independent,
                   "online_metrics": observed_metrics(fact, text, online["transcript"], physical),
                   "external_metrics": observed_metrics(fact, text, independent["transcript"], physical),
                   "external_all_facts_decoded": None not in parse_facts(independent["transcript"])}
            rows.append(row)
        print(json.dumps({"qualification_group": index + 1, "of": len(sources)}), flush=True)
    summary, checks = {}, {}
    for speed in ("normal", "slow"):
        selected = [row for row in rows if row["control"] == speed]
        for observer in ("online", "external"):
            metrics = [row[observer + "_metrics"] for row in selected]
            fact_accuracy = float(np.mean([row["audio_fact_accuracy"] for row in metrics]))
            exact = float(np.mean([row["joint_task_success"] for row in metrics]))
            summary[f"{observer}_{speed}"] = {"fact_accuracy": fact_accuracy, "exact": exact}
            checks[f"{observer}_{speed}_facts"] = fact_accuracy >= protocol["gates"][f"minimum_{observer}_fact_accuracy_each_speed"]
            checks[f"{observer}_{speed}_exact"] = exact >= protocol["gates"][f"minimum_{observer}_exact_each_speed"]
    checks["wrong_exact_rejected"] = all(not row["external_metrics"]["joint_task_success"]
                                         for row in rows if row["control"] == "wrong")
    checks["silent_truncated_incomplete"] = all(not row["external_all_facts_decoded"] and
                                                not row["external_metrics"]["required_semantic_completion"]
                                                for row in rows if row["control"] in ("silent", "truncated"))
    report = {"protocol_sha256": sha256(protocol_path), "passed": all(checks.values()),
              "checks": checks, "summary": summary, "rows": rows,
              "loads": {"generator_and_online": backend.load_receipt, "external": external.load_receipt},
              "wall_ns_before_report": time.perf_counter_ns() - started,
              "cpu_ns_before_report": time.process_time_ns() - cpu}
    write_json(args.output / "qualification.json", report)
    print(json.dumps({"passed": report["passed"], "checks": checks, "summary": summary,
                      "report_sha256": sha256(args.output / "qualification.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("register", "run"))
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--external-assets", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    register(args) if args.operation == "register" else run(args)


if __name__ == "__main__":
    main()
