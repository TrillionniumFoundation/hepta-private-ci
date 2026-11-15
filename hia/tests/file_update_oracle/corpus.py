"""Deterministic typed corpus. Predictions are unobserved until the real owner runs."""
import hashlib
import json

CASE_COUNT = 56
EXECUTION_COUNT = 159
SEMANTIC_COUNT = 157
PRECONDITION_COUNT = 2


def corpus():
    cases = []

    def chunk(old, new, *, context=None, indices=(), eof=False):
        return {"old": old, "new": new, "context": context,
                "indices": [list(pair) for pair in indices], "eof": eof}

    def add(name, source, chunks, *, modes=(0, 1), routes=(0, 1),
            predictions=None, precondition=False, patch="", file_kind=0):
        cases.append({"id": name, "source": source, "chunks": chunks,
                      "modes": list(modes), "routes": list(routes),
                      "predictions": predictions or {}, "patch": patch,
                      "file_kind": file_kind, "precondition": precondition})

    for name, source, predicted in [
        ("empty", "", ""), ("unterminated", "a", "a\n"),
        ("terminated", "a\n", "a\n"), ("single-empty-line", "\n", ""),
        ("two-empty-lines", "\n\n", "\n"),
        ("trailing-empty-line", "a\n\n", "a\n"),
        ("two-trailing-empty-lines", "a\n\n\n", "a\n\n"),
        ("crlf", "a\r\nb\r\n", "a\r\nb\r\n"),
        ("bare-cr", "a\rb", "a\rb\n"), ("final-bare-cr", "a\r", "a\r\n"),
        ("mixed-endings", "a\r\nb\rc\n", "a\r\nb\rc\n"),
    ]:
        add("no-chunks-" + name, source, [],
            predictions={"0/0": {"status": "success", "content": predicted}})

    add("overlapping-eof-reverse-edits", "a\nb\nc\n",
        [chunk(["b", "c"], ["X"], eof=True), chunk(["c"], ["Y", "Z"], eof=True)],
        predictions={"0/0": {"status": "success", "content": "a\nX\nZ\n"},
                     "1/0": {"status": "error", "kind": "ComputeReplacements"}})
    add("overlapping-eof-delete-all", "a\nb\nc\n",
        [chunk(["a", "b", "c"], [], eof=True), chunk(["c"], [], eof=True)])
    add("same-start-insertions-stable-order", "a",
        [chunk([], ["X"]), chunk([], ["Y"]), chunk([], ["Z"])],
        predictions={"0/0": {"status": "success", "content": "a\nX\nY\nZ\n"}})
    add("old-empty-vector", "a", [chunk([], ["x"])],
        predictions={"0/0": {"status": "success", "content": "a\nx\n"}})
    add("old-single-empty-string", "a", [chunk([""], ["x"])],
        predictions={"0/0": {"status": "success", "content": "x\na\n"}})
    add("old-single-empty-string-eof", "a", [chunk([""], ["x"], eof=True)])
    add("empty-vector-before-trailing-empty-line", "a\n\n", [chunk([], ["x"])])
    add("empty-vector-after-found-context", "ctx\na\nb\n", [chunk([], ["x"], context="ctx")])
    add("empty-vector-missing-context", "a\n", [chunk([], ["x"], context="missing")],
        predictions={"0/0": {"status": "error", "kind": "ComputeReplacements",
                             "display_contains": "Failed to find context 'missing'"}})
    add("trim-empty-old-and-new", "a", [chunk(["a", ""], ["x", ""])])
    add("trim-empty-old-only", "a", [chunk(["a", ""], ["x", "y"])])
    add("trim-both-to-empty", "a", [chunk([""], [""])])
    add("real-empty-line-not-sentinel", "\na\n", [chunk([""], ["x", ""])])
    add("only-one-sentinel-trimmed", "a", [chunk(["a", "", ""], ["x", "", ""])])
    add("error-retains-untrimmed-old", "a", [chunk(["missing", ""], ["x", ""])],
        predictions={"0/0": {"status": "error", "kind": "ComputeReplacements",
                             "display_suffix": "\nmissing\n"}})
    add("context-error-precedes-pattern-error", "a\n",
        [chunk(["missing-old"], ["x"], context="missing-context")])
    add("later-chunk-failure-no-write", "a\nb\n",
        [chunk(["a"], ["A"]), chunk(["missing"], ["X"])])
    add("context-does-not-rewind", "ctx\na\nctx\nb\n",
        [chunk(["b"], ["B"]), chunk(["a"], ["A"], context="ctx")])
    add("eof-does-not-fallback-to-earlier-match", "a\nb\nc\n", [chunk(["a"], ["A"], eof=True)])
    add("exact-pass-before-earlier-trimmed-match", " target \ntarget\n", [chunk(["target"], ["X"])],
        predictions={"0/0": {"status": "success", "content": " target \nX\n"}})
    add("trailing-trim-pass-before-full-trim", " target \ntarget \n", [chunk(["target"], ["X"])])
    add("unicode-punctuation-mapping", "\u201cx\u201d \u2014 \u2018y\u2019\n",
        [chunk(['"x" - \'y\''], ["matched"])])
    add("unicode-nonbreaking-space", "a\u00a0b\n", [chunk(["a b"], ["X"])])
    add("unicode-combining-not-normalized", "\u00e9\n", [chunk(["e\u0301"], ["X"])])
    add("unicode-case-not-folded", "A\n", [chunk(["a"], ["X"])])
    add("crlf-fuzzy-context-retention", "ctx \r\na\r\n",
        [chunk(["ctx", "a"], ["ctx", "A"], indices=[(0, 0)])])
    add("bare-cr-is-not-lf-split", "a\rb", [chunk(["a\rb"], ["X"])])
    add("embedded-newline-in-new-ast-string", "a\n", [chunk(["a"], ["x\ny"])])
    add("embedded-newline-in-old-ast-string", "a\nb\n", [chunk(["a\nb"], ["X"])])
    add("embedded-nul-unicode-in-new-string", "a\n", [chunk(["a"], ["\0\u03b1\U0001f642\rZ"])])
    add("context-first-pair-out-of-bounds", "a\nb\n",
        [chunk(["a", "b"], ["A", "B"], indices=[(2, 0), (0, 0)])])
    add("context-new-index-out-of-bounds", "a\nb\n",
        [chunk(["a", "b"], ["A", "B"], indices=[(0, 2), (1, 1)])])
    add("context-index-usize-max", "a\nb\n",
        [chunk(["a", "b"], ["A", "B"], indices=[(2**64 - 1, 0), (0, 0)])])
    add("context-valid-then-out-of-bounds", "a \r\nb\r\nc\r\n",
        [chunk(["a", "b", "c"], ["a", "B", "C"], indices=[(0, 0), (3, 2), (1, 1)])])
    add("context-trimmed-sentinel-out-of-bounds", "a",
        [chunk(["a", ""], ["A", ""], indices=[(1, 1)])])
    add("normalize-ignores-context-indices", "a\nb\n",
        [chunk(["a", "b"], ["A", "B"], indices=[(1, 1), (0, 0)])], modes=(0,))
    add("preserve-nonmonotone-context-panic", "a\nb\n",
        [chunk(["a", "b"], ["A", "B"], indices=[(1, 1), (0, 0)])],
        modes=(1,), routes=(0,), precondition=True)
    add("preserve-duplicate-context-panic", "a\nb\n",
        [chunk(["a", "b"], ["A", "B"], indices=[(0, 0), (0, 0)])],
        modes=(1,), routes=(0,), precondition=True)
    add("missing-file", "", [chunk(["a"], ["A"])], file_kind=1)
    add("directory-target", "", [chunk(["a"], ["A"])], file_kind=2)
    add("invalid-utf8-file", "", [chunk(["a"], ["A"])])
    cases[-1]["source_bytes_hex"] = "61ff0a"
    for name, source, body in [
        ("crlf-context", "ctx \r\na\r\n", "@@\n ctx\n-a\n+A"),
        ("mixed-endings", "a\r\nb\rc\n", "@@\n a\n-b\n+B\n c"),
        ("unterminated-final-line", "a\nb", "@@\n a\n-b\n+B"),
        ("delete-final-line", "a\nb\n", "@@\n a\n-b\n*** End of File"),
    ]:
        add("parsed-write-" + name, source, [], routes=(2,),
            patch="*** Begin Patch\n*** Update File: input.txt\n" + body + "\n*** End Patch")
    names = [c["id"] for c in cases]
    if len(cases) != CASE_COUNT or len(names) != len(set(names)):
        raise RuntimeError("the complete 56-case input inventory changed")
    executions = list(expand(cases))
    if len(executions) != EXECUTION_COUNT or sum(c["precondition"] for c, _, _ in executions) != PRECONDITION_COUNT:
        raise RuntimeError("the complete 159-execution input inventory changed")
    return cases


def expand(cases):
    for case in cases:
        for mode in case["modes"]:
            for route in case["routes"]:
                if route != 1 or mode == 0:
                    yield case, mode, route


def canonical_bytes(cases):
    return (json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(cases):
    return hashlib.sha256(canonical_bytes(cases)).hexdigest()
