"""Constructed standard-library skill tasks with independently authored goldens.

This is a finite instruction-to-operation benchmark, not observed production
traffic or open-ended code synthesis. Expected outputs are fixture constants;
neither inference nor the shared executor reads task labels or expected outputs.
"""

import csv
import hashlib
import io
import json
import unicodedata
from collections import Counter
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SKILLS = (
    "unique_stable", "sort_numeric", "sort_casefold", "count_items",
    "normalize_nfc", "normalize_nfkc", "casefold", "collapse_whitespace",
    "csv_parse", "csv_write", "json_parse", "json_compact",
)
DOMAINS = ("sequence", "text", "serialization")
SKILL_DOMAIN = {skill: DOMAINS[index // 4] for index, skill in enumerate(SKILLS)}
SPLIT_COUNTS = {"train": 10, "calibration": 4, "test": 6}
MAX_PAYLOAD_BYTES = 16_384


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def load_split(split):
    """Load one explicitly requested split; training callers must ask for train.

Each split has independently authored requests and its own raw-payload pool.
Queries are the statistical units; reused payloads are recorded as fixture IDs.
No random seeds generate new language or independent examples.
"""
    if split not in SPLIT_COUNTS:
        raise ValueError("unknown split")
    data = json.loads((ROOT / "task_fixtures.json").read_text(encoding="utf-8"))
    rows = []
    for label, skill in enumerate(SKILLS):
        entry = data[skill]
        queries = entry["queries"][split]
        if len(queries) != SPLIT_COUNTS[split]:
            raise ValueError("wrong query count")
        fixtures = entry["goldens"][split]
        for number, query in enumerate(queries):
            payload, expected = fixtures[number % len(fixtures)]
            identity = hashlib.sha256(canonical([split, query, payload])).hexdigest()
            rows.append(dict(id=identity, split=split, text=query, query=query,
                             label=label, skill=skill, skill_id=skill, domain=SKILL_DOMAIN[skill],
                             payload=payload, expected=expected,
                             fixture_id=f"{skill}:{split}:{number % len(fixtures)}"))
    return rows


def skill_catalog():
    """Public operation descriptions available equally to every comparison arm."""
    data = json.loads((ROOT / "task_fixtures.json").read_text(encoding="utf-8"))
    return [dict(id=f"public-registry:{skill}", split="registry", label=label,
                 skill=skill, skill_id=skill, domain=SKILL_DOMAIN[skill],
                 text=data[skill]["description"], query=data[skill]["description"])
            for label, skill in enumerate(SKILLS)]


def public_input(row):
    """The entire permitted inference input, with oracle metadata removed."""
    return {"text": row["text"], "payload": json.loads(json.dumps(row["payload"]))}


def _text(value):
    if not isinstance(value, str):
        raise TypeError("operation requires text")
    return value


def _strings(value):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise TypeError("operation requires a list of strings")
    return value


def execute(skill, payload):
    """Run the chosen registered operation on the actual caller payload.

The skill vocabulary/semantics are public and identical for every method. The
classifier supplies only a skill ID. This function never sees an example row,
query, expected label, project name, or corpus. Exceptions count as failed use.
"""
    if isinstance(skill, int) and not isinstance(skill, bool):
        if not 0 <= skill < len(SKILLS):
            raise ValueError("unknown operation")
        skill = SKILLS[skill]
    if len(canonical(payload)) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds bounded experiment limit")
    if skill == "unique_stable":
        return list(dict.fromkeys(_strings(payload)))
    if skill == "sort_numeric":
        values = _strings(payload)
        keys = [Decimal(value) for value in values]
        if any(not key.is_finite() for key in keys):
            raise ValueError("finite numbers required")
        return [value for _, value in sorted(enumerate(values), key=lambda p: keys[p[0]])]
    if skill == "sort_casefold":
        return sorted(_strings(payload), key=str.casefold)
    if skill == "count_items":
        return dict(Counter(_strings(payload)))
    if skill in ("normalize_nfc", "normalize_nfkc"):
        form = "NFC" if skill == "normalize_nfc" else "NFKC"
        return unicodedata.normalize(form, _text(payload))
    if skill == "casefold":
        return _text(payload).casefold()
    if skill == "collapse_whitespace":
        return " ".join(_text(payload).split())
    if skill == "csv_parse":
        return list(csv.reader(io.StringIO(_text(payload), newline=""), strict=True))
    if skill == "csv_write":
        if not isinstance(payload, list):
            raise TypeError("CSV writer requires rows")
        rows = [_strings(row) for row in payload]
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\n").writerows(rows)
        return stream.getvalue()
    if skill == "json_parse":
        return json.loads(_text(payload))
    if skill == "json_compact":
        return json.dumps(json.loads(_text(payload)), ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)
    raise ValueError("unknown operation")


def score_prediction(row, predicted_skill):
    """Evaluator-only boundary: score execution, distinct from class accuracy."""
    skill = (SKILLS[predicted_skill] if isinstance(predicted_skill, int)
             and not isinstance(predicted_skill, bool)
             and 0 <= predicted_skill < len(SKILLS) else predicted_skill)
    try:
        output = execute(skill, row["payload"])
        error = None
        correct = canonical(output) == canonical(row["expected"])
    except (ValueError, TypeError, ArithmeticError, csv.Error, OverflowError) as exc:
        output, error, correct = None, type(exc).__name__, False
    return dict(output=output, error=error, correct=correct,
                label_correct=skill == row["skill"], predicted_skill=skill)


def composition_cases():
    """Held-out compositions with explicit public step decomposition.

No model learns from these cases. This measures composing selected skills, not
discovering a plan from an unsegmented instruction. Goldens are hand-authored.
"""
    return json.loads((ROOT / "composition_fixtures.json").read_text(encoding="utf-8"))


def execute_composition(case, predict):
    """predict(text) selects every operation without receiving oracle labels."""
    value = case["payload"]
    trace = []
    for text in case["steps"]:
        predicted = predict(text)
        if isinstance(predicted, tuple):
            predicted = predicted[0]
        try:
            value = execute(predicted, value)
            trace.append({"prediction": predicted, "output": value, "error": None})
        except (ValueError, TypeError, ArithmeticError, csv.Error) as exc:
            trace.append({"prediction": predicted, "error": type(exc).__name__})
            return {"correct": False, "trace": trace, "output": None}
    return {"correct": canonical(value) == canonical(case["expected"]),
            "trace": trace, "output": value}


def profile_journal():
    """Ordered constructed observations; policy text is legitimate new input."""
    declarations = [
        (1, "amber", 1, "Keep just the first occurrence of each listed item."),
        (2, "birch", 1, "Compose canonical Unicode sequences while preserving compatibility characters."),
        (3, "cobalt", 1, "Decode the JSON document into structured values."),
        (4, "amber", 2, "Order the textual numbers from the smallest value to the largest."),
        (5, "birch", 2, "Fold compatibility Unicode forms and compose the result."),
        (6, "cobalt", 2, "Return compact JSON text without optional formatting whitespace."),
    ]
    rows = []
    targets = ("unique_stable", "normalize_nfc", "json_parse",
               "sort_numeric", "normalize_nfkc", "json_compact")
    for (sequence, project, revision, policy), target in zip(declarations, targets):
        event = dict(sequence=sequence, project=project, revision=revision, policy=policy,
                     operation_id=target,
                     source=f"constructed-project-policy/{project}/{revision}")
        event["digest"] = hashlib.sha256(canonical(event)).hexdigest()
        rows.append(event)
    return rows


def profile_learning_split(split, frontier):
    """Arbitrary new bindings learned only from legal journal-frontier sources.

Requests mention a project but never its current operation or policy text.
Labels are sourced from the declared journal operation_id; output goldens are
authored separately for each version. All frontiers are evaluation snapshots,
not new independently sampled tasks. Model callers receive public_input only.
"""
    if split not in SPLIT_COUNTS or frontier not in (3, 4, 5, 6):
        raise ValueError("invalid profile split or frontier")
    data = json.loads((ROOT / "profile_fixtures.json").read_text(encoding="utf-8"))
    rows = []
    for project, entry in data.items():
        event = resolve_profile(profile_journal(), project, frontier)
        skill = event["operation_id"]
        goldens = entry["goldens"][split]
        for index, query in enumerate(entry["queries"][split]):
            fixture = goldens[index % len(goldens)]
            expected = fixture["by_revision"][str(event["revision"])]
            identity = hashlib.sha256(canonical(["profile", split, query,
                                                 fixture["payload"], frontier])).hexdigest()
            rows.append(dict(id=identity, split=split, text=query, query=query,
                             project=project, frontier=frontier, label=SKILLS.index(skill),
                             skill=skill, skill_id=skill, domain=SKILL_DOMAIN[skill],
                             payload=fixture["payload"], expected=expected,
                             source_digest=event["digest"], source_revision=event["revision"],
                             fixture_id=f"{project}:{split}:{index % len(goldens)}"))
    return rows


def resolve_profile(journal, project, as_of):
    """Read only observations available at the requested logical frontier."""
    eligible = [row for row in journal if row["project"] == project
                and row["sequence"] <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row["sequence"])


def profile_cases():
    """Initial, corrected, and retained project rules; private evaluator labels."""
    definitions = {
        "amber": (["8", "2", "8", "-1"],
                  [("unique_stable", ["8", "2", "-1"]),
                   ("sort_numeric", ["-1", "2", "8", "8"])]),
        "birch": ("Ａ Cafe\u0301 ①",
                  [("normalize_nfc", "Ａ Café ①"), ("normalize_nfkc", "A Café 1")]),
        "cobalt": ('{ "ok" : true, "values" : [ 3, 1 ] }',
                   [("json_parse", {"ok": True, "values": [3, 1]}),
                    ("json_compact", '{"ok":true,"values":[3,1]}')]),
    }
    rows = []
    for frontier in (3, 4, 5, 6):
        for index, (project, (payload, alternatives)) in enumerate(definitions.items()):
            skill, expected = alternatives[int(frontier >= 4 + index)]
            rows.append(dict(id=f"profile:{frontier}:{project}", project=project,
                             as_of=frontier, text=f"Process this payload under the current {project} project rule.",
                             payload=payload, expected=expected, skill=skill))
    return rows


def profile_input(case, journal):
    """Same current-source information may be consumed by any compared method."""
    frontier = case.get("as_of", case.get("frontier"))
    if frontier is None:
        raise ValueError("profile request has no source frontier")
    event = resolve_profile(journal, case["project"], frontier)
    if event is None:
        return None
    return {"text": f"Current project rule: {event['policy']}\nRequest: {case['text']}",
            "payload": case["payload"], "source_digest": event["digest"],
            "source_revision": event["revision"]}


def fixture_manifest():
    """Hash source before any training or holdout prediction is admitted."""
    names = ("tasks.py", "baselines.py", "TASK_PROTOCOL.json", "task_fixtures.json",
             "composition_fixtures.json", "profile_fixtures.json")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
