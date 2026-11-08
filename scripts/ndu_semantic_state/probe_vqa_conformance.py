"""Real-reference scorer conformance; generated probes are never model answers."""

import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time

from .materials import _strict_json, check_file
from .official_vqa_accuracy import (
    LockedTextAccuracy,
    _Dataset,
    _pinned_json,
    score_terminal_pool,
)
from .review_packet import _json_bytes, _write
from .source_pool import admit_candidate_pool


def run(pool_root, upstream_path, output, *, manifest_sha256, history_sha256):
    started = time.process_time(), time.perf_counter()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hepta.official-vqa-conformance-plan.v1",
        "selection": "each original human answer for every admitted case, source order",
        "purpose": "software_conformance_only",
        "model_generated_predictions": False,
        "manifest_sha256": manifest_sha256,
        "history_sha256": history_sha256,
        "caption_adapter": "empty caption metrics; asserts accuracy already completed",
        "started_unix": time.time(),
    }
    _write(root, "PLAN.json", _json_bytes(plan))
    receipt = {"status": "failed", "plan": plan, "probes_completed": 0}
    try:
        manifest = _pinned_json(
            pool_root, "CANDIDATES.json", manifest_sha256, 8 * 1024**2
        )
        if any(
            c["project_split"] not in {"train", "development"}
            for c in manifest["cases"]
        ):
            raise ValueError(
                "Exposed reference probes cannot use confirmation or retention"
            )
        admission = admit_candidate_pool(
            pool_root,
            "CANDIDATES.json",
            "HISTORY.json",
            expected_history_sha256=history_sha256,
        )
        if admission["manifest_sha256"] != manifest_sha256:
            raise ValueError("Manifest changed during conformance admission")
        component = LockedTextAccuracy(upstream_path)
        source_bytes = Path(upstream_path).read_bytes()
        if (
            hashlib.sha256(source_bytes).hexdigest()
            != component.lock["upstream_sha256"]
        ):
            raise ValueError("Upstream source changed before full-class conformance")
        upstream = ast.parse(source_bytes)
        node = next(
            n
            for n in upstream.body
            if isinstance(n, ast.ClassDef) and n.name == "VQAEval"
        )
        namespace = {"re": re, "sys": sys}
        original_class = ast.Module(body=[node], type_ignores=[])
        exec(compile(original_class, "full-upstream-vqa-class", "exec"), namespace)
        checks, terminal = [], []
        for case in manifest["cases"]:
            key = case["id"]
            reference = _strict_json(
                check_file(pool_root, case["reference"], limit=2 * 1024**2)
            )
            terminal.append(
                {
                    "id": key,
                    "answer": reference["answers"][0]["answer"],
                    "finished": True,
                }
            )
            for index, answer in enumerate(reference["answers"]):
                captions_called = []

                class CaptionSink:
                    def __init__(self, *args):
                        if set(full.evalQA) != {key} or "overall" not in full.accuracy:
                            raise ValueError(
                                "Caption adapter ran before completed accuracy"
                            )
                        captions_called.append(True)
                        self.eval = {}

                    def evaluate(self):
                        pass

                namespace["COCOEvalCap"] = CaptionSink
                full = namespace["VQAEval"](
                    _Dataset({key: copy.deepcopy(reference)}),
                    _Dataset({key: {"image": key, "answer": answer["answer"]}}),
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    full.evaluate()
                actual = component.score({key: reference}, {key: answer["answer"]})
                if actual != {
                    "accuracy": full.accuracy,
                    "per_case": full.evalQA,
                } or captions_called != [True]:
                    raise ValueError(
                        "Official accuracy prefix/full-class conformance failed"
                    )
                checks.append(
                    {
                        "case_id": key,
                        "reference_sha256": case["reference"]["sha256"],
                        "answer_index": index,
                        "text_accuracy_equal": True,
                        "caption_adapter_after_accuracy": True,
                    }
                )
                receipt["probes_completed"] = len(checks)
        predictions = {
            "schema": "hepta.terminal-vqa-predictions.v1",
            "status": "completed",
            "purpose": "development_diagnostic",
            "prediction_origin": "reference_conformance_probe",
            "manifest_sha256": manifest_sha256,
            "predictions": terminal,
        }
        binding = _write(
            root, "private/REFERENCE_PROBES.json", _json_bytes(predictions)
        )
        scored = score_terminal_pool(
            pool_root,
            root / binding["path"],
            upstream_path,
            expected_manifest_sha256=manifest_sha256,
            expected_history_sha256=history_sha256,
            expected_predictions_sha256=binding["sha256"],
        )
        score_binding = _write(
            root, "private/REFERENCE_PROBE_SCORE.json", _json_bytes(scored)
        )
        check_binding = _write(root, "CHECKS.json", _json_bytes(checks))
        receipt.update(
            {
                "status": "completed",
                "metric_lock": component.lock,
                "check_results": check_binding,
                "reference_probe_predictions": binding,
                "reference_probe_score": score_binding,
                "case_count": len(manifest["cases"]),
                "human_reference_count": len(checks),
                "independent_training_repeats": 0,
                "model_performance_claim": False,
                "independent_reviewers": 0,
                "confirmation_cases": 0,
                "retention_cases": 0,
                "scientific_admission": False,
                "research_status": "HOLD",
            }
        )
    except BaseException as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        receipt.update(
            {
                "cpu_seconds": time.process_time() - started[0],
                "wall_seconds": time.perf_counter() - started[1],
                "source_sha256": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (
                        Path(__file__),
                        Path(__file__).with_name("official_vqa_accuracy.py"),
                    )
                },
                "cost_scope": "inclusive conformance; nested scoring and admissions not additive",
                "unknown_costs": [
                    "process startup",
                    "final receipt write",
                    "energy",
                    "charges",
                ],
            }
        )
        _write(root, "CONFORMANCE.json", _json_bytes(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser()
    for name in ("pool", "upstream", "output", "manifest-sha256", "history-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = run(
        args.pool,
        args.upstream,
        args.output,
        manifest_sha256=args.manifest_sha256,
        history_sha256=args.history_sha256,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
