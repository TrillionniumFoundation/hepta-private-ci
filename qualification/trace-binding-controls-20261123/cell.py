"""Fit and cold-load a three-role program binding from a published four-action trace."""
import argparse
import ast
import hashlib
import itertools
import json
from pathlib import Path
import re
import statistics
import time
import zipfile

import numpy as np

ROLES = ("factor", "lower", "upper")
ARMS = ("replay", "ordinal", "direct", "gradient", "no_cues", "rule", "no_donor")
ARCHIVE_SHA = "28b46e1f84215a0f3554f737930bab93e1d46f890445b14eda61abdb7b32b327"
PENALTY = 0.2
# The categories are an engineered language prior. Each number can also have
# ordinary lexical and position features independently of its semantic category.
CUES = (
    r"(?:divisible by|multiples? of|divisor(?: is)?|factor(?: is)?|step size)\s*$",
    r"(?:from|between|starting at|starting from|start at|at least|lower bound(?: is)?|over)\s*$",
    r"(?:to|through|up to|and|at most|ending at|no larger than|upper bound(?: is)?|\.\.)\s*$",
)
RAW = ("by", "from", "to")
DIGITS = re.compile(r"\b\d+\b")
IN_SCOPE = re.compile(r"divisible by|multiples? of|\bdivisor\b|\bfactor\b")
OTHER = re.compile(r"\b(?:sum|count|except|exclude|not|odd|descending|squares|product|mean|average)\b")


def read(path):
    return json.loads(path.read_bytes())


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_new(path, data):
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def inputs(text):
    text = text.lower()
    found = list(DIGITS.finditer(text))
    candidates = []
    for index, match in enumerate(found):
        left = text[:match.start()]
        before = re.findall(r"[a-z]+|\.\.", left)
        prior = before[-1] if before else ""
        cue = [float(bool(re.search(pattern, left))) for pattern in CUES]
        raw = [float(prior == word) for word in RAW]
        position = [float(index == i) for i in range(3)]
        features = cue + [0.2 * v for v in raw + position]
        candidates.append((int(match.group()), features))
    # This candidate represents the implicit positive lower bound of the skill.
    candidates.append((1, [0.0, 0.8, 0.0] + [0.0] * 6))
    return candidates


def affine(schema, x):
    return x @ np.asarray(schema, dtype=float)


def bind(text, material, arm):
    entries = inputs(text)
    explicit = len(entries) - 1
    if not 2 <= explicit <= 8:
        return None
    if arm == "ordinal":
        order = list(range(explicit))
        if explicit == 2:
            order.insert(material["source_indices"][1], explicit)
        return [entries[order[i]][0] for i in material["source_indices"]]
    x = np.array([row for _, row in entries])
    if arm == "rule":
        score = x[:, :3]
    else:
        if arm == "no_cues":
            x = x[:, 3:]
        score = affine(material["weights"][arm], x)
    # Enforce distinct source occurrences. Equal numeric values may occur.
    assignment = max(itertools.permutations(range(len(entries)), 3),
                     key=lambda v: sum(score[v[j], j] for j in range(3)))
    return [entries[i][0] for i in assignment]


def parse_donor(memory):
    rows = {r["state"]: r for r in memory}
    actions = [rows[i]["target"] for i in range(4)]
    q = rows[1]["prompt"].rsplit("\nState: ", 1)[0]
    tree = ast.parse(actions[1])
    loop, = tree.body
    if not isinstance(loop, ast.For) or not isinstance(loop.iter, ast.Call) or loop.iter.func.id != "range":
        raise ValueError("Unsupported donor loop")
    condition, = loop.body
    if not isinstance(condition, ast.If) or not isinstance(condition.test.left.op, ast.Mod):
        raise ValueError("Unsupported donor filter")
    factor = condition.test.left.right
    lower, upper = loop.iter.args
    tokens = [v for v, _ in inputs(q)[:-1]]
    source_indices, offsets, spans = [], [], []
    lines = actions[1].splitlines(keepends=True)
    for role, node in zip(ROLES, (factor, lower, upper), strict=True):
        if not isinstance(node, ast.Constant) or type(node.value) is not int:
            raise ValueError("Expected an integer literal in the donor")
        matches = [(i, delta) for delta in ((0, 1) if role == "upper" else (0,))
                   for i, value in enumerate(tokens) if value + delta == node.value]
        if len(matches) != 1:
            raise ValueError("Ambiguous alignment")
        index, offset = matches[0]
        source_indices.append(index)
        offsets.append(offset)
        base = sum(map(len, lines[:node.lineno-1]))
        spans.append([base + node.col_offset, base + node.end_col_offset])
    if len(set(source_indices)) != 3 or len(tokens) != 3:
        raise ValueError("The registered donor must uniquely bind three explicit arguments")
    return q, dict(actions=actions, spans=spans, offsets=offsets, source_indices=source_indices)


def solve(x, y, method):
    # Both estimators minimize ||X W - Y||^2 + lambda ||W||^2.
    if method == "direct":
        w = x.T @ np.linalg.solve(x @ x.T + PENALTY * np.eye(len(x)), y)
        return w, 1
    w = np.zeros((x.shape[1], y.shape[1]))
    # The Frobenius bound fixes a stable stepsize without a matrix decomposition.
    step = 1.0 / (np.square(x).sum() + PENALTY)
    for iteration in range(1, 10001):
        grad = x.T @ (x @ w - y) + PENALTY * w
        if np.linalg.norm(grad) <= 1e-9:
            return w, iteration - 1
        w -= step * grad
    raise RuntimeError("Gradient fit did not converge")


def program(material, values, arm):
    if arm == "rule":
        factor, lower, upper = values
        return f"for j in range({lower}, {upper + 1}):\n    if j % {factor} == 0:\n        print(j)"
    script = material["actions"][1]
    for (a, b), v, off in sorted(zip(material["spans"], values, material["offsets"], strict=True),
                                 key=lambda z:z[0][0], reverse=True):
        script = script[:a] + str(v + off) + script[b:]
    return script


def propose(query, material, arm):
    if query == "Return the digit zero.":
        return ["0"]
    if arm == "no_donor":
        return []
    if not IN_SCOPE.search(query.lower()) or OTHER.search(query.lower()):
        return []
    if arm == "replay":
        return material["actions"].copy()
    vals = bind(query, material, arm)
    if vals is None or not (1 <= vals[0] <= 299 and 0 <= vals[1] <= 299 and 0 <= vals[2] <= 299):
        return []
    if arm == "rule":
        return ["create", program(None, vals, arm), "run", "done"]
    actions = material["actions"].copy()
    actions[1] = program(material, vals, arm)
    return actions


def fit(archive, output, times):
    start = time.perf_counter_ns()
    if file_sha(archive) != ARCHIVE_SHA:
        raise ValueError("Wrong source")
    with zipfile.ZipFile(archive) as z:
        memory = json.loads(z.read("memory.json"))
    query, model = parse_donor(memory)
    x = np.array([v for _, v in inputs(query)[:-1]])
    y = np.zeros((len(x), 3))
    for role, idx in enumerate(model["source_indices"]):
        y[idx, role] = 1
    timing, model["weights"] = {}, {}
    for arm in ("direct","gradient","no_cues"):
        t = time.perf_counter_ns()
        w, steps = solve(x[:, 3:] if arm == "no_cues" else x, y, "gradient" if arm=="gradient" else "direct")
        timing[arm] = dict(fit_ns=time.perf_counter_ns()-t,steps=steps)
        model["weights"][arm] = w.tolist()
    model["original_source"] = ARCHIVE_SHA
    model["implementation_sha256"] = file_sha(Path(__file__))
    dump_new(output, model)
    timing["source_load_alignment_and_all_fits_to_disk_ns"] = time.perf_counter_ns()-start
    samples = {"direct": [], "gradient": []}
    for i in range(51):
        for mode in (("direct","gradient") if i%2==0 else ("gradient","direct")):
            t = time.perf_counter_ns()
            solve(x, y, mode)
            samples[mode].append(time.perf_counter_ns()-t)
    timing["alternating_fit_ns"] = samples
    timing["median_fit_ns"] = {k:statistics.median(v) for k,v in samples.items()}
    timing["max_abs_weight_difference"] = float(np.max(np.abs(
        np.asarray(model["weights"]["direct"])-np.asarray(model["weights"]["gradient"]))))
    dump_new(times, timing)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("times", type=Path)
    args = parser.parse_args()
    fit(args.archive,args.model,args.times)
