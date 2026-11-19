"""Actual-reader conformance probe, NOT future-time or procedural efficacy evidence.

Sources and task templates are explicitly authored. Four model calls exercise a
precommitted memory policy and same-reader single/set controls; no cells train.
A real procedural outcome corpus and independent reviews remain separate inputs.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from evidence_bundle import EvidenceBundle, build_windows, select_set
from frozen_memory_session import FrozenMemorySession, freeze, publish
from native import Document, Question, digest


def probe(reader, output, *, source_commit):
    output.mkdir(mode=0o700)
    outcomes = []
    authored = (
        (
            "time",
            (
                "Nera relocated in May 2024.",
                "Nera started training two months before relocating.",
            ),
            "In which month did Nera start training?",
        ),
        (
            "procedure",
            (
                "Zephyr validation uses package zephyr-core.",
                "Zephyr validation needs flag --locked, not --offline.",
            ),
            "Which package and flag are needed for Zephyr validation?",
        ),
    )
    for kind, texts, content in authored:
        scope = "authored-read-probe:" + kind
        documents = tuple(
            Document(f"{scope}/{i}", scope, scope, str(i), "2024-06-01T00:00:00Z", text)
            for i, text in enumerate(texts)
        )
        indexed_at = time.perf_counter()
        spans, index_cost = build_windows(documents)
        index_cost["index_seconds"] = time.perf_counter() - indexed_at
        window_manifest = digest([asdict(s) for s in spans])
        for mode, count in (("ranked", 1), ("coverage", 4)):
            directory = output / (kind + "-" + mode)
            policy = dict(mode=mode, count=count, window_manifest=window_manifest)
            before = time.perf_counter()
            snapshot = freeze(
                directory,
                documents,
                through="2024-06-01T12:00:00Z",
                policy_bytes=json.dumps(policy, sort_keys=True).encode(),
                policy_roots=set(),
                reader_identity=reader.identity,
                source_commit=source_commit,
            )
            write_seconds = time.perf_counter() - before
            # No task object enters freeze or indexing. Templates remain authored,
            # publicly known controls; this ordering is not independent observation.
            query = Question(scope, scope, scope, content, "2024-06-02T00:00:00Z")
            session = FrozenMemorySession(directory, expected_snapshot=snapshot)

            def select(q, docs, frontier, raw_policy, revoked):
                bound = json.loads(raw_policy)
                if bound["window_manifest"] != digest([asdict(s) for s in spans]):
                    raise ValueError("unbound indexed memory view")
                chosen = select_set(q, spans, count=bound["count"], mode=bound["mode"])
                return EvidenceBundle(
                    digest(asdict(q)), frontier, chosen, bound["mode"]
                )

            result = session.answer(query, select, reader, withdrawals=lambda: set())
            reopened = FrozenMemorySession(directory, expected_snapshot=snapshot)
            replayed = reopened.replay(
                query,
                withdrawals=lambda: set(),
                expected_result_sha256=result["result_sha256"],
            )
            if replayed != result:
                raise ValueError("restart changed committed answer")
            blocked = False
            try:
                reopened.replay(
                    query,
                    withdrawals=lambda: {scope},
                    expected_result_sha256=result["result_sha256"],
                )
            except ValueError:
                blocked = True
            if not blocked:
                raise ValueError("old snapshot resurrected a withdrawn source")
            outcomes.append(
                dict(
                    query_id=query.identity,
                    policy=policy,
                    snapshot_sha256=snapshot,
                    result=result,
                    index_cost=index_cost,
                    write_seconds=write_seconds,
                    withheld_replay_rejected=blocked,
                )
            )
    reader.verify_frozen()
    value = dict(
        schema="hepta.frozen-memory.probe.v1",
        source_commit=source_commit,
        provenance="authored_controls_not_observed_task_outcomes",
        results=outcomes,
        model_calls=len(outcomes),
        policy_optimizer_calls=0,
        reader_training=False,
        independent_snapshots=0,
        prospective_windows=0,
        superiority_claim=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
    publish(output / "probe.json", value)
    return value


if __name__ == "__main__":
    from bundle_reader import FrozenBundleReader
    from reviewed_bundle import strict_read

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reader", "inventory", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--inventory-sha", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    inventory = strict_read(args.inventory, args.inventory_sha, 4 * 1024 * 1024)
    reader = FrozenBundleReader(
        args.reader, expected_inventory=inventory["inventory_digest"]
    )
    print(
        json.dumps(
            probe(reader, args.output, source_commit=args.source_commit), indent=2
        )
    )
