"""Execute the frozen continuation using the existing pinned encoder config.

Only the supplied new evidence tree is written. No selected service or owner
bundle is changed. All subprocess costs, including failures, are retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time


def main(args):
    package = Path(__file__).resolve().parent
    config = json.loads(args.config.read_bytes())
    args.output.mkdir(parents=True, exist_ok=False)
    receipts = []
    started = time.perf_counter()

    def stage(name, command):
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        began, result, error = time.perf_counter(), None, None
        try:
            with (args.output / (name + ".stdout")).open("xb") as stdout, (args.output / (name + ".stderr")).open("xb") as stderr:
                result = subprocess.run(command, cwd=package, stdin=subprocess.DEVNULL, stdout=stdout,
                                        stderr=stderr, timeout=300, check=False)
        except BaseException as exception:
            error = repr(exception)
            raise
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            receipts.append({"stage":name, "command":command, "exit_code":None if result is None else result.returncode,
                "error":error, "wall_seconds":time.perf_counter()-began,
                "child_cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                "child_peak_rss_kib_cumulative":after.ru_maxrss})
            (args.output / "RUN.json").write_text(json.dumps({"schema":"hepta.semantic-bilingual-process-run.v1",
                "stages":receipts, "wall_seconds":time.perf_counter()-started, "automatic_retries":0,
                "runner_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "encoder_config_sha256":hashlib.sha256(args.config.read_bytes()).hexdigest(),
                "cost_scope":"actual fresh freeze/fit/compare subprocesses; historical baseline and encoder construction remain separate"}, indent=2))
        if result.returncode:
            raise RuntimeError(name + " failed; preserve all partial evidence and do not retry held")

    stage("freeze", [config["python"], "-B", str(package / "bilingual_semantic_protocol.py"),
                     "--baseline-root", str(args.baseline_root.resolve(strict=True)), "--output", str(args.output / "protocol")])
    protocol = args.output / "protocol/PROTOCOL.json"
    identity = hashlib.sha256(protocol.read_bytes()).hexdigest()
    shared = ["--protocol", str(protocol), "--protocol-sha256", identity,
              "--encoder-source", config["encoder_source"], "--encoder-source-sha256", config["source_digest"],
              "--encoder", config["encoder_directory"]]
    trainer = [config["python"], "-B", str(package / "train_bilingual_semantic.py")]
    stage("fit", [*trainer, "fit", *shared, "--output", str(args.output / "candidate")])
    stage("compare", [*trainer, "compare", *shared, "--candidate", str(args.output / "candidate"), "--output", str(args.output / "comparison")])
    publication = json.loads((args.output / "comparison/PUBLICATION_CANDIDATE.json").read_bytes())
    print(json.dumps({"protocol_sha256":identity, "language_gate_passed":publication["language_gate_passed"],
        "model":publication["model"], "model_sha256":publication["model_sha256"], "native_reference":publication["native_reference"],
        "owner_test_environment":{"HEPTA_NATIVE_INVENTORY_ENCODER_CONFIG":str(args.config.resolve(strict=True)),
            "HEPTA_NATIVE_INVENTORY_SEMANTIC_MODEL":publication["model"],
            "HEPTA_NATIVE_INVENTORY_SEMANTIC_MODEL_SHA256":publication["model_sha256"],
            "HEPTA_NATIVE_INVENTORY_SEMANTIC_EVIDENCE_DIR":str(args.output / "actual-owner")},
        "native_and_actual_owner_passed":False, "production_selected":False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    main(args)
