"""Read-only fit40 candidate replay, with historical producer identity unknown.

Only the request's fixed training JSONL is read for labels. Original inventory
files are checked before/after. No model, OCR, future collection or actor runs.
"""

import argparse
import ast
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys
import time
import types
import unicodedata

FIELDS = ("company", "date", "address", "total")
LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected, size=None, limit=64 * 1024 * 1024):
    if (
        type(expected) is not str
        or len(expected) != 64
        or any(c not in "0123456789abcdef" for c in expected)
    ):
        raise ValueError("LEGACY_PIN_SHAPE")
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or size is not None
        and (type(size) is not int or not 0 <= size <= limit)
    ):
        raise ValueError("LEGACY_INPUT_BOUND")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1 if size is None else size + 1)
    if (
        len(raw) > limit
        or size is not None
        and len(raw) != size
        or sha(raw) != expected
    ):
        raise ValueError("LEGACY_INPUT_PIN_MISMATCH")
    return raw


def partitions(plan):
    if plan.get("schema") != "ndu.ctrl.answer-repair-plan.v1":
        raise ValueError("LEGACY_PLAN_SCHEMA")
    groups = []
    for key, count in (
        ("original_fit_sources", 40),
        ("inner_train_sources", 32),
        ("inner_tune_sources", 8),
        ("future_sources", 37),
        ("excluded_sources", 20),
    ):
        values = plan.get(key)
        if (
            type(values) is not list
            or len(values) != count
            or any(type(x) is not str or not 0 < len(x) <= 512 for x in values)
            or len(set(values)) != count
        ):
            raise ValueError("LEGACY_PARTITION_BOUND")
        groups.append(set(values))
    fit, inner, tune, future, excluded = groups
    if (
        inner & tune
        or inner | tune != fit
        or fit & (future | excluded)
        or future & excluded
    ):
        raise ValueError("LEGACY_PARTITION_OVERLAP")
    return fit


def normalizer(raw):
    nodes = [
        n
        for n in ast.parse(raw).body
        if isinstance(n, ast.FunctionDef) and n.name == "canonical"
    ]
    if len(nodes) != 1 or nodes[0].decorator_list or nodes[0].args.defaults:
        raise ValueError("LEGACY_NORMALIZER_CONTRACT")
    namespace = dict(
        date=date,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        re=re,
        unicodedata=unicodedata,
    )
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), "<pinned-canonical>", "exec"),
        namespace,
    )
    return namespace["canonical"]


def project(raw, fit, canonical, coverage, bindings):
    lines = raw.splitlines()
    if (
        not lines
        or len(lines) > 8192
        or any(not line or len(line) > 2 * 1024 * 1024 for line in lines)
    ):
        raise ValueError("LEGACY_RECORD_BOUND")
    projected, states, fields = [], {s: set() for s in fit}, {}
    for line in lines:
        row = coverage._json(line)
        if (
            row.get("schema")
            not in {
                "ndu.real.training-transition.v1",
                "ndu.real.training-transition.v2",
            }
            or row.get("split") != "train"
            or row.get("source_group") not in fit
        ):
            raise ValueError("LEGACY_ROW_ROLE_OR_SOURCE")
        matrix, candidates = row["candidate_features"], row["candidate_metadata"]
        finite = lambda value: type(value) in (int, float) and math.isfinite(value)
        if (
            type(matrix) is not list
            or not 1 <= len(matrix) <= 128
            or any(
                type(x) is not list or len(x) != 126 or not all(finite(v) for v in x)
                for x in matrix
            )
            or type(candidates) is not list
            or len(candidates) != len(matrix)
        ):
            raise ValueError("LEGACY_FEATURE_SHAPE")
        size, field, metadata = (
            row["source_size"],
            row["reference_field"],
            row["public_metadata"],
        )
        if (
            type(size) is not dict
            or set(size) != {"width", "height"}
            or any(type(v) is not int or not 1 <= v <= 100000 for v in size.values())
            or size["width"] * size["height"] > 16000000
        ):
            raise ValueError("LEGACY_SOURCE_SIZE")
        if (
            field not in FIELDS
            or type(row["expected_text"]) is not str
            or not 1 <= len(row["expected_text"]) <= 8192
            or type(metadata) is not list
            or len(metadata) != 16
            or not all(finite(v) and 0 <= v <= 1 for v in metadata)
            or metadata[:4] != [float(field == f) for f in FIELDS]
            or metadata[10:12] != [0, 0]
        ):
            raise ValueError("LEGACY_REFERENCE_OR_METADATA")
        for c in candidates:
            if (
                type(c) is not dict
                or set(c) != {"text", "bbox", "origin"}
                or type(c["text"]) is not str
                or len(c["text"]) > 8192
                or c["origin"]
                not in {"pixel_ocr", "registered_public_text", "no_recognized_text"}
            ):
                raise ValueError("LEGACY_CANDIDATE_SCHEMA")
            box = c["bbox"]
            if (
                type(box) is not list
                or len(box) != 4
                or not all(finite(v) for v in box)
                or not 0 <= box[0] < box[2] <= size["width"]
                or not 0 <= box[1] < box[3] <= size["height"]
            ):
                raise ValueError("LEGACY_CANDIDATE_BOX")
        source, state = row["source_group"], coverage.digest(matrix)
        key = source, state
        if key in fields and fields[key] != field:
            raise ValueError("LEGACY_STATE_FIELD_CONFLICT")
        fields[key] = field
        states[source].add(state)
        target = canonical(row["expected_text"], field)
        positives = (
            None
            if target is None
            else [
                i
                for i, c in enumerate(candidates)
                if canonical(c["text"], field) == target
            ]
        )
        projected.append(
            dict(
                source_id=source,
                role="train",
                state_id=state,
                observation_id=row["record_id"],
                observation_sha256=sha(line),
                generator_sha256=bindings["generator_sha256"],
                bindings_sha256=coverage.digest(bindings),
                candidates=dict(
                    sha256=coverage.digest(candidates),
                    count=len(candidates),
                    positive_indices=positives,
                    selection=None,
                    pre_cap_unique_count=None,
                ),
            )
        )
    if any(not state_set for state_set in states.values()):
        raise ValueError("LEGACY_REGISTERED_SOURCE_HAS_NO_STATE_INVENTORY")
    sources = [
        dict(source_id=s, role="train", state_ids=sorted(states[s]))
        for s in sorted(fit)
    ]
    return projected, sources, fields


def field_summary(rows, fit, fields):
    unique = {(r["source_id"], r["state_id"]): r["candidates"] for r in rows}
    result = {}
    for field in FIELDS:
        groups = {source: [] for source in fit}
        values = [c for key, c in unique.items() if fields[key] == field]
        for key, c in unique.items():
            if fields[key] == field:
                groups[key[0]].append(
                    None
                    if c["positive_indices"] is None
                    else float(bool(c["positive_indices"]))
                )
        means = [
            None if not vs or None in vs else math.fsum(vs) / len(vs)
            for vs in groups.values()
        ]
        result[field] = dict(
            registered_sources=len(fit),
            observed_sources=sum(bool(vs) for vs in groups.values()),
            missing_sources=sum(not vs for vs in groups.values()),
            unique_states=len(values),
            oracle_ceiling=None if None in means else math.fsum(means) / len(means),
            known_uncovered_states=sum(c["positive_indices"] == [] for c in values),
            unknown_coverage_states=sum(c["positive_indices"] is None for c in values),
            at_cap_states=sum(c["count"] == 128 for c in values),
            truncation_unknown_states=len(values),
            selected_accuracy=None,
            selection_gap=None,
        )
    return result


def execute(
    request_path,
    request_sha256,
    coverage_source,
    coverage_source_sha256,
    adapter_sha256,
    output,
):
    started, cpu = time.perf_counter(), time.process_time()
    own_raw = read(__file__, adapter_sha256)
    if adapter_sha256 != LOADED_SHA256:
        raise ValueError("LEGACY_FRESH_WORKER_REQUIRED")
    coverage_raw = read(coverage_source, coverage_source_sha256)
    coverage = types.ModuleType("pinned_candidate_coverage")
    coverage.__file__ = str(coverage_source)
    exec(compile(coverage_raw, str(coverage_source), "exec"), coverage.__dict__)
    request_raw = read(request_path, request_sha256, limit=4 * 1024 * 1024)
    request = coverage._json(request_raw)
    if request.get("schema") != "ndu.ctrl.answer-repair-native-request.v1":
        raise ValueError("LEGACY_REQUEST_SCHEMA")
    plan = request["plan"]
    fit = partitions(plan)
    collection_raw = read(
        request["collection_plan"], request["collection_sha256"], limit=4 * 1024 * 1024
    )
    collection = coverage._json(collection_raw)
    pins = collection["source_pins"]
    if (
        collection.get("schema") != "ndu.real.stopped-collection-plan.v1"
        or type(pins) is not list
        or len(pins) != 60
        or len({p["path"] for p in pins}) != 60
        or sum(p["bytes"] for p in pins) > 8 * 1024 * 1024
        or sha(json.dumps(pins, sort_keys=True).encode())
        != plan["source_inventory_sha256"]
    ):
        raise ValueError("LEGACY_SOURCE_INVENTORY")
    normalizer_path = str(
        Path(collection["execution_config"]["scripts_root"])
        / "ndu_real_materials/evaluator.py"
    )
    normalizer_raw = None
    for pin in pins:
        source_raw = read(pin["path"], pin["sha256"], pin["bytes"])
        if (
            pin["path"] == normalizer_path
            and pin["sha256"] == plan["normalizer_sha256"]
        ):
            normalizer_raw = source_raw
    if normalizer_raw is None:
        raise ValueError("LEGACY_NORMALIZER_PIN_MISSING")
    matches = [
        p
        for p in collection["original_pins"]
        if p["path"] == request["records"] and p["sha256"] == plan["fit_records_sha256"]
    ]
    if len(matches) != 1:
        raise ValueError("LEGACY_FIXED_DATASET_PIN_MISSING")
    data_pin = matches[0]
    raw = read(data_pin["path"], data_pin["sha256"], data_pin["bytes"])
    contract = dict(
        schema="ndu.ctrl.legacy-candidate-projection.v1",
        records_sha256=sha(raw),
        adapter_sha256=adapter_sha256,
        historical_generator_identity=None,
        state_identity="source_group and canonical JSON raw candidate_features SHA256",
    )
    bindings = dict(
        generator_sha256=coverage.digest(contract),
        selector_sha256=coverage.digest(dict(selection="unobserved_in_legacy_rows")),
        normalizer_sha256=plan["normalizer_sha256"],
        observation_contract_sha256=coverage.digest(contract),
    )
    rows, sources, fields = project(
        raw, fit, normalizer(normalizer_raw), coverage, bindings
    )
    report = coverage.summarize(rows, sources, bindings=bindings)
    report["by_reference_field"] = field_summary(rows, fit, fields)
    for pin in pins:
        read(pin["path"], pin["sha256"], pin["bytes"])
    for path, expected, size in (
        (data_pin["path"], data_pin["sha256"], data_pin["bytes"]),
        (request_path, request_sha256, len(request_raw)),
        (request["collection_plan"], request["collection_sha256"], len(collection_raw)),
        (coverage_source, coverage_source_sha256, len(coverage_raw)),
        (__file__, adapter_sha256, len(own_raw)),
    ):
        read(path, expected, size)
    histogram = {}
    for source in sources:
        count = str(len(source["state_ids"]))
        histogram[count] = histogram.get(count, 0) + 1
    report.update(
        scope="legacy_frozen_file_observed_states_only",
        state_inventory_independently_preregistered=False,
        state_inventory_derivation="unique raw feature states within each source of the pinned historical file",
        legacy_projection_contract=contract,
        historical_producer_identity_authenticated=False,
        original_input_rows=len(rows),
        unique_states_per_source_histogram=histogram,
        agrees_with_prior_200_rows_160_states_four_per_source=len(rows) == 200
        and report["registered_states"] == 160
        and histogram == {"4": 40},
        input_pins=dict(
            request=dict(sha256=request_sha256, bytes=len(request_raw)),
            embedded_plan_sha256=coverage.digest(plan),
            collection=dict(sha256=sha(collection_raw), bytes=len(collection_raw)),
            records=dict(sha256=sha(raw), bytes=len(raw)),
            source_inventory_sha256=plan["source_inventory_sha256"],
        ),
        execution=dict(
            adapter_sha256=adapter_sha256,
            coverage_sha256=coverage_source_sha256,
            normalizer_sha256=sha(normalizer_raw),
            original_source_files_verified_before_and_after=len(pins),
            python=sys.version,
            implementation=sys.implementation.name,
            platform=sys.platform,
            machine=platform.machine(),
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu,
            duration_scope="entry only; imports, launcher, final serialization and transport excluded",
            physical_full_cost_observed=False,
            model_inference_calls=0,
            training_steps=0,
            ocr_calls=0,
            future_labels_opened=False,
        ),
    )
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "RESULT.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "request",
        "request-sha256",
        "coverage-source",
        "coverage-source-sha256",
        "adapter-sha256",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        report = execute(
            args.request,
            args.request_sha256,
            args.coverage_source,
            args.coverage_source_sha256,
            args.adapter_sha256,
            args.output,
        )
    except Exception as error:
        code = str(error)
        if (
            not code.startswith(("LEGACY_", "COVERAGE_"))
            or not code.replace("_", "").isalnum()
        ):
            code = "LEGACY_REJECTED"
        print(json.dumps(dict(status="rejected", error_code=code)))
        return 2
    print(
        json.dumps(
            dict(
                status="completed",
                unique_states=report["registered_states"],
                oracle_ceiling=report["source_equal_means"]["oracle_ceiling"],
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
