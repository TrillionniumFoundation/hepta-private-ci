"""Fixed historical-prefix scale probes; no held-out performance selection."""

import time

from cohort_contract import file_sha
from retrieval_index import Retriever, build


def probe(output, documents, requests, levels, cutoff):
    results = []
    total_read, total_write = 0, 0
    for count in sorted(set(levels)):
        path = output / f"scale-{count}.sqlite3"
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        receipt = build(path, documents[:count], train_until=cutoff)
        reader = Retriever(path)
        rows = [reader.query(request) for request in requests]
        reader.close()
        actual = dict(
            documents=count,
            source_bytes=sum(len(r["text"].encode()) for r in documents[:count]),
            active_index_bytes=path.stat().st_size,
            index_sha256=file_sha(path),
            wall_ns=time.perf_counter_ns() - started,
            cpu_ns=time.process_time_ns() - cpu,
            queries=[
                dict(
                    task_id=r["task_id"],
                    documents=[x["document"]["doc_id"] for x in r["results"]],
                    wall_ns=r["wall_ns"],
                    cpu_ns=r["cpu_ns"],
                )
                for r in rows
            ],
            source_prefix_not_independent_task_groups=True,
            retained_after_trial=False,
        )
        results.append(actual)
        total_read += (
            receipt["source_bytes"]
            + actual["active_index_bytes"]
            + sum(r["source_bytes_returned"] for r in rows)
        )
        total_write += actual["active_index_bytes"]
        # The fixed scale probe has ended; its exact index hash/size is retained.
        # The complete full-corpus serving index remains separately present.
        path.unlink()
    return dict(levels=results, extrapolation_beyond_observed_75_documents=False), dict(
        read_bytes=total_read, write_bytes=total_write
    )
