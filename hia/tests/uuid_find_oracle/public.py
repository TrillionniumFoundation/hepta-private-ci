"""Compare entire public results and independently observed original regex spans."""
import json
import struct
from pathlib import Path

from .common import binding, require
from .transport import Native, fixture_cases


def observe(records, fixture, corpus, output, commands, env):
    output.mkdir()
    summaries, results = {}, {}
    for name in ("original", "native"):
        binary = records["observers"][name]["binary"]["path"]
        result = output / (name + "-public.bin")
        spans = output / (name + "-regex-spans.bin")
        stdout = commands.run("observe-" + name + "-public", [binary, fixture, result, spans],
                              cwd=output, env=env)
        summaries[name] = json.loads(stdout.read_bytes())
        require(summaries[name]["cases"] == corpus["cases"]
                and summaries[name]["ownership_checks"] == corpus["cases"],
                "public observer omitted cases or returned-String ownership checks")
        results[name] = binding(result)
    require(results["original"]["bytes"] == results["native"]["bytes"]
            and results["original"]["sha256"] == results["native"]["sha256"]
            and Path(results["original"]["path"]).read_bytes() == Path(results["native"]["path"]).read_bytes(),
            "complete unnormalized public results differ")
    reference, native = summaries["original"], summaries["native"]
    require({k: v for k, v in reference.items() if not k.startswith("actual_hia_")}
            == {k: v for k, v in native.items() if not k.startswith("actual_hia_")},
            "complete public observations differ")
    require(reference["actual_hia_queries"] == reference["actual_hia_emits"] == 0
            and native["actual_hia_queries"] == corpus["cases"]
            and native["actual_hia_emits"] == native["nonempty_cases"],
            "actual native public dispatch was not query/conditional-emit")
    return {"public_pairs_equal": corpus["cases"], "public_transcripts": results,
            "observations": summaries, "path_or_value_normalization_used": False,
            "strings_observed_after_source_overwrite_and_drop": corpus["cases"],
            "original_regex_spans": binding(output / "original-regex-spans.bin")}


def compare_spans(producer, library_dir, fixture, span_record, count, output, report):
    native = Native(producer, library_dir, output / "regex-offset-calls.jsonl.gz")
    try:
        pairs, matches = 0, 0
        with Path(span_record["path"]).open("rb") as stream:
            require(struct.unpack("<Q", stream.read(8))[0] == count, "wrong original span count")
            for index, data in enumerate(fixture_cases(fixture)):
                number = struct.unpack("<Q", stream.read(8))[0]
                require(number <= len(data) // 36, "impossible original non-overlapping UUID count")
                raw = stream.read(16 * number)
                require(len(raw) == 16 * number, "truncated complete original regex spans")
                rows = list(struct.iter_unpack("<QQ", raw))
                native.valid(data, rows, 0, category="complete_original_regex_query_" + str(index))
                native.valid(data, rows, 1, category="complete_original_regex_emit_" + str(index))
                pairs += 1
                matches += number
            require(stream.read(1) == b"" and pairs == count, "extra or missing original regex data")
        report["complete_regex_query_emit_pairs_equal"] = pairs
        report["complete_regex_matches"] = matches
    finally:
        report["raw_plan_execution"] = native.finish()
    require(report["raw_plan_execution"]["counts"] == {
        "calls": 2 * count, "query": count, "emit": count, "errors_no_write": 0},
        "missing real query/emit comparisons")
