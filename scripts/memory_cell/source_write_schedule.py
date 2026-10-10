"""Exact source-only write schedule; planned exposure is not learned knowledge.

The planner preserves the existing scope-round-robin order and stops before a
partial example. Its CLI uses the pinned tokenizer and original source corpus,
without loading model weights, reading evaluation tasks or running an optimizer.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from native import Document, Question, digest


def schedule(prepared, groups, *, maximum_steps, token_ceiling):
    if (
        type(maximum_steps) is not int
        or not 1 <= maximum_steps <= 128
        or type(token_ceiling) is not int
        or not 1 <= token_ceiling <= 65536
        or not 1 <= len(prepared) <= 2048
        or not isinstance(groups, dict)
        or not groups
    ):
        raise ValueError("bounded source schedule required")
    for scope, indices in groups.items():
        if (
            not isinstance(scope, str)
            or not scope
            or len(scope.encode()) > 1024
            or not isinstance(indices, (list, tuple))
            or not indices
            or any(type(i) is not int or not 0 <= i < len(prepared) for i in indices)
        ):
            raise ValueError("bounded explicit scope and example indices required")
    members = [i for indices in groups.values() for i in indices]
    if sorted(members) != list(range(len(prepared))):
        raise ValueError("every source example belongs to exactly one scope")
    lengths, supervised = [], []
    for ids, labels in prepared:
        if (
            not 1 <= len(ids) <= 2112
            or len(ids) != len(labels)
            or any(type(i) is not int or not 0 <= i < 2**31 for i in ids)
            or any(
                type(v) is not int or v not in (-100, i) for i, v in zip(ids, labels)
            )
            or not any(v != -100 for v in labels)
        ):
            raise ValueError("complete finite-token completion example required")
        lengths.append(len(ids))
        supervised.append(sum(v != -100 for v in labels))
    scopes = sorted(groups)
    entries, visits, tokens, targets = [], [0] * len(prepared), 0, 0
    stopped = "maximum_steps"
    for step in range(maximum_steps):
        group = groups[scopes[step % len(scopes)]]
        index = group[(step // len(scopes)) % len(group)]
        if tokens + lengths[index] > token_ceiling:
            stopped = "token_ceiling_before_next_example"
            break
        entries.append(index)
        visits[index] += 1
        tokens += lengths[index]
        targets += supervised[index]
    return dict(
        schema="hepta.source-write.schedule.v1",
        prepared_digest=digest(prepared),
        groups_digest=digest(groups),
        scopes=scopes,
        entries=entries,
        maximum_steps=maximum_steps,
        token_ceiling=token_ceiling,
        planned_steps=len(entries),
        planned_input_tokens=tokens,
        planned_supervised_tokens=targets,
        visits_per_example=visits,
        unvisited_examples=[i for i, n in enumerate(visits) if n == 0],
        stop_reason=stopped,
        actual_optimizer_steps=0,
        coverage_is_not_task_success=True,
    )


def prepare(tokenizer, examples, *, maximum_steps, token_ceiling):
    from experience_memory import render
    from grounded_protocol import completion_ids

    prepared, groups = [], {}
    for example in examples:
        query = Question(**example["query"])
        prompt = render(tokenizer, query, [], [])
        ids, labels = completion_ids(tokenizer, prompt, example["target"], maximum=2112)
        groups.setdefault(query.scope, []).append(len(prepared))
        prepared.append((ids, labels))
    return prepared, schedule(
        prepared, groups, maximum_steps=maximum_steps, token_ceiling=token_ceiling
    )


def preflight(sources, output, *, source_sha):
    from huggingface_hub import HfApi, snapshot_download
    from transformers import AutoTokenizer
    from bundle_trial import write
    from event_memory_trial import read
    from experience_memory import PROFILE, STEPS, TOKEN_CEILING, source_examples
    from reader_reference import MODELS, catalogue, verify_files

    started = time.perf_counter()
    documents = tuple(
        Document(**(d | {"assets": tuple(d["assets"])}))
        for d in read(sources, source_sha)
    )
    examples, dispositions = source_examples(
        documents,
        revision=2,
        allowed_roots={d.root for d in documents},
        revoked=set(),
    )
    output.mkdir()
    repository, revision = MODELS["qwen-3b"]
    entries = catalogue(
        HfApi().model_info(
            repository, revision=revision, files_metadata=True, token=False
        ),
        revision,
    )
    names = {"tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"}
    selected = {n: value for n, value in entries.items() if n in names}
    if (
        set(selected) != names
        or sum(v["bytes"] for v in selected.values()) > 32 * 1024**2
    ):
        raise ValueError("complete bounded pinned tokenizer required")
    write(
        output / "publisher.json",
        dict(repository=repository, revision=revision, files=selected),
    )
    snapshot_download(
        repository,
        revision=revision,
        allow_patterns=sorted(names),
        local_dir=output / "tokenizer",
        token=False,
        max_workers=2,
    )
    verify_files(output / "tokenizer", selected)
    tokenizer = AutoTokenizer.from_pretrained(
        output / "tokenizer", local_files_only=True, trust_remote_code=False
    )
    _, plan = prepare(
        tokenizer, examples, maximum_steps=STEPS, token_ceiling=TOKEN_CEILING
    )
    result = dict(
        schema="hepta.source-write.preflight.v1",
        writer_profile=PROFILE,
        source_sha256=source_sha,
        source_documents_digest=digest([asdict(d) for d in documents]),
        tokenizer_repository=repository,
        tokenizer_revision=revision,
        tokenizer_files_digest=digest(selected),
        source_events=len(documents),
        source_examples=len(examples),
        source_example_ids=[r["query"]["identity"] for r in examples],
        source_supervision_digest=digest(examples),
        unresolved_source_facts=dispositions,
        schedule=plan,
        schedule_sha256=digest(plan),
        measured_preflight_seconds=time.perf_counter() - started,
        model_weights_loaded=False,
        evaluation_task_inputs_consumed=False,
        independent_future_cohort=False,
        production_accepted=False,
    )
    write(output / "preflight.json", result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    preflight(args.sources, args.output, source_sha=args.source_sha)
