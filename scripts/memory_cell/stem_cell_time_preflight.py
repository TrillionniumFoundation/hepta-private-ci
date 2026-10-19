"""Source-only chronology census, without targets, models or generated answers.

A native timestamp parser can flag uncertainty or actual future histories; it
cannot retroactively repair published policy outputs or authenticate chronology.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from native import digest, load
from stem_cell_time import source_not_after_question


def native_chronology(sources):
    reports = {}
    for name, benchmark in sorted(sources.items()):
        by_scope = defaultdict(list)
        for document in benchmark.documents:
            by_scope[document.scope].append(document)
        observable = {}
        for question in benchmark.questions:
            observable.setdefault((question.scope, question.observed_at), question)
        outcomes = Counter()
        examples = {"unknown": [], "future": []}
        for (scope, _), question in sorted(observable.items()):
            for doc in by_scope[scope]:
                try:
                    admitted = source_not_after_question(
                        doc.observed_at, question.observed_at
                    )
                    status = "not-future" if admitted else "future"
                except ValueError:
                    status = "unknown"
                outcomes[status] += 1
                if status in examples and len(examples[status]) < 32:
                    examples[status].append(
                        digest(
                            (
                                benchmark.source_sha256,
                                question.identity,
                                doc.identity,
                                question.observed_at,
                                doc.observed_at,
                            )
                        )
                    )
        reports[name] = dict(
            unique_scope_question_timestamp_pairs=len(observable),
            source_observation_checks=sum(outcomes.values()),
            accepted=outcomes["not-future"],
            future=outcomes["future"],
            unknown=outcomes["unknown"],
            example_identity_digests=examples,
            declared_source_sha256=benchmark.source_sha256,
            no_target_annotations_inspected=True,
        )
    return dict(
        schema="hepta.stem-native-chronology.v1",
        datasets=reports,
        all_observations_comparable_and_nonfuture=all(
            d["future"] == d["unknown"] == 0 for d in reports.values()
        ),
        production_chronology_qualified=False,
        actual_future_window_count=0,
    )


def main(staged: Path, output: Path):
    stage_info = json.loads((staged / "staging.json").read_text())
    benchmarks = {
        name: load(
            staged / f"{name}.json",
            name,
            stage_info[name]["sha256"],
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
            empty_turns="preserve",
        )
        for name in ("locomo", "longmemeval")
    }
    report = native_chronology(benchmarks)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.staged, args.output)
