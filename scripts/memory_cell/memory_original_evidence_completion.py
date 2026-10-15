#!/usr/bin/env python3
"""Read-only two-source evidence-set completion on real Git originals.

Historical, already exposed 12-case cohort; no model call, semantic judge,
future evidence or program repair is inferred. All rank arms have two source
slots, three unmodified source lines per slot and the same 480-byte per-source
budget. Original implementation labels are opened by the scorer only.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re

from memory_original_nonparam_pair import (
    ARMS, QUESTIONS, ROOT_COUNTS, bm25_candidates, code_search_candidates,
    read_docs, scope_node, source_graph_candidates,
)
from real_source_reader_probe import (
    SOURCE_CUT, SOURCE_SHA, REOPEN_SHA, canonical, digest, real_source,
    require, strict_json, write_once,
)

SCHEMA = "hepta.memory.original-crossfile-evidence-completion.v1"
SLOTS = 2
MAX_SPANS = 3
MAX_BYTES_PER_SOURCE = 480
# These are filled only from a frozen deterministic, label-free original run.
PLAN_SHA256 = "5f34ff721dfd502292bb215083f7f00a059529b037ff838f5b955b8fc12c3d59"
RANK_SHA256 = "cc7c806ea48d05a98a2964e7e01ed074ede550b0231c1053f10cc80d1310974e"


def public_plan(sources):
    docs = read_docs(sources)
    cases = [dict(id=i, root=r, caller_file=f, caller_scope=s, symbol=n)
             for i, r, f, s, n in QUESTIONS]
    require(len(cases) == 12 and len({c["id"] for c in cases}) == 12
            and Counter(c["root"] for c in cases) == ROOT_COUNTS,
            "source family / registered question drift")
    return dict(schema=SCHEMA, source_sha256=SOURCE_SHA,
                reopen_sha256=REOPEN_SHA, source_cut=SOURCE_CUT,
                cases=cases, arms=list(ARMS), final_source_slots=SLOTS,
                max_raw_spans_per_source=MAX_SPANS,
                max_bytes_per_source=MAX_BYTES_PER_SOURCE,
                source_inventory=[dict(root=root, path=path, sha256=value["sha256"],
                                       git_blob=value["blob"])
                                  for (root, path), value in sorted(docs.items())],
                gold_before_ranking=False, original_reader_calls=0,
                future_source_family_count=0, production_qualified=False)


def _caller_lines(case, text):
    """Query-only static caller slicing. No independently adjudicated line IDs."""
    symbol = case["symbol"]
    target = symbol.split(".")[-1]
    lines = text.splitlines()
    result = []
    if case["caller_file"].endswith(".py"):
        parsed = ast.parse(text)
        scope = scope_node(parsed, case["caller_scope"])
        if scope is None:
            return []
        imports = [node for node in parsed.body if isinstance(node, ast.ImportFrom)
                   and ((symbol.startswith("HTTPConnection.") and node.module == "http"
                         and any(alias.name == "client" for alias in node.names))
                        or (node.module is not None and node.module.startswith("sklearn.")
                            and any(alias.name == target for alias in node.names)))]
        if imports:
            result.append(imports[0].lineno)
            if not symbol.startswith("HTTPConnection."):
                names = [alias.lineno for alias in imports[0].names if alias.name == target]
                result.extend(names[:1])
        calls = [node for node in ast.walk(scope) if isinstance(node, ast.Call) and
                 ((isinstance(node.func, ast.Attribute) and node.func.attr == target)
                  if "." in symbol else
                  (isinstance(node.func, ast.Name) and node.func.id == target))]
        if calls:
            result.append(min(node.lineno for node in calls))
    else:
        imported = re.compile(r"^\s*use\s+crate::cache::" + re.escape(target) + r"\s*;\s*$")
        result.extend(i for i, line in enumerate(lines, 1) if imported.fullmatch(line))
        scope = case["caller_scope"]
        if scope.startswith("literal-line-"):
            pos = int(scope.removeprefix("literal-line-"))
            if 1 <= pos <= len(lines) and re.search(r"\b" + re.escape(target) + r"\b", lines[pos - 1]):
                result.append(pos)
        else:
            beginning = next((i for i, line in enumerate(lines, 1) if re.search(
                r"\bfn\s+" + re.escape(scope) + r"\b", line)), None)
            if beginning is not None:
                result.extend(i for i in range(beginning, min(beginning + 110, len(lines) + 1))
                              if re.search(r"\b" + re.escape(target) + r"\b", lines[i - 1]))
    return list(dict.fromkeys(result))[:MAX_SPANS]


def _definition_lines(symbol, text):
    target = symbol.split(".")[-1]
    if symbol.startswith("HTTPConnection.") or text.lstrip().startswith("def ") or "\nclass " in text:
        try:
            parsed = ast.parse(text)
            if "." in symbol:
                owner = symbol.split(".")[0]
                for node in parsed.body:
                    if isinstance(node, ast.ClassDef) and node.name == owner:
                        match = next((x for x in node.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                                      and x.name == target), None)
                        if match:
                            return [match.lineno]
            else:
                match = next((x for x in parsed.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and x.name == target), None)
                if match:
                    return [match.lineno]
        except SyntaxError:
            pass
    pattern = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:fn|const|enum)\s+" +
                         re.escape(target) + r"\b")
    return [i for i, line in enumerate(text.splitlines(), 1) if pattern.search(line)][:1]


def _packet(case, path, doc):
    lines = doc["text"].splitlines()
    if path == case["caller_file"]:
        selected = _caller_lines(case, doc["text"])
    else:
        selected = _definition_lines(case["symbol"], doc["text"])
    if not selected:
        selected = [1]
    selected = list(dict.fromkeys(selected))[:MAX_SPANS]
    spans = [dict(line=n, text=lines[n - 1], sha256=digest(lines[n - 1].encode()))
             for n in selected if 1 <= n <= len(lines)]
    require(spans and len(spans) <= MAX_SPANS and
            sum(len(s["text"].encode()) for s in spans) <= MAX_BYTES_PER_SOURCE,
            "unbounded or missing original line evidence")
    return dict(path=path, blob_sha=doc["blob"], source_sha256=doc["sha256"],
                spans=spans, raw_span_bytes=sum(len(s["text"].encode()) for s in spans))


def rank_without_gold(sources, plan):
    require(plan == public_plan(sources), "nonparametric plan altered")
    docs = read_docs(sources)
    result = []
    for case in plan["cases"]:
        root = case["root"]
        lexical = bm25_candidates(case, root, docs)
        symbol = code_search_candidates(case, root, docs, lexical)
        graph = source_graph_candidates(case, root, docs, lexical)
        orders = [lexical, [case["caller_file"]] + [x for x in symbol if x != case["caller_file"]],
                  [case["caller_file"]] + [x for x in graph if x != case["caller_file"]]]
        for arm, order in zip(ARMS, orders, strict=True):
            chosen = order[:SLOTS]
            require(len(chosen) == SLOTS and len(set(chosen)) == SLOTS,
                    "unmatched evidence slots")
            packets = [_packet(case, path, docs[(root, path)]) for path in chosen]
            result.append(dict(id=case["id"], root=root, arm=arm,
                               source_paths=chosen, evidence=packets,
                               raw_span_bytes=sum(x["raw_span_bytes"] for x in packets)))
    require(len(result) == len(QUESTIONS) * len(ARMS), "paired arm / case census missing")
    return dict(schema=SCHEMA + ".ranked.v1", plan_sha256=digest(canonical(plan) + b"\n"),
                rows=result, evidence_slots=SLOTS, labels_opened=False,
                pretrained_calls=0, production_qualified=False)


def independent_score(sources, plan, ranked, external_oracle):
    """Score original raw source line identities, never self-reported successes."""
    require(plan == public_plan(sources) and ranked == rank_without_gold(sources, plan),
            "original evidence tampered or plan identity changed")
    # Deliberately unavailable in rank_without_gold, which cannot see labels.
    from memory_original_crossfile_trace import audit
    verified = audit(sources)
    require(external_oracle == verified and verified["schema"] ==
            "hepta.memory.original-crossfile-dependency.v1",
            "static oracle must be independently regenerated from original Git bytes")
    gold = {x["id"]: x for x in verified["cases"]}
    require(set(gold) == {q["id"] for q in plan["cases"]},
            "static oracle incomplete")
    records = []
    for record in ranked["rows"]:
        g = gold[record["id"]]
        docs = {d["path"]: d for d in record["evidence"]}
        caller = docs.get(g["caller_file"])
        callee = docs.get(g["implementation_file"])
        def contains(doc, sha):
            return bool(doc and any(x["sha256"] == sha for x in doc["spans"]))
        i = contains(caller, g["import_site_sha256"])
        c = contains(caller, g["call_site_sha256"])
        d = contains(callee, g["definition_site_sha256"])
        records.append(dict(id=record["id"], root=record["root"], arm=record["arm"],
                            both_source_files=bool(caller and callee),
                            complete_source_line_set=bool(i and c and d),
                            caller_import=i, caller_use=c, callee_definition=d,
                            raw_span_bytes=record["raw_span_bytes"]))
    arms = {}
    for arm in ARMS:
        selected = [row for row in records if row["arm"] == arm]
        arms[arm] = dict(cases=len(selected), complete_pairs=sum(x["both_source_files"] for x in selected),
                         import_use_definition_all_present=sum(x["complete_source_line_set"] for x in selected),
                         import_line=sum(x["caller_import"] for x in selected),
                         call_line=sum(x["caller_use"] for x in selected),
                         definition_line=sum(x["callee_definition"] for x in selected),
                         evidence_bytes=sum(x["raw_span_bytes"] for x in selected),
                         by_family={root:dict(cases=sum(x["root"] == root for x in selected),
                                              completed=sum(x["root"] == root and x["complete_source_line_set"] for x in selected))
                                    for root in ROOT_COUNTS})
    return dict(schema=SCHEMA + ".independent-scored.v1", source_sha256=SOURCE_SHA,
                original_case_count=12, independent_original_roots=3,
                arms=arms, code_graph_increment_over_symbol=
                arms[ARMS[2]]["import_use_definition_all_present"] -
                arms[ARMS[1]]["import_use_definition_all_present"],
                paired_original_source_statics=records,
                new_model_calls=0, independent_human_semantic_judgement=False,
                natural_reader_task_success=None, program_repair_success=None,
                future_window_count=0, total_lifecycle_cost=None,
                production_qualified=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "rank", "score"))
    p.add_argument("--source-zip", type=Path, required=True)
    p.add_argument("--reopen-zip", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--ranking", type=Path)
    p.add_argument("--oracle", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    source = real_source(args.source_zip, args.reopen_zip)
    plan = public_plan(source)
    if args.command == "prepare":
        raw = canonical(plan) + b"\n"
    else:
        require(args.plan.is_file() and args.plan.read_bytes() == canonical(plan) + b"\n" and
                digest(args.plan.read_bytes()) == PLAN_SHA256,
                "source-first plan SHA not frozen")
        if args.command == "rank":
            raw = canonical(rank_without_gold(source, plan)) + b"\n"
        else:
            require(args.ranking and args.oracle and args.ranking.is_file() and args.oracle.is_file() and
                    digest(args.ranking.read_bytes()) == RANK_SHA256,
                    "independent original ranking pin required")
            raw = canonical(independent_score(source, plan, strict_json(args.ranking.read_bytes()),
                                             strict_json(args.oracle.read_bytes()))) + b"\n"
    if args.command == "prepare":
        require(digest(raw) == PLAN_SHA256, "source-derived frozen plan differs")
    if args.command == "rank":
        require(digest(raw) == RANK_SHA256, "source-derived frozen ranking differs")
    write_once(args.output, raw)
    print(json.dumps(dict(operation=args.command, sha256=digest(raw),
                          pretrained_calls=0, production_qualified=False), sort_keys=True))


if __name__ == "__main__":
    main()
