"""Keep every original E5 source position when reporting v2 tokenizer results."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ENTRY = "scripts/cell_experiments/e5_bounded_target_v2/count_tokens.py"
INDEX_SHA = "6f7ae3e77cbd23a488622a982fc4718f8cbd4bd7049c5d1a9642ee76ea578767"
PREFIX_SHA = "1319a7884200321c108f08bae4c48e9a0e6417b9eb00b34cb1b9d12c0bf38a69"
LEGACY_SHA = "bbfbe6cc9d433755ad22440cd23c0621d0ddf26f414531a3f44e2e0debed3092"
TUPLE = ("source_freeze_sha256", "target_readout_sha256", "tokenizer_freeze_sha256")
GATES = ("v1_static_context_closed", "structural_roundtrip", "visible_action_roundtrip")
ZERO_COUNTERS = (
    "model_loads",
    "forward_calls",
    "generation_calls",
    "training_updates",
    "native_replays",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_sha(value):
    return (
        type(value) is str
        and len(value) == 64
        and set(value) <= set("0123456789abcdef")
    )


def original_source_ids(index_path, prefix_path):
    documents = []
    for path, expected in ((index_path, INDEX_SHA), (prefix_path, PREFIX_SHA)):
        raw = path.read_bytes()
        require(sha(raw) == expected, "original source manifest changed")
        documents.append(json.loads(raw))
    index, prefix = documents
    sources = [row["source_id"] for row in index["materials"]]
    require(
        index["prefix_sha256"] == PREFIX_SHA
        and sources == [row["source_id"] for row in prefix["materials"]]
        and len(sources) == len(set(sources)) == 16
        and sources == sorted(sources),
        "original source order changed",
    )
    return sources


def ordered_rows(rows, sources):
    require(type(rows) is list, "source rows must be a list")
    positions = []
    for row in rows:
        require(type(row) is dict, "source row must be an object")
        ordinal = row.get("ordinal")
        require(
            type(ordinal) is int and 0 <= ordinal < len(sources),
            "invalid original source ordinal",
        )
        require(row.get("source_id") == sources[ordinal], "source identity changed")
        positions.append(ordinal)
    require(positions == sorted(set(positions)), "duplicate or reordered source rows")
    return dict(zip(positions, rows))


def validate_request(request, sources):
    require(type(request) is dict, "request must be an object")
    require(
        request.get("schema") == "hepta.e5.v2.complete-target-tokenizer-request.v1",
        "not a complete v2 target request",
    )
    require(request.get("tokenizer_entrypoint", ENTRY) == ENTRY, "wrong v2 entrypoint")
    require(
        all(is_sha(request.get(k)) for k in TUPLE),
        "missing source/target/tokenizer binding",
    )
    records = ordered_rows(request.get("records"), sources)
    refusals = ordered_rows(request.get("source_refusals"), sources)
    require(
        not records.keys() & refusals.keys()
        and records.keys() | refusals.keys() == set(range(len(sources))),
        "records and refusals must cover every original source exactly once",
    )
    for row in refusals.values():
        require(row.get("status") == "SOURCE_REFUSAL", "invalid source refusal")
    for row in records.values():
        prompt, target = row.get("prompt"), row.get("target")
        require(type(prompt) is str, "missing complete prompt")
        require(sha(prompt.encode()) == row.get("prompt_sha256"), "prompt changed")
        require(target is None or type(target) is str, "invalid complete target")
        require(all(type(row.get(k)) is bool for k in GATES), "nonboolean source gate")
    return records, refusals


def complete_readout(request_raw, counter_raw, sources):
    request, counter = json.loads(request_raw), json.loads(counter_raw)
    records, refusals = validate_request(request, sources)
    require(
        counter.get("schema") == "hepta.e5-codec-tokenizer-readout.v1",
        "wrong original counter result",
    )
    require(counter.get("truncation") is False, "complete untruncated counter required")
    require(
        all(type(counter.get(k)) is int and counter[k] == 0 for k in ZERO_COUNTERS),
        "counter must retain tokenizer-only execution scope",
    )
    require(
        counter.get("serialization")
        == "native_chat_v2; separately encode exact inference prefix and full assistant continuation",
        "counter serialization differs from original protocol",
    )
    require(
        counter.get("request_sha256") == sha(request_raw), "counter request changed"
    )
    require(
        all(counter.get(k) == request[k] for k in TUPLE),
        "counter source/target/tokenizer binding changed",
    )
    measured = ordered_rows(counter.get("rows"), sources)
    require(
        list(measured) == list(records), "token rows do not match requested sources"
    )
    rows = []
    for ordinal, source_id in enumerate(sources):
        if ordinal in refusals:
            rows.append(
                {
                    **refusals[ordinal],
                    "static_representation_admitted": False,
                    "training_execution_admitted": False,
                }
            )
            continue
        record, row = records[ordinal], measured[ordinal]
        prompt_bytes = len(record["prompt"].encode())
        require(
            row.get("prompt_sha256") == record["prompt_sha256"]
            and type(row.get("prompt_bytes")) is int
            and row["prompt_bytes"] == prompt_bytes,
            "counter prompt binding changed",
        )
        prefix = row.get("prefix_tokens")
        require(type(prefix) is int and prefix >= 0, "invalid prefix token count")
        require(
            is_sha(row.get("prefix_ids_sha256")), "missing exact prefix token identity"
        )
        bounds = {
            "fits_original_native_message_bytes_65536": prompt_bytes <= 65536,
            "fits_original_input_4096": prefix <= 4096,
            "fits_original_sft_3584": False,
            "fits_original_generation_384": False,
        }
        target = record["target"]
        if target is not None:
            tokens, target_bytes = row.get("target_tokens"), len(target.encode())
            require(type(tokens) is int and tokens >= 0, "invalid target token count")
            require(
                is_sha(row.get("target_ids_sha256"))
                and type(row.get("prefix_labels_masked")) is int
                and row["prefix_labels_masked"] == prefix
                and type(row.get("all_target_labels_retained")) is int
                and row["all_target_labels_retained"] == tokens,
                "complete target labels or masked prefix changed",
            )
            require(
                row.get("target_sha256") == sha(target.encode())
                and type(row.get("target_bytes")) is int
                and row["target_bytes"] == target_bytes
                and type(row.get("complete_sft_positions")) is int
                and row["complete_sft_positions"] == prefix + tokens,
                "counter target binding changed",
            )
            bounds.update(
                {
                    "fits_original_sft_3584": prefix + tokens <= 3584,
                    "fits_original_generation_384": tokens <= 384,
                    "fits_original_answer_bytes_32768": target_bytes <= 32768,
                }
            )
        else:
            require(
                row.get("target_tokens") is None
                and row.get("complete_sft_positions") is None,
                "unexpected target measurement",
            )
        require(
            all(row.get(k) is value for k, value in bounds.items()),
            "counter bounds changed",
        )
        admitted = (
            target is not None
            and all(record[k] for k in GATES)
            and all(bounds.values())
        )
        require(
            row.get("static_representation_admitted") is admitted,
            "counter static gate changed",
        )
        require(
            row.get("training_execution_admitted") is False,
            "token counts do not admit training",
        )
        rows.append({**row, "status": "MEASURED"})
    prefixes = {
        str(n): n <= len(rows)
        and all(rows[i]["static_representation_admitted"] for i in range(n))
        for n in (1, 4, 16, 64)
    }
    return {
        "schema": "hepta.e5.v2.complete-source-prefix-readout.v1",
        "material_index_sha256": INDEX_SHA,
        "source_prefix_sha256": PREFIX_SHA,
        "request_sha256": sha(request_raw),
        "original_counter_sha256": sha(counter_raw),
        "original_counter_scope": {
            k: counter[k] for k in ("truncation", "serialization", *ZERO_COUNTERS)
        },
        **{k: request[k] for k in TUPLE},
        "rows": rows,
        "prefix_1_4_16_representable": {k: prefixes[k] for k in ("1", "4", "16")},
        "prefix_1_4_16_64_representable": prefixes,
        "original_counter_prefixes": counter.get("prefix_1_4_16_representable"),
        "missing_sources_for_64": max(0, 64 - len(sources)),
        "training_prefix_1_4_16_64_admitted": {k: False for k in prefixes},
        "optimizer_unit_mapping": None,
        "new_compute_or_verification_budget": None,
        "independent_future_panel": None,
    }


def main():
    parser = argparse.ArgumentParser()
    for name in ("request", "material-index", "source-prefix", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--counter-result", type=Path)
    mode.add_argument("--tokenizer-freeze", type=Path)
    args = parser.parse_args()
    sources = original_source_ids(args.material_index, args.source_prefix)
    request_raw = args.request.read_bytes()
    validate_request(json.loads(request_raw), sources)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "ORIGINAL_REQUEST.json").write_bytes(request_raw)
    if args.counter_result is not None:
        counter_raw = args.counter_result.read_bytes()
    else:
        legacy = (
            Path(__file__).resolve().parent.parent
            / "e5_source_codec_v1/count_tokens.py"
        )
        require(
            sha(legacy.read_bytes()) == LEGACY_SHA, "original counter source changed"
        )
        child = subprocess.run(
            [
                sys.executable,
                str(legacy),
                "--request",
                str(args.request),
                "--tokenizer-freeze",
                str(args.tokenizer_freeze),
                "--output",
                str(args.output / "original-counter"),
            ],
            capture_output=True,
        )
        (args.output / "original-counter.stdout").write_bytes(child.stdout)
        (args.output / "original-counter.stderr").write_bytes(child.stderr)
        if child.returncode:
            raise SystemExit(child.returncode)
        counter_raw = (args.output / "original-counter/RESULT.json").read_bytes()
    (args.output / "ORIGINAL_COUNTER_RESULT.json").write_bytes(counter_raw)
    result = complete_readout(request_raw, counter_raw, sources)
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        json.dumps(
            {
                "prefixes": result["prefix_1_4_16_64_representable"],
                "output": str(args.output / "RESULT.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
