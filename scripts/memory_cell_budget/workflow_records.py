"""Automatic source-only short-command records; never a repair-label dataset."""

from collections import Counter
import math
import random
import re
import shlex

from budget_ledger import digest
from retrieval_index import tokens


SCOPE = "workflow-source-20261016"
TRAIN_TEMPLATES = [
    "For {entity}, return the stored {relation}.",
    "Recall {relation} for {entity}.",
]
FINAL_TEMPLATE = "What is the {relation} recorded at {entity}?"
CONTROL = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "for",
    "while",
    "do",
    "done",
    "case",
    "esac",
    "set",
    "export",
    "echo",
    "printf",
    "cd",
    "exit",
    "return",
    "true",
    "false",
}


def direct_command(text):
    """Only a complete short, single command; no expansion or shell program."""
    text = text.strip()
    if not 1 <= len(text.encode()) <= 64 or re.search(r"[\n\r;$|&<>`(){}]", text):
        return None
    try:
        argv = shlex.split(text)
    except ValueError:
        return None
    if (
        not argv
        or argv[0] in CONTROL
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", argv[0]) is None
    ):
        return None
    return dict(text=text, argv=argv)


def extract(documents):
    """Inspect every YAML run block; select by source hash, without final inputs.

    This is a deliberately narrow lexical extractor, not a general YAML evaluator.
    The exact source line and its parent document remain in each retained record.
    """
    records = []
    for document in documents:
        lines = document["text"].splitlines()
        step, index = "unnamed-step", 0
        while index < len(lines):
            line = lines[index]
            named = re.match(r"^\s*-\s+name:\s*(.*)$", line)
            if named:
                step = named[1].strip("\"'")
            run = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*?)\s*$", line)
            if not run:
                index += 1
                continue
            indent, value = len(run[1]), run[2]
            candidates = [(index + 1, value.strip("\"'"))]
            if value in ("|", "|-", "|+", ">", ">-", ">+"):
                candidates = []
                following = index + 1
                while following < len(lines):
                    current = lines[following]
                    if (
                        current.strip()
                        and len(current) - len(current.lstrip()) <= indent
                    ):
                        break
                    candidates.append((following + 1, current.strip()))
                    following += 1
            heredoc = None
            for number, candidate in candidates:
                if heredoc:
                    if candidate.strip() == heredoc:
                        heredoc = None
                    continue
                marker = re.search(
                    r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", candidate
                )
                if marker:
                    heredoc = marker[1]
                    continue
                parsed = direct_command(candidate)
                if parsed is None:
                    continue
                source = dict(
                    document_sha256=document["source_sha256"],
                    path=document["path"],
                    line=number,
                    command=parsed["text"],
                    origin=document["origin"],
                )
                identity = digest(source)
                entity = f"{document['path'].rsplit('/', 1)[-1]} line {number}"
                records.append(
                    dict(
                        record_id=identity,
                        group_id=document["group_id"],
                        entity=entity,
                        relation="command",
                        value=parsed["text"],
                        source_digest=identity,
                        scope=SCOPE,
                        source=source,
                        source_step_name=step,
                        feature_text=document["path"]
                        + " "
                        + step
                        + " "
                        + parsed["text"],
                    )
                )
            index += 1
    unique = {r["record_id"]: r for r in records}
    return sorted(unique.values(), key=lambda r: r["record_id"])


def facts(records):
    return [
        {k: r[k] for k in ("scope", "entity", "relation", "value", "source_digest")}
        for r in records
    ]


def source_partitions(records, seed=4731):
    """Whole-workflow shards from source lexical cosine versus seeded random.

    No decoder outcome, repair label, task text, or held-out group enters either.
    These source-document groups are not independent natural task groups.
    """
    groups = sorted({r["group_id"] for r in records})
    if len(groups) < 2:
        raise ValueError("at least two historical workflows required for a split")
    vectors = {}
    for group in groups:
        counts = Counter(
            tokens(
                " ".join(r["feature_text"] for r in records if r["group_id"] == group)
            )
        )
        norm = math.sqrt(sum(v * v for v in counts.values()))
        vectors[group] = {k: v / norm for k, v in counts.items()}
    cosine = lambda a, b: sum(v * vectors[b].get(k, 0) for k, v in vectors[a].items())
    first = groups[0]
    second = min(groups, key=lambda g: (cosine(first, g), g))
    ordered = sorted(groups, key=lambda g: (cosine(g, first) - cosine(g, second), g))
    shuffled = list(groups)
    random.Random(seed).shuffle(shuffled)
    result = {}
    for name, ordering in (("data_split", ordered), ("random_split", shuffled)):
        selected = set(ordering[: len(ordering) // 2])
        slots = [int(r["group_id"] in selected) for r in records]
        result[name] = dict(
            slots=slots,
            group_slots={g: int(g in selected) for g in groups},
            method="source_lexical_cosine_balanced_groups"
            if name == "data_split"
            else "source_seeded_random_balanced_groups",
            sizes=[slots.count(0), slots.count(1)],
            final_inputs_used=False,
        )
    return result


def source_protocol():
    return dict(
        schema="hepta.workflow-source.commands.v1",
        extraction="all historical workflow run blocks; complete short direct commands only",
        source_order="ascending SHA256(source document identity, exact line and command)",
        selection="first 128 source records with value 1..15 tokenizer tokens and complete training prompts <=192 tokens",
        tokenizer_filter_before_any_training=True,
        dropped_records_receipted=True,
        templates=TRAIN_TEMPLATES,
        final_template=FINAL_TEMPLATE,
        heldout_wording_records="first 16 admitted source records by source hash; known facts, not independent tasks",
        shared_parent_updates=32,
        per_arm_additional_updates=96,
        single=dict(rank=4, updates=96),
        expanded=dict(
            from_rank=4,
            to_rank=8,
            expansion="verified zero-new-B function-preserving copy",
            updates=96,
        ),
        data_split=dict(
            ranks=[4, 4],
            updates=[48, 48],
            partition="source lexical cosine whole-workflow groups",
        ),
        random_split=dict(ranks=[4, 4], updates=[48, 48], partition_seed=4731),
        learning_rate=0.001,
        seed=2718,
        objective="completion_ce",
        router="fixed source-centroid cosine dispatch; no final outcomes, no learned edge or decoder-utility claim",
        natural_questions="original failure excerpts in a request for one short shell command; 192-token contract retained; overlength input rejected, never silently truncated",
        task_success="only approved command execution followed by original gate exit; recall exact match does not count as repair",
    )
