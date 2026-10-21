"""Inspect source-order six-event prompt budgets without loading any model."""

import argparse
import hashlib
import itertools
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from event_experience import question
from event_projection import EventProjection
from event_reader_view import event_prompt
from strong_rag_trial import _bundle, documents
from transformers import AutoTokenizer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("model_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    manifest_path = args.collection / "collection.json"
    manifest = json.loads(manifest_path.read_bytes())
    inputs = {}
    for name in ("sources.json", "questions.json"):
        raw = (args.collection / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
            raise ValueError("frozen source input changed")
        inputs[name] = json.loads(raw)
    originals = documents(inputs["sources.json"])
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_directory, local_files_only=True, trust_remote_code=False
    )
    observed_at = datetime.now(timezone.utc).isoformat()
    cases = []
    for spec in inputs["questions.json"]:
        query, _ = question(spec, observed_at)
        scoped = tuple(d for d in originals.values() if d.scope == query.scope)
        projection = EventProjection(scoped)
        count, maximum, failed, first_failure = 0, 0, 0, None
        for selected in itertools.combinations([d.identity for d in scoped], 6):
            count += 1
            try:
                ids, _ = event_prompt(
                    tokenizer,
                    query,
                    _bundle(
                        query,
                        selected,
                        originals,
                        frontier=projection.frontier,
                        arm="tokenizer_only_budget_diagnostic",
                    ),
                    originals,
                    frontier=projection.frontier,
                    revoked=set(),
                    token_limit=2048,
                )
                maximum = max(maximum, len(ids))
            except Exception as error:
                failed += 1
                if first_failure is None:
                    first_failure = {
                        "selected": selected,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
        cases.append(
            dict(
                question_id=query.identity,
                combinations=count,
                max_admitted_tokens=maximum,
                failed=failed,
                first_failure=first_failure,
            )
        )
    if "torch" in sys.modules:
        raise ValueError("tokenizer-only audit unexpectedly imported torch")
    result = {
        "schema": "hepta.external-git-event.tokenizer-budget.v2",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "collection_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "query_observed_at_for_this_diagnostic": observed_at,
        "token_limit": 2048,
        "all_six_source_combinations_in_builder_order": True,
        "ranked_runtime_prompts_require_separate_preflight": True,
        "labels_read": False,
        "model_called": False,
        "torch_imported": False,
        "seconds": time.perf_counter() - started,
        "cases": cases,
        "qualification": "NO_GO",
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "cases": len(cases),
                "combinations": sum(c["combinations"] for c in cases),
                "failed": sum(c["failed"] for c in cases),
                "maximum": max(c["max_admitted_tokens"] for c in cases),
            }
        )
    )


if __name__ == "__main__":
    main()
