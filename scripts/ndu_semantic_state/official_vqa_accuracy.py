"""Pinned official VizWiz text accuracy; offline development diagnostics only.

The original source stays private. This component executes its unchanged accuracy
statements through setAccuracy, excluding caption and unanswerability metrics.
It neither qualifies five task families nor proves operating-system isolation.
"""

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

from .materials import _read, _strict_json, check_file
from .review_packet import _json_bytes
from .source_pool import admit_candidate_pool
from .state import exact_fields, sha256_value


UPSTREAM_SHA256 = "d26ef7ac2db06351444c3531f8d95fd9c454423fbcb9fd5dd984f12281146694"
METRIC = "vizwiz.official-20230316.text-accuracy-prefix.v1"
METHODS = {
    "__init__",
    "evaluate",
    "processPunctuation",
    "processDigitArticle",
    "setAccuracy",
    "setEvalQA",
    "setEvalAnsType",
    "updateProgress",
}


class _Dataset:
    def __init__(self, rows):
        self.imgToQA = rows

    def getImgs(self):
        return list(self.imgToQA)


class LockedTextAccuracy:
    def __init__(self, source_path):
        raw = Path(source_path).read_bytes()
        if len(raw) != 11856 or hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
            raise ValueError("Official evaluator source differs from the fixed pin")
        tree = ast.parse(raw, filename="official-vizwiz-vqaEval.py")
        classes = [
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VQAEval"
        ]
        if len(classes) != 1:
            raise ValueError("Expected one pinned VQAEval class")
        component = copy.deepcopy(classes[0])
        component.body = [
            n
            for n in component.body
            if isinstance(n, ast.FunctionDef) and n.name in METHODS
        ]
        if {n.name for n in component.body} != METHODS:
            raise ValueError("Official accuracy method roster differs")
        evaluate = next(n for n in component.body if n.name == "evaluate")
        boundary = [
            i
            for i, n in enumerate(evaluate.body)
            if (
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute)
                and isinstance(n.value.func.value, ast.Name)
                and n.value.func.value.id == "self"
                and n.value.func.attr == "setAccuracy"
            )
        ]
        if len(boundary) != 1:
            raise ValueError("Official text/caption boundary differs")
        evaluate.body = evaluate.body[: boundary[0] + 1]
        extracted = ast.Module(body=[component], type_ignores=[])
        identity = hashlib.sha256(
            ast.dump(extracted, include_attributes=False).encode()
        ).hexdigest()
        namespace = {
            "re": re,
            "sys": sys,
            "__name__": "locked_official_vizwiz_accuracy",
        }
        exec(compile(extracted, "official-vizwiz-accuracy-prefix", "exec"), namespace)
        self.evaluator = namespace["VQAEval"]
        self.lock = {
            "metric": METRIC,
            "upstream_sha256": UPSTREAM_SHA256,
            "upstream_bytes": len(raw),
            "component_ast_sha256": identity,
            "python_version": sys.version.split()[0],
            "extraction": "VQAEval accuracy statements through first self.setAccuracy call",
            "rounding_decimal_places": 2,
            "unit": "percent",
            "ground_truth_normalization": "none added; original human answer strings preserved",
            "excluded_metrics": ["caption", "unanswerability"],
            "upstream_source_republished": False,
        }

    def score(self, originals, predictions):
        if not originals or set(originals) != set(predictions):
            raise ValueError("Nonempty exact prediction/reference roster required")
        gold, answers = {}, {}
        for key, original in originals.items():
            if not isinstance(key, str) or not isinstance(predictions[key], str):
                raise ValueError("String case identifiers and predictions required")
            references = original.get("answers")
            if (
                not isinstance(original.get("answer_type"), str)
                or not isinstance(references, list)
                or len(references) != 10
                or any(
                    not isinstance(a, dict) or not isinstance(a.get("answer"), str)
                    for a in references
                )
            ):
                raise ValueError("Ten original human answers and answer type required")
            gold[key] = copy.deepcopy(original)
            answers[key] = {"answer": predictions[key], "image": key}
        evaluator = self.evaluator(_Dataset(gold), _Dataset(answers), n=2)
        with contextlib.redirect_stdout(io.StringIO()):
            evaluator.evaluate()
        if evaluator.caption_metric or evaluator.unanswerability:
            raise ValueError("Text component unexpectedly produced other metrics")
        return {"accuracy": evaluator.accuracy, "per_case": evaluator.evalQA}


def _pinned_json(root, path, expected, limit):
    raw, actual, _ = _read(root, path, limit)
    if actual != sha256_value(expected, "external input pin"):
        raise ValueError("Evaluation input differs from the external pin")
    return _strict_json(raw)


def validate_terminal_predictions(envelope, expected_manifest_sha256, case_ids):
    """Validate before opening any reference. This is an API boundary, not custody."""
    exact_fields(
        envelope,
        (
            "schema",
            "status",
            "purpose",
            "prediction_origin",
            "manifest_sha256",
            "predictions",
        ),
        "prediction envelope",
    )
    if (
        envelope["schema"] != "hepta.terminal-vqa-predictions.v1"
        or envelope["status"] != "completed"
        or envelope["purpose"] != "development_diagnostic"
        or envelope["prediction_origin"]
        not in {
            "captured_model_output",
            "reference_conformance_probe",
            "synthetic_boundary_fixture",
        }
        or envelope["manifest_sha256"] != expected_manifest_sha256
    ):
        raise ValueError("Only completed, pinned development predictions are accepted")
    if not isinstance(envelope["predictions"], list):
        raise ValueError("Prediction list required")
    predictions = {}
    for row in envelope["predictions"]:
        exact_fields(row, ("id", "answer", "finished"), "terminal prediction")
        if (
            not isinstance(row["id"], str)
            or not isinstance(row["answer"], str)
            or row["finished"] is not True
            or row["id"] in predictions
        ):
            raise ValueError("Unique finished string predictions required")
        predictions[row["id"]] = row["answer"]
    if (
        not case_ids
        or set(predictions) != set(case_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        raise ValueError("Prediction roster differs from the predeclared selection")
    return predictions


def score_terminal_pool(
    pool_root,
    prediction_path,
    upstream_path,
    *,
    expected_manifest_sha256,
    expected_history_sha256,
    expected_predictions_sha256,
):
    started = time.process_time(), time.perf_counter()
    manifest = _pinned_json(
        pool_root, "CANDIDATES.json", expected_manifest_sha256, 8 * 1024**2
    )
    path = Path(prediction_path)
    envelope = _pinned_json(
        path.parent, path.name, expected_predictions_sha256, 2 * 1024**2
    )
    cases = manifest["cases"]
    predictions = validate_terminal_predictions(
        envelope, expected_manifest_sha256, [c["id"] for c in cases]
    )
    if any(c["project_split"] not in {"train", "development"} for c in cases):
        raise ValueError("This component cannot certify confirmation or retention")
    admission = admit_candidate_pool(
        pool_root,
        "CANDIDATES.json",
        "HISTORY.json",
        expected_history_sha256=expected_history_sha256,
    )
    if admission["manifest_sha256"] != expected_manifest_sha256:
        raise ValueError("Manifest changed during offline admission")
    references = {
        c["id"]: _strict_json(check_file(pool_root, c["reference"], limit=2 * 1024**2))
        for c in cases
    }
    component = LockedTextAccuracy(upstream_path)
    split_scores = {}
    for split in ("train", "development"):
        roster = [c["id"] for c in cases if c["project_split"] == split]
        if roster:
            split_scores[split] = component.score(
                {k: references[k] for k in roster}, {k: predictions[k] for k in roster}
            )
    return {
        "schema": "hepta.official-vqa-development-score.v1",
        "status": "completed",
        "purpose": "development_diagnostic",
        "prediction_origin": envelope["prediction_origin"],
        "metric_lock": component.lock,
        "manifest_sha256": expected_manifest_sha256,
        "history_sha256": expected_history_sha256,
        "predictions_sha256": expected_predictions_sha256,
        "source_admission": admission,
        "score": component.score(references, predictions),
        "split_scores": split_scores,
        "case_count": len(cases),
        "independent_cluster_count": None,
        "claim_limits": [
            "terminal flags and hashes do not prove generator custody or prevent prior exposure",
            "only the host-side scorer reads original references; operating-system isolation unverified",
            "official text accuracy is not a five-family domain evaluator or image-quality score",
            "this newly locked diagnostic does not replace any ongoing pilot primary metric",
        ],
        "scientific_admission": False,
        "research_status": "HOLD",
        "cpu_seconds": time.process_time() - started[0],
        "wall_seconds": time.perf_counter() - started[1],
        "cost_scope": "inclusive offline scoring; admission costs nested",
        "unknown_costs": [
            "process startup",
            "final receipt write",
            "energy",
            "charges",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "pool",
        "predictions",
        "upstream",
        "manifest-sha256",
        "history-sha256",
        "predictions-sha256",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    result = score_terminal_pool(
        args.pool,
        args.predictions,
        args.upstream,
        expected_manifest_sha256=args.manifest_sha256,
        expected_history_sha256=args.history_sha256,
        expected_predictions_sha256=args.predictions_sha256,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(_json_bytes(result))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
