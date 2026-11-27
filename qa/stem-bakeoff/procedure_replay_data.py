"""Predeclared artificial task language and disjoint input-file families.

This is instruction-to-existing-procedure selection, not program synthesis.
Public queries exclude the goal, observed labels and output bytes. Each input
family is crossed with every procedure, so file structure cannot identify the
answer. No template or input family crosses a dataset partition.
"""

from dataclasses import dataclass
import random

from procedure_replay_contracts import CONTRACTS, canonical, sha


TEMPLATES = (
    (
        "Keep only the last occurrence for each id, then order by id.",
        "Remove earlier versions of repeated identifiers; list the final records by identifier.",
        "For every id select its final appearance in the input, sorting those ids alphabetically.",
        "Deduplicate identifiers using the last record as the winner and present id order.",
        "An id may appear repeatedly: retain its last entry, with identifiers in sorted order.",
        "Replace earlier records with the final record of the same id; arrange the surviving ids.",
        "Resolve repeated ids in favor of the later input occurrence and sort by identifier.",
        "Produce one record per id using the final occurrence, listed in ascending id order.",
        "Build the final version view: later entries supersede earlier entries sharing an id.",
        "For each identifier, discard every appearance except the last; return identifier order.",
        "Use last-write-wins on ids, then enumerate the surviving records lexically by id.",
        "Collapse repeat identifiers to their final input record and sort the identifier keys.",
    ),
    (
        "Sum all scores for each group and list the groups in order.",
        "Aggregate scores by group, returning one total for every group alphabetically.",
        "Add every score within each group and emit sorted group totals.",
        "Produce a per-group sum of scores, including duplicate records in the total.",
        "Group the records and calculate their score sums, listing groups alphabetically.",
        "Return group totals by adding all associated scores and sorting the group names.",
        "Accumulate the score column separately for each group, ordered by group.",
        "Report the sum belonging to each group rather than the individual records.",
        "Prepare a subtotal table: one row per group with its combined score.",
        "Roll scores up into group-level totals and enumerate the groups lexically.",
        "Combine the numeric scores sharing a group into one sum for that group.",
        "Make a grouped accounting summary whose totals include every input record.",
    ),
    (
        "Keep records whose score reaches the cutoff, preserving their original order.",
        "Filter out scores below the threshold; retain qualifying duplicates and input order.",
        "Select all records with score greater than or equal to the threshold without reordering.",
        "Drop low scores below the cutoff while leaving the remaining sequence unchanged.",
        "Return entries meeting the inclusive score threshold in their input sequence.",
        "Exclude records under the cutoff and preserve the order of every retained record.",
        "Keep score values at least the threshold, including ties and repeated identifiers.",
        "Apply the score cutoff inclusively, retaining the original relative order.",
        "Prune scores that do not reach the minimum; otherwise leave each entry in place.",
        "Only qualifying scores should remain: equality with the cutoff is sufficient.",
        "Reject entries strictly below the minimum score, keeping the other entries unchanged.",
        "Use the threshold as a lower bound and emit the accepted records in source order.",
    ),
    (
        "Sort every record by increasing score, preserving the order of tied scores.",
        "Reorder all records from lowest score to highest; ties keep their input order.",
        "Apply a stable ascending score sort without dropping any duplicates.",
        "Rank the entire input by score in increasing order, leaving ties stable.",
        "Arrange all entries by ascending numeric score and keep equal scores in their old order.",
        "Return a stable score ordering from small to large, retaining every input record.",
        "Put the smallest score first and the largest last; preserve source order among ties.",
        "Order the full list by score ascending without deduplicating or filtering.",
        "Make a low-to-high score ranking of the complete record list with stable ties.",
        "Place records into increasing score order without losing entries or disturbing equal scores.",
        "Produce an ascending numeric ordering of all scores and keep duplicate entries.",
        "Rearrange the records so scores never decrease; preserve input order for equal values.",
    ),
)
SPLITS = {"train": (0, 1, 2, 3), "calibration": (4, 5),
          "development": (6, 7), "heldout": (8, 9, 10, 11)}
DATA_SEED = 43017


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    split: str
    template_family: str
    input_family: str
    source_group_id: str
    input_sha256: str


@dataclass(frozen=True)
class Case:
    query: Query
    input_bytes: bytes
    goal: str


def make_cases():
    cases = []
    for split, template_ids in SPLITS.items():
        for template_id in template_ids:
            for variant in range(4):
                family = f"file-family-{template_id:02d}-{variant}"
                rng = random.Random(DATA_SEED + 101 * template_id + 17 * variant)
                threshold = rng.randrange(-3, 7)
                count = 8 + template_id + variant
                ids = [f"item-{template_id:02d}-{variant}-{n}" for n in range(4)]
                groups = [f"bucket-{template_id:02d}-{variant}-{n}" for n in range(3)]
                rows = [{"id": ids[n % 4], "group": groups[(n + variant) % 3],
                         "score": threshold + rng.randrange(-6, 7), "note": f"event-{n}"}
                        for n in range(count)]
                # Distinguishing edge cases are part of every frozen family:
                # a below-cutoff row, an above-cutoff row, exact ties, repeated ids.
                rows[0]["score"], rows[1]["score"] = threshold + 5, threshold - 5
                rows[2]["score"] = rows[3]["score"] = threshold
                raw = canonical({"records": rows, "threshold": threshold}) + b"\n"
                for contract, templates in zip(CONTRACTS, TEMPLATES):
                    text = (templates[template_id] + f" Input data.json has {count} records; "
                            f"the threshold is {threshold}. Write output.json without changing data.json.")
                    query_id = sha(canonical([family, text]))[:24]
                    query = Query(query_id, text, split, f"template-family-{template_id:02d}",
                                  family, family, sha(raw))
                    cases.append(Case(query, raw, contract["id"]))
    return tuple(sorted(cases, key=lambda case: case.query.query_id))


def validate_partitions(cases):
    seen_templates, seen_inputs, seen_queries, seen_files = set(), set(), set(), set()
    counts = {}
    for split in SPLITS:
        rows = [case for case in cases if case.query.split == split]
        templates = {case.query.template_family for case in rows}
        inputs = {case.query.input_family for case in rows}
        texts = {case.query.text for case in rows}
        files = {case.query.input_sha256 for case in rows}
        if (seen_templates & templates or seen_inputs & inputs or seen_queries & texts
                or seen_files & files or len(texts) != len(rows)):
            raise ValueError("template, source-file or query overlap between partitions")
        seen_templates |= templates
        seen_inputs |= inputs
        seen_queries |= texts
        seen_files |= files
        counts[split] = {"queries": len(rows), "template_families": len(templates),
                         "input_file_families": len(inputs)}
    return counts
