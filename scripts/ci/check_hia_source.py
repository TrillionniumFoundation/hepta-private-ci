#!/usr/bin/env python3
"""Fail-fast lexical preflight of pinned HIA source (not native qualification)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

FN = re.compile(r"fn\s+([A-Za-z_]\w*)\(.*\)\s*->\s*\((.*?)\)\s+effects\(.*\)\s+entry\(\w+\)")
BLK = re.compile(r"block\s+([A-Za-z_]\w*)\((.*?)\)")
ASSIGN = re.compile(r"([A-Za-z_]\w*:[A-Za-z_]\w*(?:\([^()]*\))?(?:,[A-Za-z_]\w*:[A-Za-z_]\w*(?:\([^()]*\))?)*)\s*=")
CALL = re.compile(r"(.+?)\s*=\s*call\(.*\)\s+(\{.*\})")
RET = re.compile(r"ret\((.*?)\)")
BIND = re.compile(r"[A-Za-z_]\w*:[A-Za-z_]\w*(?:\([^()]*\))?")


def split_flat(text):
    if not text.strip():
        return []
    if "(" in text or ")" in text:
        raise ValueError("nested register list")
    result = [item.strip() for item in text.split(",")]
    if not all(result):
        raise ValueError("empty register list element")
    return result


def audit(text, path="<source>"):
    lines = text.splitlines()
    errors, funcs, blocks, returns, calls = [], {}, {}, [], []
    active, bindings = None, {}

    def fail(n, code):
        errors.append({"line": n, "code": code})

    if not lines or not re.fullmatch(r"hia-asm\.v1 hepta\.hia\.program\.v\d+ \w+", lines[0]):
        fail(1, "HEADER")
    if not lines or lines[-1] != "end":
        fail(len(lines), "TERMINATOR")
    for n, original in enumerate(lines, 1):
        if not original.strip() or original.lstrip().startswith(("#", "//")):
            continue
        line = original.strip()
        if line.startswith("fn "):
            m = FN.fullmatch(line)
            if m is None:
                fail(n, "FUNCTION_SHAPE")
                active = None
                continue
            active = m[1]
            if active in funcs:
                fail(n, "DUPLICATE_FUNCTION")
            try:
                count = len(split_flat(m[2]))
            except ValueError:
                fail(n, "FUNCTION_RETURN_SHAPE")
                count = 0
            if count > 3:
                fail(n, "TOO_MANY_RESULTS")
            funcs[active] = count
            blocks[active] = set()
            bindings = {}
        elif line.startswith("block "):
            m = BLK.fullmatch(line)
            if m is None or active is None:
                fail(n, "BLOCK_SHAPE")
                continue
            if m[1] in blocks[active]:
                fail(n, "DUPLICATE_BLOCK")
            blocks[active].add(m[1])
            try:
                params = split_flat(m[2])
            except ValueError:
                fail(n, "BLOCK_PARAMETERS")
                params = []
            for param in params:
                if not BIND.fullmatch(param):
                    fail(n, "BLOCK_PARAMETER_SHAPE")
                    continue
                key = param.split(":", 1)[0]
                if key in bindings:
                    fail(n, "DUPLICATE_SSA")
                bindings[key] = n
        elif line.startswith("ret("):
            m = RET.fullmatch(line)
            if not m or active is None:
                fail(n, "RETURN_SHAPE")
            else:
                try:
                    returns.append((active, n, len(split_flat(m[1]))))
                except ValueError:
                    fail(n, "RETURN_LIST")
        elif line == "end":
            active = None
        elif active is not None and original.startswith("  "):
            d = ASSIGN.match(line)
            if d:
                for item in d[1].split(","):
                    key = item.split(":", 1)[0]
                    if key in bindings:
                        fail(n, "DUPLICATE_SSA")
                    bindings[key] = n
            c = CALL.fullmatch(line)
            if c:
                try:
                    meta = json.loads(c[2])
                    target = meta["function"]
                    bound = 0 if c[1] == "_" else len(split_flat(c[1]))
                    if c[1] != "_" and any(not BIND.fullmatch(x) for x in split_flat(c[1])):
                        raise ValueError("binding shape")
                    calls.append((n, target, bound))
                except (ValueError, TypeError, KeyError):
                    fail(n, "CALL_SHAPE")
    for name, n, observed in returns:
        if name in funcs and funcs[name] != observed:
            fail(n, "RETURN_ARITY")
    for n, target, observed in calls:
        if target not in funcs:
            fail(n, "UNKNOWN_CALLEE")
        elif funcs[target] != observed:
            fail(n, "CALL_ARITY")
    if not funcs:
        fail(1, "NO_FUNCTIONS")
    return {"path": path, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "functions": len(funcs), "blocks": sum(len(x) for x in blocks.values()),
            "calls": len(calls), "returns": len(returns), "errors": errors,
            "passed": not errors, "compiler_invocations": 0, "production_qualified": False}


def self_test():
    def program(body):
        return "hia-asm.v1 hepta.hia.program.v9 fixture\n" + body + "end\n"
    def errors(body):
        return [e["code"] for e in audit(program(body))["errors"]]
    z = "fn f0() -> () effects(trap) entry(entry)\nblock entry()\n  ret()\n"
    assert not errors(z)
    assert "HEADER" in [e["code"] for e in audit("bad\n")["errors"]]
    assert "TOO_MANY_RESULTS" in errors(z.replace("-> ()", "-> (u64,u64,u64,u64)"))
    assert "RETURN_ARITY" in errors(z.replace("-> ()", "-> (u64)"))
    assert "DUPLICATE_FUNCTION" in errors(z + "end\n" + z)
    assert "DUPLICATE_SSA" in errors("fn f0() -> () effects(trap) entry(entry)\n"
        "block entry(v:u64)\n  jump second(v)\nblock second(v:u64)\n  ret()\n")
    assert "UNKNOWN_CALLEE" in errors("fn f0() -> () effects(trap) entry(entry)\n"
        "block entry()\n  _ = call() {\"function\":\"missing\"}\n  ret()\n")
    assert "CALL_ARITY" in errors("fn f0() -> () effects(trap) entry(entry)\n"
        "block entry()\n  v:u64 = call() {\"function\":\"g\"}\n  ret()\nend\n"
        "fn g() -> () effects(trap) entry(entry)\nblock entry()\n  ret()\n")
    print("HIA lexical preflight: 8 source-only self-tests passed")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--toolchain", type=Path)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("files", type=Path, nargs="*")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    files = list(args.files)
    if args.toolchain:
        lock = json.loads(args.toolchain.read_text(encoding="utf-8"))
        modules = lock.get("modules")
        if not isinstance(modules, list) or not modules or len(modules) != len(set(modules)):
            p.error("locked modules must be a nonempty unique list")
        if any(not isinstance(x, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", x) for x in modules):
            p.error("invalid locked module name")
        files.extend(args.toolchain.parent / (name + ".hepta") for name in modules)
    if not files:
        p.error("supply source files or --toolchain")
    results = [audit(path.read_text(encoding="utf-8"), str(path)) for path in files]
    print(json.dumps({"passed": all(r["passed"] for r in results), "sources": results},
                     indent=2, sort_keys=True))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
