"""Pure exact-byte / lexical audit of the actual main41e source transitions.
This script reads immutable evidence and writes only its own audit directory.
It does not import project code, run a gate, invoke Rust or Git, or touch H.
"""
import base64
import collections
import difflib
import gzip
import hashlib
import json
from pathlib import Path
from lexical_primitives import ident, lex, changed_sequences

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
GRAPH = Path("/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/CANDIDATE_FILE_GRAPH.json")
PINS = {
 "fix.after": {"raw": [555679,"da484cc8d169e80b539a939902d3c4c16d5db40ea594adc98be1ffdcdb7992b7","1cb4a10f1ca57b4487c4eb03e239d643bf93c0d7"],"gzip":[95513,"ffd361393e4a0400ba53a41542b9608698b52de60c768c0a329e687efd09f4f2","3e55b852f07e13b10e8e3da5c36e57305787d046"],"part":[127353,"35b1aabe37707746b16737163851ae4b4ea9c97d9acf8371ef7e4cb26811ae99","20dd7d549e853f9664429fda17802692c0af985d"],"count":12},
 "fmt.after": {"raw": [555856,"fac9941be31c2e366aa56f487fde4f63b68e679ef2afcf31edfe3b855846b445","fd45c00bc5956ed4de6f666f0c1d509de86f0ac0"],"gzip":[100978,"6621de7fee0d02fcabe5997a43fdd584d342d46493274a233c524271ba2259e0","e010270c7a9d886197082ef873897e0f4375e857"],"part":[134641,"eb10eef6d32294f34c6fc07c9a80afa3e5eaab4b25ae1fca936bc45513591c05","960d167cdeae0539323bd152365e096e77a7e62e"],"count":14},
 "final": {"raw": [665433,"732c48099edc5a704f3aab74d91f997b98f92fdd122adbf49d31b750b77e28a8","88b9299120113937610da4a84b344eda76011674"],"gzip":[117415,"47d010ee5046c09fcfee902d170aa9b458b50b1e91b91b58f50b1e91bdf405f1508602bf307a11","3fc4ea110842f84d6db20bf3c1f27bf7ad35fc40"],"part":[156557,"a6131a8c3e1c4eb23f92052a1cfe392e08c354d67f79d151ae0d5c523de2ef49","7ff9c82ac2f6369e0116f4aec9c48187c9444748"],"count":17}
}
# The final gzip SHA is fixed below to the original ARTIFACTS value.
PINS["final"]["gzip"][1] = "47d010ee5046c09fcfee902d170aa9b458b50b1e91bdf405f1508602bf307a11"

def expect(raw, pin):
    actual = ident(raw)
    assert [actual["bytes"], actual["sha256"], actual["git_blob"]] == pin, (actual, pin)
    return actual

def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ("immutable output changed", str(path))
    else:
        with path.open("xb") as f:
            f.write(raw)

def write_json(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    save(HERE / name, raw)
    return ident(raw)

def main():
    graph_raw = GRAPH.read_bytes()
    assert hashlib.sha256(graph_raw).hexdigest() == "41e1924454c39e21d46f4dddde2cc61a654f462cd82e8a6b659f46fa8e3eae4a"
    graph = json.loads(graph_raw)
    assert graph["tree"] == "a489b394666b8141840275128a780605b024cde0"
    source_rows = {r["path"]: r for r in graph["files"]}
    assert len(source_rows) == len(graph["files"]) == 15243
    all_rows, data, summaries = {}, {}, []
    for stage, pin in PINS.items():
        name = stage + ".postimages.json"
        part_name = name + ".gz.part-001.b64"
        sdk = json.loads((HERE / "github" / (part_name + ".GET.original.json")).read_bytes())
        fetched_part = sdk["structuredContent"]["content"].encode()
        part = (INPUTS / part_name).read_bytes()
        assert fetched_part == part
        expect(part, pin["part"])
        # One LF is part of the frozen text envelope; no permissive Base64 decoding.
        assert part.endswith(b"\n") and b"\n" not in part[:-1]
        zipped = base64.b64decode(part[:-1], validate=True)
        expect(zipped, pin["gzip"])
        raw = gzip.decompress(zipped)
        expect(raw, pin["raw"])
        assert raw == (INPUTS / name).read_bytes()
        packet = json.loads(raw)
        assert packet["stage"] == stage
        assert packet["format"] == "hepta-maintenance-actual-source-transition-v1"
        assert packet["source_commit_unchanged"] == "d25675445c39f76db69a7bd8e71a1a72e1cd5b9f"
        assert packet["all_physical_changes_including_untracked_or_ignored_are_recorded"] is True
        assert packet["qualification"] is False
        rows = {r["path"]: r for r in packet["changes"]}
        assert len(rows) == len(packet["changes"]) == pin["count"]
        all_rows[stage] = packet
        data[stage] = {}
        for path, row in rows.items():
            texts = {}
            for side in ("before", "after"):
                raw_source = base64.b64decode(row[side + "_raw_base64"], validate=True)
                meta = row[side]
                expected = [meta["bytes"], meta["sha256"], meta["working_blob"]]
                expect(raw_source, expected)
                assert meta["path"] == path and meta["kind"] == "file" and meta["stable"] is True
                assert meta["permissions"] == 0o644 and meta["index_mode"] == "100644"
                assert meta["index_blob"] == source_rows[path]["git_blob"]
                assert meta["matches_index"] is (meta["working_blob"] == meta["index_blob"])
                save(HERE / "source-images" / stage / side / path, raw_source)
                texts[side] = raw_source.decode("utf-8")
            data[stage][path] = texts
            before, after = texts["before"], texts["after"]
            at, ac = lex(before); bt, bc = lex(after)
            token_changes = changed_sequences(at, bt)
            comment_changes = changed_sequences(ac, bc)
            diff = "".join(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=path + "." + stage + ".before", tofile=path + "." + stage + ".after"))
            save(HERE / "diffs" / stage / (Path(path).name + ".diff"), diff.encode())
            summaries.append({
              "stage": stage, "path":path,
              "before":ident(before.encode()), "after":ident(after.encode()),
              "token_count_before":len(at), "token_count_after":len(bt),
              "non_whitespace_token_sequences_equal":not token_changes,
              "literal_sequence_exact_equal":[x[:2] for x in at if x[0]=="literal"] == [x[:2] for x in bt if x[0]=="literal"],
              "comments_exact_equal":not comment_changes,
              "token_changes":token_changes, "comment_changes":comment_changes,
              "diff_bytes":len(diff.encode())
            })
    first, formatted, final = (data[k] for k in ("fix.after","fmt.after","final"))
    assert set(final) == set(first) | set(formatted)
    lineage = []
    for path, images in final.items():
        initial = images["before"].encode()
        row = source_rows[path]
        assert [len(initial),hashlib.sha256(initial).hexdigest(),ident(initial)["git_blob"]] == [row["bytes"],row["sha256"],row["git_blob"]]
        assert row["mode"] == "100644" and row["kind"] == "file"
        running = images["before"]
        stages = []
        for stage in ("fix.after","fmt.after"):
            if path in data[stage]:
                assert data[stage][path]["before"] == running, ("broken actual stage chain",stage,path)
                running = data[stage][path]["after"]
                stages.append(stage)
        assert images["after"] == running, ("final disagrees with stages",path)
        lineage.append({"path":path,"actual_stages":stages,
                        "initial_matches_frozen_a489":True,
                        "final_exactly_composes_actual_stages":True,
                        "before":ident(initial),"after":ident(running.encode())})
    assert all_rows["fix.after"]["base_inventory_sha256"] == all_rows["final"]["base_inventory_sha256"]
    assert all_rows["fix.after"]["after_inventory_sha256"] == all_rows["fmt.after"]["base_inventory_sha256"]
    assert all_rows["fmt.after"]["after_inventory_sha256"] == all_rows["final"]["after_inventory_sha256"]
    proof={
      "format":"hepta-main41e-exact-transition-independent-review-v1",
      "scope":"Immutable original evidence decoding and source-byte/lexical comparison only",
      "not_native_execution_or_qualification":True,
      "source_graph":ident(graph_raw), "source_tree":graph["tree"],"source_rows":len(source_rows),
      "artifacts_exact":PINS,
      "actual_stage_counts":{"fix":len(first),"fmt":len(formatted),"union":len(final)},
      "production_paths":[r["path"] for r in lineage if not r["path"].endswith("_tests.rs")],
      "stage_lineage":lineage,
      "lexical_review":summaries,
      "script":ident(Path(__file__).read_bytes()),
      "lexical_helpers":ident((HERE/"lexical_primitives.py").read_bytes()),
      "limits":["The lexer preserves full literals and separately records comments; it is not a Rust parser.",
                "Whitespace/punctuation differences require scoped review; no blanket comma normalization is used.",
                "No project function, formatter, Rust compiler, test, H process, source write, or ref mutation is performed."]
    }
    identity=write_json("ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json",proof)
    print(json.dumps({"report":identity,
      "counts":proof["actual_stage_counts"],
      "production_paths":proof["production_paths"],
      "stage_changes":[{"stage":r["stage"],"file":Path(r["path"]).name,"token_edits":len(r["token_changes"]),
                         "literal_equal":r["literal_sequence_exact_equal"],"comments_equal":r["comments_exact_equal"],"diff_bytes":r["diff_bytes"]}
                        for r in summaries if r["stage"]!="final"]},indent=2))

if __name__ == "__main__":
    main()

