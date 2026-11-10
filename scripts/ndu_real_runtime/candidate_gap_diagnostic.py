"""Pinned train-only retained-text probes, without new observations or selection.

Proposals receive only recorded candidate text, boxes, origins and field. Labels
are used afterwards to classify coverage. No missing text or READ effect is
inferred; historical producer identity and complete observation inventory remain
unknown. This diagnostic does not encode/install candidates in the actor.
"""

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import types
import unicodedata

LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DATE = r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b"
MONEY = r"(?<!\w)(?:RM\s*)?[-+]?\d[\d,]*\.\d{2}(?!\d)"
NUMERIC_DATE = r"(?<!\w)(\d{1,4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,4})(?!\w)"
NUMERIC_AMOUNT = (
    r"(?<![\w.,])(?:RM\s*|MYR\s*)?([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\w.,])"
)
CATEGORIES = (
    "covered",
    "A_frozen_regex",
    "B_numeric_format",
    "C_other_recorded_state",
    "D_evidence_insufficient",
    "unknown_reference",
    "out_of_scope",
)


def profile():
    return dict(
        schema="ndu.ctrl.retained-text-gap-rules.v1",
        frozen_date=DATE,
        frozen_money=MONEY,
        numeric_date=NUMERIC_DATE,
        numeric_amount=NUMERIC_AMOUNT,
        families=("A_frozen_regex", "B_numeric_format"),
        category_priority=CATEGORIES,
        date_policy="NFKC; remove separator whitespace; four-digit year-first to day/month/year; no day/month swap or month names",
        amount_policy="NFKC; dot decimal and grouped thousands comma; integer or any positive fractional width; no decimal-comma or OCR-character repair",
        candidate_cap=128,
        max_proposals=64,
        max_scanned_matches=4096,
        max_input_text_chars=8192,
        proposal_order="family, original candidate index, regex match order",
        deduplication="text, source bbox, origin; preserve original candidates",
    )


def verify_lexers(raw):
    found = {}
    for node in ast.parse(raw).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"DATE", "MONEY"}
        ):
            call = node.value
            if (
                not isinstance(call, ast.Call)
                or ast.unparse(call.func) != "re.compile"
                or call.keywords
            ):
                raise ValueError("GAP_FROZEN_LEXER_CONTRACT")
            found[node.targets[0].id] = (
                ast.literal_eval(call.args[0]),
                [ast.unparse(a) for a in call.args[1:]],
            )
    if found != {"DATE": (DATE, []), "MONEY": (MONEY, ["re.I"])}:
        raise ValueError("GAP_FROZEN_LEXER_MISMATCH")


def spans(text, field, family):
    if family == "A_frozen_regex":
        for match in re.finditer(DATE if field == "date" else MONEY, text, re.I):
            yield match.group().strip()
        return
    text = unicodedata.normalize("NFKC", text).upper()
    if field == "date":
        for match in re.finditer(NUMERIC_DATE, text):
            first, middle, last = match.groups()
            if len(first) == 4 and len(last) <= 2:
                yield f"{last}/{middle}/{first}"
            elif len(first) <= 2 and len(last) in {2, 4}:
                yield f"{first}/{middle}/{last}"
    else:
        text = re.sub(r"(?<=\d)\s*([.,])\s*(?=\d)", r"\1", text)
        for match in re.finditer(NUMERIC_AMOUNT, text):
            yield match.group(1)


def propose(candidates, field):
    """Target-free metadata proposals only; no reference/normalizer argument."""
    if field not in {"date", "total"} or not 1 <= len(candidates) <= 128:
        raise ValueError("GAP_PUBLIC_INPUT_BOUND")
    for c in candidates:
        if (
            set(c) != {"text", "bbox", "origin"}
            or type(c["text"]) is not str
            or len(c["text"]) > 8192
        ):
            raise ValueError("GAP_PUBLIC_INPUT_BOUND")
    key = lambda text, c: (text, tuple(c["bbox"]), c["origin"])
    seen = {key(c["text"], c) for c in candidates}
    kept, counts = [], Counter()
    room = min(64, 128 - len(candidates))
    for family in ("A_frozen_regex", "B_numeric_format"):
        for index, c in enumerate(candidates):
            for text in spans(c["text"], field, family):
                if counts["scanned_matches"] == 4096:
                    counts["scan_censored"] = 1
                    return kept, dict(counts)
                counts["scanned_matches"] += 1
                identity = key(text, c)
                if identity in seen:
                    continue
                seen.add(identity)
                counts["unique_proposals_seen"] += 1
                if len(kept) < room:
                    kept.append(dict(text=text, parent_index=index, family=family))
                    counts["retained_proposals"] += 1
                elif counts["unique_proposals_seen"] > 64:
                    counts["known_dropped_by_proposal_limit"] += 1
                else:
                    counts["known_dropped_by_candidate_cap"] += 1
    return kept, dict(counts)


def aggregate(states, fit):
    groups = {s: [] for s in fit}
    for state in states:
        groups[state["source"]].append(state)
    counts = Counter(s["category"] for s in states)
    known = all(
        vs
        and all(v["category"] not in {"unknown_reference", "out_of_scope"} for v in vs)
        for vs in groups.values()
    )
    rate = lambda names: (
        None
        if not known
        else math.fsum(
            sum(v["category"] in names for v in vs) / len(vs) for vs in groups.values()
        )
        / len(groups)
    )
    probe_counts = Counter()
    for state in states:
        probe_counts.update(state["proposal_counts"])
    return dict(
        registered_sources=len(fit),
        observed_sources=sum(bool(v) for v in groups.values()),
        missing_sources=sum(not v for v in groups.values()),
        unique_states=len(states),
        categories={c: counts[c] for c in CATEGORIES},
        source_equal_original_coverage=rate({"covered"}),
        source_equal_probe_candidate_availability=rate(
            {"covered", "A_frozen_regex", "B_numeric_format"}
        ),
        source_equal_category_rates={c: rate({c}) for c in CATEGORIES},
        A_and_B_retained_match_states=sum(s["both"] for s in states),
        proposal_counts=dict(probe_counts),
        budget_censored_states=sum(s["censored"] for s in states),
        D_with_budget_censoring=sum(
            s["category"] == "D_evidence_insufficient" and s["censored"] for s in states
        ),
        selected_accuracy=None,
        selection_gap=None,
        unavailable_observation_states=None,
    )


def diagnose(rows, fit, canonical, coverage):
    # Freeze every target-free proposal before accessing expected_text.
    unique, proposals = {}, {}
    for row in rows:
        key = row["source_group"], coverage.digest(row["candidate_features"])
        if key not in unique:
            unique[key] = row
            proposals[key] = (
                propose(row["candidate_metadata"], row["reference_field"])
                if row["reference_field"] in {"date", "total"}
                else ([], {})
            )
    values, targets = {}, {}
    for key, row in unique.items():
        field = row["reference_field"]
        targets[key] = canonical(row["expected_text"], field)
        values[key] = {
            v
            for c in row["candidate_metadata"]
            if (v := canonical(c["text"], field)) is not None
        }
    for row in rows:
        key = row["source_group"], coverage.digest(row["candidate_features"])
        if (
            row["reference_field"] != unique[key]["reference_field"]
            or row["candidate_metadata"] != unique[key]["candidate_metadata"]
            or canonical(row["expected_text"], row["reference_field"]) != targets[key]
        ):
            raise ValueError("GAP_DUPLICATE_STATE_CONFLICT")
    references = {}
    for key, row in unique.items():
        identity = key[0], row["reference_field"]
        target = targets[key]
        if target is not None:
            if identity in references and references[identity] != target:
                raise ValueError("GAP_SOURCE_FIELD_REFERENCE_CONFLICT")
            references[identity] = target
    states = []
    for key, row in unique.items():
        field, target = row["reference_field"], targets[key]
        kept, counts = proposals[key]
        hits = {
            p["family"]
            for p in kept
            if target is not None and canonical(p["text"], field) == target
        }
        if field not in {"date", "total"}:
            category = "out_of_scope"
        elif target is None:
            category = "unknown_reference"
        elif target in values[key]:
            category = "covered"
        elif hits:
            category = (
                "A_frozen_regex" if "A_frozen_regex" in hits else "B_numeric_format"
            )
        elif any(
            other != key
            and other[0] == key[0]
            and unique[other]["reference_field"] == field
            and target in vs
            for other, vs in values.items()
        ):
            category = "C_other_recorded_state"
        else:
            category = "D_evidence_insufficient"
        states.append(
            dict(
                source=key[0],
                field=field,
                category=category,
                both=len(hits) == 2,
                proposal_counts=counts,
                censored=bool(
                    counts.get("scan_censored")
                    or counts.get("known_dropped_by_proposal_limit")
                    or counts.get("known_dropped_by_candidate_cap")
                ),
            )
        )
    return dict(
        overall=aggregate(states, fit),
        by_reference_field={
            f: aggregate([s for s in states if s["field"] == f], fit)
            for f in ("date", "total")
        },
    )


def load(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("GAP_SOURCE_PIN_MISMATCH")
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if hashlib.sha256(raw).hexdigest() != expected or len(raw) > 1024 * 1024:
        raise ValueError("GAP_SOURCE_PIN_MISMATCH")
    module = types.ModuleType("pinned_" + Path(path).stem)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def execute(
    request,
    request_sha256,
    coverage_source,
    coverage_source_sha256,
    legacy_source,
    legacy_source_sha256,
    diagnostic_sha256,
    output,
):
    started, cpu = time.perf_counter(), time.process_time()
    if diagnostic_sha256 != LOADED_SHA256:
        raise ValueError("GAP_FRESH_WORKER_REQUIRED")
    coverage = load(coverage_source, coverage_source_sha256)
    legacy = load(legacy_source, legacy_source_sha256)
    legacy.read(__file__, diagnostic_sha256)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    arguments = (
        request,
        request_sha256,
        coverage_source,
        coverage_source_sha256,
        legacy_source_sha256,
    )
    before = legacy.execute(*arguments, destination / "BASELINE_BEFORE")
    if not before["agrees_with_prior_200_rows_160_states_four_per_source"]:
        raise ValueError("GAP_FIT40_STATE_SCOPE")
    request_data = coverage._json(
        legacy.read(request, request_sha256, before["input_pins"]["request"]["bytes"])
    )
    plan = request_data["plan"]
    collection = coverage._json(
        legacy.read(
            request_data["collection_plan"],
            request_data["collection_sha256"],
            before["input_pins"]["collection"]["bytes"],
        )
    )

    def original_source(relative):
        path = str(Path(collection["execution_config"]["scripts_root"]) / relative)
        matches = [p for p in collection["source_pins"] if p["path"] == path]
        if len(matches) != 1:
            raise ValueError("GAP_ORIGINAL_SOURCE_PIN")
        pin = matches[0]
        return legacy.read(path, pin["sha256"], pin["bytes"])

    normalizer_raw = original_source("ndu_real_materials/evaluator.py")
    ocr_raw = original_source("ndu_real_runtime/ocr.py")
    verify_lexers(ocr_raw)
    pin = before["input_pins"]["records"]
    raw = legacy.read(request_data["records"], pin["sha256"], pin["bytes"])
    rows = [coverage._json(line) for line in raw.splitlines()]
    result = diagnose(
        rows, legacy.partitions(plan), legacy.normalizer(normalizer_raw), coverage
    )
    after = legacy.execute(*arguments, destination / "BASELINE_AFTER")
    if (
        before["input_pins"] != after["input_pins"]
        or before["source_equal_means"] != after["source_equal_means"]
    ):
        raise ValueError("GAP_BASELINE_CHANGED")
    legacy.read(__file__, diagnostic_sha256)
    legacy.read(legacy_source, legacy_source_sha256)
    legacy.read(coverage_source, coverage_source_sha256)
    result.update(
        schema="ndu.ctrl.retained-text-gap-report.v1",
        scope="fixed_train40_historical_retained_candidate_text_only",
        rules=profile(),
        rules_sha256=coverage.digest(profile()),
        input_pins=before["input_pins"],
        sources=dict(
            diagnostic_sha256=diagnostic_sha256,
            coverage_sha256=coverage_source_sha256,
            legacy_sha256=legacy_source_sha256,
            normalizer_sha256=legacy.sha(normalizer_raw),
            frozen_ocr_sha256=legacy.sha(ocr_raw),
        ),
        baseline_results_sha256={
            phase: legacy.sha((destination / phase / "RESULT.json").read_bytes())
            for phase in ("BASELINE_BEFORE", "BASELINE_AFTER")
        },
        original_rows=len(rows),
        unique_states=before["registered_states"],
        state_inventory_independently_preregistered=False,
        historical_generator_identity=None,
        historical_producer_identity_authenticated=False,
        interpretation=dict(
            A="retained text contains a frozen-lexer match; historical extraction attribution unverified",
            B="fixed target-free numeric projection contains a scorer match; semantic correctness and selection unmeasured",
            C="another recorded same-source same-field state contains the scorer match; no reachability or READ causal claim",
            D="fixed probes did not retain a scorer match; original pixels, full OCR inventory and availability unknown",
            priority="A before B before C; overlaps reported; categories are diagnostic attribution, not causal effects",
            candidate_budget="proposals preserve the original prefix; 64 proposal and 128 total limits; scan/drop censorship explicit",
        ),
        execution=dict(
            python=sys.version,
            legacy_validation_rounds=2,
            original_source_files_per_round=60,
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu,
            duration_scope="entry only; imports, launcher, final serialization and transport excluded",
            full_physical_cost_observed=False,
            model_inference_calls=0,
            training_steps=0,
            ocr_calls=0,
            new_observations=0,
            future_labels_opened=False,
        ),
        new_independent_tasks=0,
        policy_efficacy_evaluated=False,
        actor_installed=False,
        production_admission=False,
    )
    with (destination / "RESULT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "request",
        "request-sha256",
        "coverage-source",
        "coverage-source-sha256",
        "legacy-source",
        "legacy-source-sha256",
        "diagnostic-sha256",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    try:
        report = execute(**vars(parser.parse_args(argv)))
    except Exception as error:
        code = str(error)
        if (
            not code.startswith(("GAP_", "LEGACY_", "COVERAGE_"))
            or not code.replace("_", "").isalnum()
        ):
            code = "GAP_REJECTED"
        print(json.dumps(dict(status="rejected", error_code=code)))
        return 2
    print(
        json.dumps(
            dict(
                status="completed",
                unique_states=report["unique_states"],
                categories=report["overall"]["categories"],
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
