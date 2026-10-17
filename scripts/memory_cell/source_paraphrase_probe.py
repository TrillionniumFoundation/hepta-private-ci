"""Source-derived, untrained-query paraphrase probe (NOT independent holdout).

Only transform the already registered source-only writer QUESTION template. The
training target and all future evaluation plans are not read by this function.
Preserve exactly the original scope, family, timestamp and source ancestry.
"""

from dataclasses import replace
import re

from native import Question, digest

MODE = "source_paraphrase_v1"
PREFIX = "At logical revision "
MIDDLE = ", what is the recorded "
RELATION = " identifier of "
SUFFIX = "? Return only its value."


def paraphrase_writer_question(example: dict) -> Question:
    """Rephrase a controlled source-only prompt without inspecting its label.

    A novel surface form for an in-training fact is NOT new knowledge, an
    independent family, or a human-certified semantic paraphrase.
    """
    if not isinstance(example, dict) or not isinstance(example.get("query"), dict):
        raise ValueError("source-only writer question required")
    q = Question(**example["query"])
    if (
        not q.content.startswith(PREFIX)
        or not q.content.endswith(SUFFIX)
        or len(q.content.encode("utf-8")) > 2048
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in q.content)
    ):
        raise ValueError("unrecognized or unsafe writer prompt")
    middle = q.content[len(PREFIX) : -len(SUFFIX)]
    version, separator, statement = middle.partition(MIDDLE)
    if not separator or not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})", version):
        raise ValueError("missing explicit writer revision")
    revision = int(version)
    relation, marker, entity = statement.rpartition(RELATION)
    if (
        revision > 10000
        or not marker
        or not relation
        or not entity
        or RELATION in relation
        or RELATION in entity
        or not all(x.isprintable() for x in (relation, entity))
        or len(relation.encode()) > 128
        or len(entity.encode()) > 256
    ):
        raise ValueError("unambiguous bounded source relation required")
    content = (
        f"For entity {entity}, state the {relation} identifier valid at "
        f"logical revision {revision}. Output only the identifier."
    )
    if content == q.content:
        raise ValueError("not a new question wording")
    return replace(
        q,
        identity="source_paraphrase_" + digest((MODE, q.identity, content)),
        content=content,
    )
