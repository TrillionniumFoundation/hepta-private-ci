"""Read-only exact-source replay of frozen exposed reader-format trial receipts.

A second process recomputes prompts, all token IDs, original answers, scoring,
and actually reruns the authored selector worker. It makes ZERO model calls and
is not an independent semantic adjudicator or Hugging Face parity validator.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from offline_event_reader_trial import inputs
from historical_reader_format_source import locked_reader_format


def replay(archive, reader_dir, execution_dir, output):
    if output.exists():
        raise ValueError("refuse to overwrite verifier receipt")
    result = Path(execution_dir)
    prereg = json.loads((result / "preregistered.json").read_text())
    journal_bytes = (result / "raw-answers.jsonl").read_bytes()
    if (
        hashlib.sha256(journal_bytes).hexdigest()
        != json.loads((result / "report.json").read_text())["raw_journal_sha256"]
    ):
        raise ValueError("original journal digest changed")
    plan, sources, worker_bytes = inputs(archive)
    prompt, reader, frozen_sources = locked_reader_format()
    STYLES, ARMS = prompt.STYLES, prompt.ARMS
    build_messages, strict_answer = prompt.build_messages, prompt.strict_answer
    PINS, digest = reader.PINS, reader.digest
    if (
        prereg["source_files"] != frozen_sources
        or prereg["pinned_model_files"] != PINS
        or tuple(prereg["styles"]) != STYLES
        or tuple(prereg["evidence_arms"]) != ARMS
        or prereg["raw_answers_before_label_access"] is not True
        or prereg["prior_task_exposure"] is not True
    ):
        raise ValueError("generating source/plan/controls changed")
    reader.verify_files(reader_dir)
    tokenizer = reader.ByteLevel(reader_dir)
    original = [json.loads(line) for line in journal_bytes.decode().splitlines()]
    evaluated = json.loads((result / "scored-answers.json").read_text())
    wanted = [
        (c["query"]["identity"], s, a)
        for c in plan["cases"]
        for s in STYLES
        for a in ARMS
    ]
    if (
        len(original) != 64
        or len(evaluated) != 64
        or prereg["census"] != [list(row) for row in wanted]
    ):
        raise ValueError("incomplete original request census")
    with __import__("zipfile").ZipFile(archive) as z:
        labels_raw = z.read("observations/labels.json")
    if hashlib.sha256(labels_raw).hexdigest() != plan["labels_sha"]:
        raise ValueError("original target labels changed")
    truths = {r["id"]: r for r in json.loads(labels_raw)}
    worker = result / "original-event-probe.py"
    if worker.read_bytes() != worker_bytes:
        raise ValueError("original authored worker changed")
    cases = {c["query"]["identity"]: c for c in plan["cases"]}
    result_by = {}
    replayed_program_checks = 0
    for raw, scored, key in zip(original, evaluated, wanted, strict=True):
        qid, style, arm = key
        if (
            any(
                r["question_id"] != qid
                or r["representation"] != style
                or r["arm"] != arm
                for r in (raw, scored)
            )
            or raw["status"] != "succeeded"
        ):
            raise ValueError("original answer or arm missing, moved or failed")
        c = cases[qid]
        msgs, selected = build_messages(c, arm, style, sources)
        prompt = tokenizer.render(msgs)
        ids = tokenizer.encode(prompt)
        if (
            msgs != raw["messages"]
            or prompt != raw["prompt"]
            or ids != raw["input_ids"]
            or digest(ids) != raw["input_digest"]
            or selected != raw["selected"]
            or raw["candidate_digest"] != c["candidate_digest"]
            or len(ids) > 2048
            or len(raw["generated_ids"]) > 64
            or tokenizer.decode(raw["generated_ids"]) != raw["answer"]
        ):
            raise ValueError("original request/tokenization/output not reproducible")
        for k, v in raw.items():
            if scored.get(k) != v:
                raise ValueError("scored answer silently rewrote original inference")
        truth = truths[qid]
        expected = strict_answer(raw["answer"])
        selected_citations = set()
        for token in re.findall(r"\[E([1-9][0-9]*)\]", raw["answer"]):
            num = int(token)
            if 1 <= num <= len(selected):
                selected_citations.add(selected[num - 1])
        checks = {
            "parsed_identifier": expected,
            "expected_identifier_mentioned": truth["expected"]
            in re.findall(r"(?:site|mode)_[0-9a-f]{8}", raw["answer"]),
            "required_sources_covered": set(truth["support"]).issubset(selected),
            "declared_support_chain_cited": set(truth["support"]).issubset(
                selected_citations
            ),
            "semantic_citation_precision": None,
        }
        if truth["kind"] == "procedure":
            supplied = expected or "invalid_response"
            request = dict(
                operation="execute", recipe=truth["procedure"], supplied=supplied
            )
            checked = subprocess.run(
                [sys.executable, "-I", "-S", str(worker)],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            checks["strict_task_success"] = checked.returncode == 0
            if (
                scored["program_verification"]["exit_code"] != checked.returncode
                or scored["program_verification"]["stdout"] != checked.stdout
                or scored["program_verification"]["stderr"] != checked.stderr
                or scored["program_verification"]["request"] != request
            ):
                raise ValueError("original bounded program outcome changed")
            replayed_program_checks += 1
        else:
            checks["strict_task_success"] = expected == truth["expected"]
        if any(scored.get(k) != v for k, v in checks.items()):
            raise ValueError("score or citation was reconstructed incorrectly")
        result_by.setdefault(f"{style}/{arm}", []).append(checks)
    receipt = dict(
        schema="hepta.memory.reader-representation-independent-process-replay.v1",
        generator_commit=prereg["generating_commit"],
        source_bytes=frozen_sources,
        original_journal_sha256=hashlib.sha256(journal_bytes).hexdigest(),
        verified_inference_requests_and_answers=64,
        reexecuted_authored_program_checks=replayed_program_checks,
        by_condition={
            k: dict(
                n=len(v),
                strict_success=sum(r["strict_task_success"] for r in v),
                value_mentions=sum(r["expected_identifier_mentioned"] for r in v),
                declared_support_citation=sum(
                    r["declared_support_chain_cited"] for r in v
                ),
            )
            for k, v in sorted(result_by.items())
        },
        additional_model_calls=0,
        independent_human_adjudication=False,
        hf_runtime_and_tokenizer_parity_certified=False,
        source_families_are_previously_exposed=True,
        production_accepted=False,
    )
    with output.open("x", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "reader", "execution", "output"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    replay(args.archive, args.reader, args.execution, args.output)
