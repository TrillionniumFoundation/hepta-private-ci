"""Second-process read-only replay of sealed authored source-local trial.

Preserves original source and stdout bytes; never reclassifies this symbolic
parser as an independent human judge, general Reader or production candidate.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from local_causal_reader import SCHEMA, answer, digest
from run_local_causal_trial import ARCHIVE_SHA, ARMS, file_sha, write


def audit(archive, recorded, destination, *, source_commit):
    root = Path(recorded)
    locked = json.loads((root / "preregistered.json").read_text())
    if (
        locked["generating_commit"] != source_commit
        or locked["schema"] != "hepta.memory.local-causal-trial.v1"
        or locked["input_profile"] != SCHEMA
        or locked["arms"] != list(ARMS)
        or locked["no_label_before_answer_journal"] is not True
    ):
        raise ValueError("generating identity or preregistration drift")
    for name, expected in locked["source_sha256"].items():
        source = Path(__file__).with_name(name)
        if file_sha(source) != expected:
            raise ValueError("generating source changed")
    if file_sha(archive) != ARCHIVE_SHA:
        raise ValueError("original original-source archive changed")
    with zipfile.ZipFile(archive) as z:
        plan_bytes = z.read("plan/plan.json")
        source_bytes = z.read("plan/source-view.json")
        plan = json.loads(plan_bytes)
        if (
            hashlib.sha256(plan_bytes).hexdigest() != locked["original_plan_sha256"]
            or hashlib.sha256(source_bytes).hexdigest()
            != locked["original_source_sha256"]
        ):
            raise ValueError("original plan or source bytes drift")
        original_rows = json.loads(source_bytes)
        originals = {d["identity"]: d for d in original_rows}
        if len(originals) != len(original_rows):
            raise ValueError("duplicate original sources")
        target_bytes = z.read("observations/labels.json")
        worker_bytes = z.read("source/event_probe.py")
    if hashlib.sha256(target_bytes).hexdigest() != plan["labels_sha"]:
        raise ValueError("original label file drift")
    if hashlib.sha256(worker_bytes).hexdigest() != locked["original_worker_sha256"]:
        raise ValueError("original worker changed")
    raw = (root / "raw-answers.jsonl").read_bytes()
    scored = json.loads((root / "scored-answers.json").read_text())
    report = json.loads((root / "report.json").read_text())
    if (
        hashlib.sha256(raw).hexdigest() != report["raw_journal_sha256"]
        or len(scored) != 48
        or report["all_planned"] != 48
        or len(raw.splitlines()) != 48
    ):
        raise ValueError("sealed reader outcome population incomplete")
    original = [json.loads(line) for line in raw.splitlines()]
    labels = {r["id"]: r for r in json.loads(target_bytes)}
    seen = set()
    checks = 0
    metrics = {arm: dict(success=0, abstained=0, cited_complete=0) for arm in ARMS}
    for case in plan["cases"]:
        query = case["query"]
        if digest(case["candidate_ids"]) != case["candidate_digest"]:
            raise ValueError("candidate pool drift")
        for arm in ARMS:
            index = len(seen)
            actual = original[index]
            scored_row = scored[index]
            selected = list(case["controls"][arm]["selected"])
            key = (query["identity"], arm)
            if key in seen:
                raise ValueError("duplicate question/arm pair")
            seen.add(key)
            expected = answer(query, selected, originals)
            if (actual["question_id"], actual["arm"]) != key or (
                actual["output"] != expected
                or scored_row["output"] != actual["output"]
                or actual["selected"] != selected
                or actual["query_digest"] != digest(query)
                or actual["source_view_sha"] != locked["original_source_sha256"]
                or actual["reader_profile"] != SCHEMA
                or actual["status"] != "succeeded"
            ):
                raise ValueError("original model-free answer or source chain modified")
            target = labels[query["identity"]]
            selected_chain = {t["original_id"] for t in expected["trace"]}
            value = (
                expected["answer"].split(" ")[0]
                if expected["status"] == "answered"
                else None
            )
            success = value == target["expected"]
            all_cited = success and set(target["support"]).issubset(selected_chain)
            if target["kind"] == "procedure":
                if (
                    not (root / "original-event-probe.py").is_file()
                    or file_sha(root / "original-event-probe.py")
                    != locked["original_worker_sha256"]
                ):
                    raise ValueError("program executable differs from pinned original")
                request = dict(
                    operation="execute",
                    recipe=target["procedure"],
                    supplied=value or "invalid_response",
                )
                p = subprocess.run(
                    [sys.executable, "-I", "-S", str(root / "original-event-probe.py")],
                    input=json.dumps(request),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                checks += 1
                recorded_check = scored_row.get("original_program_verification")
                if recorded_check is None or any(
                    recorded_check[field] != v
                    for field, v in (
                        ("exit_code", p.returncode),
                        ("stdout", p.stdout),
                        ("stderr", p.stderr),
                    )
                ):
                    raise ValueError("original program response has changed")
                success = p.returncode == 0
            if (
                scored_row["strict_task_success"] != success
                or scored_row["complete_declared_chain_cited"] != all_cited
                or scored_row["parsed_value"] != value
            ):
                raise ValueError("postscore answer/citation adjudication drift")
            metrics[arm]["success"] += int(success)
            metrics[arm]["cited_complete"] += int(all_cited)
            metrics[arm]["abstained"] += int(expected["status"] == "abstained")
    if (
        len(seen) != 48
        or checks != 12
        or any(
            report["result_by_arm"][arm]["strict_task_success"] != row["success"]
            or report["result_by_arm"][arm]["complete_declared_chain_cited"]
            != row["cited_complete"]
            or report["result_by_arm"][arm]["abstained"] != row["abstained"]
            for arm, row in metrics.items()
        )
    ):
        raise ValueError("reported complete population or program validation drift")
    receipt = dict(
        schema="hepta.memory.local-causal-independent-process-replay.v1",
        generating_commit=source_commit,
        original_source_sha256=ARCHIVE_SHA,
        original_journal_sha256=hashlib.sha256(raw).hexdigest(),
        independently_recomputed_original_answers=48,
        independently_reexecuted_authored_program_cases=12,
        all_citation_chains_recomputed=True,
        reader_type="source-local-controlled-symbolic_parser",
        new_model_calls=0,
        training_steps=0,
        new_source_families=0,
        human_semantic_review=False,
        production_accepted=False,
        outcomes=metrics,
    )
    write(Path(destination), receipt)
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("recorded", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--source-commit", required=True)
    a = p.parse_args()
    print(
        json.dumps(
            audit(a.archive, a.recorded, a.output, source_commit=a.source_commit)
        )
    )
