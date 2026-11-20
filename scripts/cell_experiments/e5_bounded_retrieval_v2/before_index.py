"""One bounded lexical index of sanitized before bytes; upstream code never runs."""

import ast
import collections
import re
import textwrap
from pathlib import PurePosixPath

from v2_common import Budget, canonical, policy, require, sha, terms
from v2_legacy import source_actions, source_units

FRAME = re.compile(r"([^\s:\n]+\.(?:py|pyx)):(\d+):\s+in\s+([^\s]+)")


def validate_visible(visible, budget):
    require(
        set(visible) == {"identity", "identity_sha256", "runtime", "task", "cases"},
        "only the sanitized before/task API is accepted",
    )
    identity = visible["identity"]
    require(
        sha(canonical(identity)) == visible["identity_sha256"],
        "visible identity changed",
    )
    for label in ("runtime", "task"):
        rows = []
        for path, raw in sorted(visible[label].items()):
            name = PurePosixPath(path)
            require(
                type(raw) is bytes
                and not name.is_absolute()
                and str(name) == path
                and ".." not in name.parts,
                "unsafe visible bytes/path",
            )
            rows.append({"path": path, "sha256": sha(raw), "bytes": len(raw)})
        require(rows == identity[label], "visible bytes changed: " + label)
    require(
        sha(canonical(visible["cases"])) == identity["cases_sha256"],
        "before cases changed",
    )
    budget.check(
        runtime_bytes=sum(map(len, visible["runtime"].values())),
        task_bytes=sum(map(len, visible["task"].values())),
        total_files=len(visible["runtime"]) + len(visible["task"]),
        diagnostic_bytes=sum(
            len((c["failure"] or "").encode()) for c in visible["cases"]
        ),
    )
    require(visible["runtime"] and visible["cases"], "empty original material")
    require(
        not set(visible["runtime"]) & set(visible["task"]),
        "runtime crossed task boundary",
    )


def semantic_text(raw, budget):
    tree = ast.parse(textwrap.dedent(raw.decode("utf-8")))
    nodes = list(ast.walk(tree))
    budget.check(ast_nodes=budget.counts["ast_nodes"] + len(nodes))
    docs = {
        id(n.body[0].value)
        for n in nodes
        if isinstance(
            n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    identifiers, literals = [], []
    for node in nodes:
        if isinstance(node, ast.Name):
            identifiers.append(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.append(node.name)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docs
        ):
            literals.append(node.value)
    return terms(" ".join(identifiers + literals)), terms(" ".join(literals))


def index_before(visible):
    budget = Budget()
    validate_visible(visible, budget)
    failed = sorted(
        [c for c in visible["cases"] if c["failure"] is not None],
        key=lambda c: (c["classname"], c["name"]),
    )
    require(failed, "original before failure absent")
    names = " ".join(c["name"] for c in failed)
    matched = [
        p
        for p in sorted(visible["task"])
        if re.search(
            r"(?<![A-Za-z0-9_])"
            + re.escape(PurePosixPath(p).stem)
            + r"(?![A-Za-z0-9_])",
            names,
        )
    ]
    diagnostic = "\n".join(
        c["classname"] + "::" + c["name"] + "\n" + c["failure"] for c in failed
    )
    counts = collections.Counter(terms(diagnostic))
    limit = budget.limits["query_terms"]
    query = set(sorted(counts, key=lambda w: (-counts[w], w))[:limit])
    mismatch_counts = collections.Counter(
        terms(
            "\n".join(
                line
                for line in diagnostic.splitlines()
                if re.match(r"^E\s+[+-]\s", line)
            )
        )
    )
    mismatch = set(
        sorted(mismatch_counts, key=lambda w: (-mismatch_counts[w], w))[:limit]
    )
    fixture_counts, unsupported = collections.Counter(), []
    for path in matched:
        if path.endswith(".py"):
            try:
                body, _ = semantic_text(visible["task"][path], budget)
                fixture_counts.update(body)
            except (SyntaxError, UnicodeError, IndentationError):
                unsupported.append(path)
    fixture = set(sorted(fixture_counts, key=lambda w: (-fixture_counts[w], w))[:limit])
    frames = [(p, int(line) - 1) for p, line, _ in FRAME.findall(diagnostic)]
    units, rankings = [], []
    weights = policy()["rank"]
    for path, raw in sorted(visible["runtime"].items()):
        budget.check(runtime_file_bytes=len(raw))
        current = source_units.inventory(path, raw)
        budget.check(source_units=len(units) + len(current))
        for unit in current:
            try:
                body, literals = semantic_text(unit["text"].encode(), budget)
            except (SyntaxError, UnicodeError, IndentationError):
                body, literals = set(terms(unit["text"])), set()
            body, literals = set(body), set(literals)
            frame = any(
                (p == path or p.endswith("/" + path))
                and unit["start_line"] <= line < unit["end_line"]
                for p, line in frames
            )
            score = (
                weights["frame_bonus"] * int(frame)
                + weights["diagnostic_literal_weight"] * len(literals & mismatch)
                + weights["fixture_semantic_weight"] * len(body & fixture)
                + weights["qualified_name_weight"]
                * len(set(terms(unit["qualname"])) & query)
                + weights["diagnostic_body_weight"] * len(body & query)
            )
            rankings.append(
                {
                    "unit_id": unit["unit_id"],
                    "path": path,
                    "start_line": unit["start_line"],
                    "end_line": unit["end_line"],
                    "score": score,
                    "before_frame": frame,
                }
            )
        units += current
        budget.check()
    rankings.sort(
        key=lambda r: (
            -r["score"],
            r["path"],
            r["start_line"],
            r["end_line"],
            r["unit_id"],
        )
    )
    require(rankings and rankings[0]["score"] > 0, "no before-visible runtime location")
    binding, _ = source_actions.bind(
        visible["identity"]["source_id"], visible["runtime"]
    )
    budget.check()
    return {
        "visible": visible,
        "units": units,
        "ranking": rankings,
        "binding": binding,
        "failed": failed,
        "matched_task_paths": matched,
        "unsupported_task_scripts": unsupported,
        "query": sorted(query),
        "mismatch": sorted(mismatch),
        "fixture_terms": sorted(fixture),
        "budget": budget,
    }
