"""Actual 75-workflow BM25, input-only hints, storage codecs and bounded load."""

import argparse
from collections import Counter
import hashlib
import json
import lzma
from pathlib import Path
import re
import resource
import time
import zlib

from budget_ledger import digest
from cohort_contract import file_sha, retain, validate_seal
from model_budget import inventory, ledger_for
from retrieval_index import Retriever, build, tokens
from retrieval_scale import probe
from workflow_records import direct_command, extract


def input_only(request):
    candidates = re.findall(
        r"(?:run|execute)\s+['`]([^'`\n]+)['`]", request["text"], flags=re.I
    )
    return next((c for c in candidates if direct_command(c)), None)


def source_proposal(request, result):
    query = Counter(tokens(request["text"] + " " + " ".join(request["paths"])))
    candidates = []
    for rank, entry in enumerate(result["results"]):
        for row in extract([entry["document"]]):
            score = sum(query[t] for t in set(tokens(row["feature_text"])))
            candidates.append((-score, rank, row["record_id"], row["value"]))
    return sorted(candidates)[0][3] if candidates else None


def measured(ledger, event, phase, upper, request, function):
    ledger.reserve(event, phase, upper, request_sha256=digest(request))
    clock, cpu = time.perf_counter_ns(), time.process_time_ns()
    value, counts = function()
    actual = dict(
        counts,
        wall_ns=time.perf_counter_ns() - clock,
        cpu_ns=time.process_time_ns() - cpu,
    )
    receipt = dict(value=value, actual=actual, request_sha256=digest(request))
    ledger.settle(event, actual, receipt_sha256=digest(receipt))
    return receipt


def run(study, output):
    validate_seal(study)
    protocol = json.loads((study / "protocol.json").read_text())
    documents = json.loads((study / "source-documents.json").read_text())
    requests = json.loads((study / "requests.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    ledger = ledger_for(
        output / "budget.sqlite3",
        "retrieval",
        protocol,
        file_sha(study / "protocol.json"),
    )
    index = output / "retrieval.sqlite3"

    def make_index():
        value = build(index, documents, train_until=protocol["source_cutoff"])
        return value, dict(
            read_bytes=value["source_bytes"], write_bytes=index.stat().st_size
        )

    built = measured(
        ledger,
        "index",
        "index",
        dict(
            wall_ns=30 * 10**9,
            cpu_ns=30 * 10**9,
            read_bytes=2 * 1024**2,
            write_bytes=32 * 1024**2,
        ),
        {"source": file_sha(study / "source-documents.json")},
        make_index,
    )
    retain(output / "index-receipt.json", built)
    retriever = Retriever(index)
    outputs, no_memory, proposals = {}, {}, {}

    def query_once():
        for request in requests:
            result = retriever.query(request)
            outputs[request["task_id"]] = result
            no_memory[request["task_id"]] = input_only(request)
            proposals[request["task_id"]] = source_proposal(request, result)
        return dict(outputs=outputs, input_only=no_memory, proposals=proposals), dict(
            read_bytes=sum(v["source_bytes_returned"] for v in outputs.values())
        )

    queried = measured(
        ledger,
        "initial-queries",
        "infer",
        dict(wall_ns=30 * 10**9, cpu_ns=30 * 10**9, read_bytes=4 * 1024**2),
        requests,
        query_once,
    )
    retain(output / "retrieval-outputs.json", queried)
    retain(output / "input-only-predictions.json", no_memory)
    retain(output / "retrieval-predictions.json", proposals)
    retain(
        output / "predictions-frozen.json",
        dict(
            frozen_at_ns=time.time_ns(),
            files={
                p.name: file_sha(p)
                for p in (
                    output / "input-only-predictions.json",
                    output / "retrieval-predictions.json",
                    output / "retrieval-outputs.json",
                )
            },
            final_gold_read=False,
        ),
    )
    retriever.close()
    load_rows = []
    repeats = protocol["continuous_load"]["repetitions_per_task"]

    def load_test():
        reader = None
        for index_number in range(repeats * len(requests)):
            if index_number % protocol["continuous_load"]["reopen_every"] == 0:
                if reader:
                    reader.close()
                reader = Retriever(index)
            request = requests[index_number % len(requests)]
            result = reader.query(request)
            load_rows.append(
                dict(
                    sequence=index_number,
                    task_id=request["task_id"],
                    wall_ns=result["wall_ns"],
                    cpu_ns=result["cpu_ns"],
                    output_sha256=digest(result["results"]),
                    source_bytes_returned=result["source_bytes_returned"],
                )
            )
        reader.close()
        return dict(
            queries=len(load_rows),
            reopens=(len(load_rows) - 1) // protocol["continuous_load"]["reopen_every"]
            + 1,
            independent_task_count=len(requests),
            outputs_stable=all(
                row["output_sha256"] == digest(outputs[row["task_id"]]["results"])
                for row in load_rows
            ),
        ), dict(read_bytes=sum(r["source_bytes_returned"] for r in load_rows))

    load = measured(
        ledger,
        "continuous-load",
        "infer",
        dict(wall_ns=120 * 10**9, cpu_ns=120 * 10**9, read_bytes=512 * 1024**2),
        protocol["continuous_load"],
        load_test,
    )
    retain(output / "load-rows.json", load_rows)
    retain(output / "load-receipt.json", load)
    source = (study / "source-documents.json").read_bytes()

    def compress():
        compressed = {
            "raw-json": source,
            "zlib-9": zlib.compress(source, 9),
            "lzma-6": lzma.compress(source, preset=6),
        }
        if (
            zlib.decompress(compressed["zlib-9"]) != source
            or lzma.decompress(compressed["lzma-6"]) != source
        ):
            raise ValueError("lossless source compression roundtrip failed")
        for name, raw in compressed.items():
            (output / (name + ".bin")).write_bytes(raw)
        return dict(
            codecs={
                k: dict(bytes=len(v), sha256=hashlib.sha256(v).hexdigest())
                for k, v in compressed.items()
            },
            source_bytes=len(source),
            lossless_exact_roundtrip=True,
        ), dict(
            read_bytes=len(source), write_bytes=sum(len(v) for v in compressed.values())
        )

    codecs = measured(
        ledger,
        "source-codecs",
        "source",
        dict(
            wall_ns=30 * 10**9,
            cpu_ns=30 * 10**9,
            read_bytes=2 * 1024**2,
            write_bytes=4 * 1024**2,
        ),
        protocol["source_exact_compression_controls"],
        compress,
    )
    retain(output / "codec-receipt.json", codecs)
    scale = measured(
        ledger,
        "scale-prefixes",
        "index",
        dict(
            wall_ns=60 * 10**9,
            cpu_ns=60 * 10**9,
            read_bytes=32 * 1024**2,
            write_bytes=32 * 1024**2,
        ),
        protocol["corpus_scale_levels"],
        lambda: probe(
            output,
            documents,
            requests,
            protocol["corpus_scale_levels"],
            protocol["source_cutoff"],
        ),
    )
    retain(output / "scale-receipt.json", scale)
    components = [
        dict(name="admitted-source", path=str(study), kind="source", private=False),
        dict(name="retrieval-state", path=str(output), kind="index", private=True),
    ]
    inv = inventory(
        ledger,
        components,
        output.parent / (output.name + ".inventory.json"),
        peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
    )
    result = dict(
        schema="hepta.memory-budget.baselines.v1",
        corpus_documents=len(documents),
        source_document_bytes=sum(len(d["text"].encode()) for d in documents),
        task_count=len(requests),
        prospective_task_results=0,
        input_only=no_memory,
        retrieval_proposals=proposals,
        retrieval_executed=True,
        dense_or_reranker_executed=False,
        load=load["value"],
        codecs=codecs["value"],
        scale=scale["value"],
        retained_declared_bytes=inv["logical_bytes"],
        budget=ledger.snapshot(),
        task_success_not_scored_by_relevance=True,
        unmeasured=[
            "continuous storage byte-time",
            "historical acquisition CPU",
            "OS/runtime file closure",
        ],
        full_equal_total_cost_qualification=False,
    )
    retain(output / "result.json", result)
    validate_seal(study)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.study, args.output), sort_keys=True))
