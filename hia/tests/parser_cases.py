#!/usr/bin/env python3
"""Generate only inputs; the untouched original Rust supplies every expectation."""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import random

BEGIN, END = "*** Begin Patch", "*** End Patch"
WS = [*range(9, 14), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000]
NEAR_WS = [8, 14, 0x1C, 0x1F, 0x7F, 0x180E, 0x200B, 0x200C, 0x2060, 0xFEFF]


def push(text, parser="main"):
    return {"op": "push", "text": text, "parser": parser}


def finish(parser="main"):
    return {"op": "finish", "parser": parser}


def cases():
    bodies = [
        "", "*** Add File: x", "*** Delete File: x", "*** Update File: x",
        "*** Environment ID:remote", "*** Environment ID: ",
        "*** Environment ID:first\n*** Environment ID: ",
        "*** Update File: x\n@@", "*** Update File: x\n@@\n*** End of File",
        "*** Update File: x\n*** End of File\n+later",
        "*** Update File: x\n@@\n-same\n+same\n same",
        "*** Update File: x\n@@ label \t\n\n \t\n+\n-",
        "*** Update File: x\n*** Move to: dest\n@@\n+a",
        "*** Update File: x\n*** Move to: one\n*** Move to: two",
        "*** Add File: x\n+payload\r\r", "*** Add File: x\n+*** End Patch",
        "*** Add File: ", "*** Add File:  leading path \t\n+trailing \t\r",
        "*** Delete File: x\n", "*** Update File: x\n@@\n@@ \t",
        "*** Update File: x\n@@\n*** Add File: y \t",
        "*** Update File: x\n@@\n+ok\nBAD\n+lost",
        "*** Update File: x\n@@\n+ok\n*** End of File\n \t\nBAD \t",
    ]
    texts = ["", " \t\r\n\u2003", "bad", BEGIN, END, END + "\n", BEGIN + "\n" + END]
    texts += [f"{BEGIN}\n{body}\n{END}" for body in bodies]
    texts += [
        BEGIN + "\n*** Environment ID: \nmissing-end", "wrong-first\nwrong-last",
        BEGIN + "\n*** Update File: x\n@@\n+value\n " + END,
        BEGIN + "\n*** Update File: x\n@@\n+value\n " + END + "\n",
        BEGIN + "\n*** Update File: x\n@@\n+value\n *** Update File: y\n" + END,
        BEGIN + "\n" + END + "\nextra", BEGIN + "\n" + END + "\n\u2003",
        f"{BEGIN}\r\n*** Environment ID:遠端\r\n*** Add File: 文.txt\r\n+é🙂\r\r\n{END}",
    ]
    for text in texts:
        yield "batch-fixed", {"kind": "batch", "input": text}
    for opener, closer, inside in itertools.product(
        ["<<EOF", "<<'EOF'", '<<"EOF"', "<< EOF", " <<EOF", "<<EOF extra"],
        ["EOF", "prefixEOF", " EOF", "EOF suffix", "EOF\t"],
        [BEGIN + "\n" + END, "bad\n" + END, BEGIN + "\nbad"],
    ):
        yield "heredoc", {"kind": "batch", "input": f"{opener}\n{inside}\n{closer}"}
    for code in WS + NEAR_WS:
        c = chr(code)
        for text in [
            f"{c}{BEGIN}{c}\n{END}{c}",
            f"{BEGIN}\n{c}*** Add File: x{c}\n+{c}\n{END}",
            f"{BEGIN}\n*** Environment ID:{c}value{c}\n{END}",
            f"{BEGIN}\n*** Update File: x\n@@{c}\n+v\n{END}",
            f"{BEGIN}\n*** Update File: x\n@@\n+v\n{c}{END}{c}",
        ]:
            yield "unicode-trim-batch", {"kind": "batch", "input": text}
            yield "unicode-trim-stream", {"kind": "stream", "operations": [push(text), finish()]}
    alphabet = ["", "+x", "-x", " x", "@@", "@@ ctx", "*** End of File", "*** Move to: d", "bad"]
    for length in range(4):
        for lines in itertools.product(alphabet, repeat=length):
            yield "bounded-token-product", {"kind": "batch", "input": BEGIN + "\n*** Update File: x\n" + "\n".join(lines) + "\n" + END}
    for text in texts:
        for i in range(len(text) + 1):
            yield "every-scalar-cut", {"kind": "stream", "operations": [push(text[:i]), {"op": "environment"}, push(""), push(text[i:]), finish(), finish()]}
        yield "scalar-at-a-time", {"kind": "stream", "operations": [*(push(c) for c in text), finish(), {"op": "environment"}]}
    prefixes = [
        "BAD\n" + BEGIN + "\n",
        BEGIN + "\n*** Add File: x\n+kept\nBAD\n+discarded\n" + END + "\n",
        BEGIN + "\n*** Environment ID: first\n*** Environment ID: \n*** Add File: lost\n",
        BEGIN + "\n*** Update File: x\n" + END + "\n",
        BEGIN + "\n*** Update File: x\n@@\n@@ \t\n+discarded\n",
        BEGIN + "\n*** Update File: x\n@@\n*** Add File: y \t\n",
        BEGIN + "\n" + END + "\nextra\nignored\n",
    ]
    for prefix in prefixes:
        for terminated in [True, False]:
            yield "error-commit-clone-retry", {"kind": "stream", "operations": [
                push(prefix if terminated else prefix.rstrip("\n")), finish(), {"op": "environment"}, {"op": "clone", "to": "branch"},
                push("+repair\n" + END + "\n"), finish(), push(BEGIN + "\n*** Add File: retry\n+branch\n" + END + "\n", "branch"), finish("branch"),
                {"op": "snapshot"}, {"op": "snapshot", "parser": "branch"},
            ]}
    for prefix in ["", BEGIN + "\n", BEGIN + "\n*** Add File: x\n+par", BEGIN + "\n*** Update File: x\n@@\n-old\n", BEGIN + "\n" + END + "\n"]:
        yield "clone-and-owned-return", {"kind": "stream", "operations": [push(prefix), {"op": "clone", "to": "branch"}, {"op": "mutate_returned"}, push("t-one\n" + END), finish(), push("t-two\n" + END, "branch"), finish("branch"), {"op": "snapshot"}, {"op": "snapshot", "parser": "branch"}]}
    paths = ["", ".", "..", "a/../b", "/absolute", "a\\b", "C:\\windows\\x", "\\\\server\\share", "nul\0tail", "遠端/🙂", "file:///not-special", {"unix_bytes": [0x66, 0x80, 0xFF]}]
    for cwd, path, kind in itertools.product(["file:///oracle/root", "file:///C:/root", "file://server/root"], paths, ["AddFile", "DeleteFile", "UpdateFile"]):
        for move in ([None, "", "destination"] if kind == "UpdateFile" else [None]):
            yield "real-pathuri", {"kind": "path", "cwd": cwd, "hunk": {"kind": kind, "path": path, "move_path": move}}
    rng = random.Random(0x19F33D8DA)
    tokens = [BEGIN, END, "*** Add File: x", "*** Delete File: y", "*** Update File: z", "*** Environment ID:remote", "*** Environment ID: ", *alphabet, "\r", "é🙂", "*** End Patch \t", " *** End Patch"]
    for _ in range(384):
        text = "\n".join(rng.choice(tokens) for _ in range(rng.randrange(14)))
        offsets = sorted({0, len(text), *(rng.randrange(len(text) + 1) for _ in range(5))})
        operations = [push(text[a:b]) for a, b in zip(offsets, offsets[1:])]
        operations += [finish(), {"op": "clone", "to": "retry"}, push("+later\n" + END + "\n"), finish(), finish("retry")]
        yield "deterministic-random-stream", {"kind": "stream", "operations": operations}


def large_cases():
    for label, payload in [("ascii", "x" * 2_200_000), ("unicode", "é中🙂" * 250_000)]:
        text = BEGIN + "\n*** Add File: long\n+" + payload + "\n" + END
        yield "large-" + label + "-batch", {"kind": "batch", "input": text}
        yield "large-" + label + "-chunks", {"kind": "stream", "operations": [*(push(text[i:i + 65521]) for i in range(0, len(text), 65521)), finish()]}
    payload = "".join(chr(c) for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF).replace("\n", "\n+")
    yield "all-unicode-scalar-payload", {"kind": "batch", "input": BEGIN + "\n*** Add File: unicode\n+" + payload + "\n" + END}
    text = BEGIN + "\n" + "".join(f"*** Update File: file-{n}\n@@\n-old\n+new\n context\n" for n in range(20_000)) + END
    yield "large-hunk-table", {"kind": "batch", "input": text}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--include-large", action="store_true")
    args = p.parse_args()
    counts, digest, total = Counter(), hashlib.sha256(), 0
    with args.output.open("wb") as stream:
        for i, (family, case) in enumerate(itertools.chain(cases(), large_cases() if args.include_large else [])):
            case.update(case_id=f"{i:06d}:{family}", family=family)
            data = (json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            stream.write(data); digest.update(data); total += len(data); counts[family] += 1
    report = {"schema": "codex.hia.patch-parser-oracle-corpus.v1", "cases": sum(counts.values()), "families": dict(counts), "sha256": digest.hexdigest(), "bytes": total, "seed": "0x19F33D8DA", "include_large": args.include_large, "expectations": "Only complete original Rust supplies expected behavior.", "native_parser_qualified": False}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
