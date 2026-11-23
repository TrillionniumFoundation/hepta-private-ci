"""Deterministic four-action replay and a bounded arithmetic reference evaluator."""

import ast
import random
import re

STATES = ("two previous attempts errored", "empty file present", "file saved", "exit 0")
TEMPLATES = (
    "Write Python to print the multiples of {d} between 1 and {n} inclusive.",
    "List numbers divisible by {d} from 1 through {n} with a Python script.",
    "In Python, print each multiple of {d} up to {n}, starting at 1.",
    "Output every integer from 1 to {n} divisible by {d}. Use Python.",
    "Make a Python program listing positive multiples of {d} no larger than {n}.",
    "Generate Python that prints values divisible by {d} over 1..{n} inclusive.",
)


def panel(seed, historical):
    rng = random.Random(seed)
    numbers = [
        (d, n) for d in (2, 3, 4, 5, 6, 8, 9, 11) for n in (32, 47, 60, 81, 97, 120)
    ]
    cases = [("known", historical, 7, 100)]
    cases.extend(("wording", t.format(d=7, n=100), 7, 100) for t in TEMPLATES)
    for i, (d, n) in enumerate(rng.sample(numbers, 12)):
        cases.append(("changed", TEMPLATES[i % len(TEMPLATES)].format(d=d, n=n), d, n))
    return [
        dict(id=f"q{i:02d}", group=g, query=q, divisor=d, bound=n)
        for i, (g, q, d, n) in enumerate(cases)
    ]


def stage_prompt(query, stage):
    return query + "\nState: " + STATES[stage]


def integer(node):
    if (
        not isinstance(node, ast.Constant)
        or type(node.value) is not int
        or not 0 <= node.value <= 300
    ):
        raise ValueError("bounded nonnegative integer required")
    return node.value


def variable(node, name):
    return isinstance(node, ast.Name) and node.id == name


def outputs(program):
    """Interpret the declared for/range/if/print grammar. Never execute submitted code."""
    try:
        if len(program) > 600:
            return None
        body = ast.parse(program).body
        if len(body) != 1 or not isinstance(body[0], ast.For):
            return None
        loop = body[0]
        if loop.orelse or not isinstance(loop.target, ast.Name) or len(loop.body) != 1:
            return None
        name = loop.target.id
        call = loop.iter
        if (
            not isinstance(call, ast.Call)
            or not variable(call.func, "range")
            or call.keywords
        ):
            return None
        span = range(*(integer(x) for x in call.args))
        line = loop.body[0]
        divisor = None
        if isinstance(line, ast.If):
            cond = line.test
            if len(line.body) != 1 or line.orelse or not isinstance(cond, ast.Compare):
                return None
            if (
                len(cond.ops) != 1
                or not isinstance(cond.ops[0], ast.Eq)
                or integer(cond.comparators[0]) != 0
            ):
                return None
            mod = cond.left
            if (
                not isinstance(mod, ast.BinOp)
                or not isinstance(mod.op, ast.Mod)
                or not variable(mod.left, name)
            ):
                return None
            divisor = integer(mod.right)
            if not divisor:
                return None
            line = line.body[0]
        if not isinstance(line, ast.Expr) or not isinstance(line.value, ast.Call):
            return None
        print_call = line.value
        if (
            not variable(print_call.func, "print")
            or print_call.keywords
            or len(print_call.args) != 1
            or not variable(print_call.args[0], name)
        ):
            return None
        return [v for v in span if divisor is None or v % divisor == 0]
    except (SyntaxError, TypeError, ValueError, OverflowError, RecursionError):
        return None


def passes(stage, answer, case):
    if stage == 1:
        return outputs(answer.strip()) == list(
            range(case["divisor"], case["bound"] + 1, case["divisor"])
        )
    return answer.strip() == {0: "create", 2: "run", 3: "done"}[stage]


def words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def retrieved_prompt(query, state, memory, tokenizer, wrap, limit):
    candidates = [r for r in memory if r["state"] == state]
    if not candidates:
        return query
    terms = words(query)

    def similarity(r):
        previous = words(r["prompt"])
        return len(previous & terms) / max(1, len(previous | terms))

    best = max(candidates, key=similarity)
    text = best["target"]
    while text:
        context = query + "\nPrior example: " + text
        if len(tokenizer.encode(wrap(context), add_special_tokens=False)) <= limit:
            return context
        text = text[:-1]
    return query
