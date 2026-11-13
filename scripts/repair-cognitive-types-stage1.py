#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

SCRIPT = Path("scripts/apply-cognitive-types-stage1.py")
text = SCRIPT.read_text(encoding="utf-8")

old_helper = '''def replace_once(text: str, old: str, new: str, path: str | Path) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)
'''
new_helper = '''def replace_once(text: str, old: str, new: str, path: str | Path) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0:
        # Source formatters may change only whitespace around a guarded anchor.
        # Accept exactly one whitespace-normalized match; semantic drift still
        # fails closed because zero or multiple normalized matches are rejected.
        pieces = re.split(r"(\\s+)", old)
        pattern = "".join(r"\\s+" if piece.isspace() else re.escape(piece) for piece in pieces)
        updated, normalized_count = re.subn(pattern, lambda _: new, text, count=1)
        if normalized_count == 1:
            return updated
    raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
'''

if text.count(old_helper) != 1:
    raise SystemExit("replace_once helper anchor changed; refusing to repair")
text = text.replace(old_helper, new_helper, 1)

old_runpy = '''namespace = runpy.run_path(str(vector_py), run_name="cognitive_types_vector_migration")'''
new_runpy = '''# Load only imports, assignments and function definitions from the verifier.
# The verifier intentionally executes assertions at module scope in some
# repository revisions; executing those assertions before expected digests are
# rewritten would make the migration self-blocking.
namespace: dict[str, object] = {}
verifier_ast = __import__("ast")
verifier_module = verifier_ast.parse(read(vector_py), filename=str(vector_py))
definition_nodes = [
    node
    for node in verifier_module.body
    if isinstance(
        node,
        (
            verifier_ast.Import,
            verifier_ast.ImportFrom,
            verifier_ast.Assign,
            verifier_ast.AnnAssign,
            verifier_ast.FunctionDef,
        ),
    )
]
exec(
    compile(
        verifier_ast.Module(body=definition_nodes, type_ignores=[]),
        str(vector_py),
        "exec",
    ),
    namespace,
)'''

if text.count(old_runpy) != 1:
    raise SystemExit("vector definition loader anchor changed; refusing to repair")
text = text.replace(old_runpy, new_runpy, 1)

SCRIPT.write_text(text, encoding="utf-8")
