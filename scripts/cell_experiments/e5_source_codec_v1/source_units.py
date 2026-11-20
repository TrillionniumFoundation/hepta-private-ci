"""Inventory complete original source units without executing or rewriting code."""

import ast
import hashlib
import io
import tokenize


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def names(node):
    """Keep every lexical load; nested scopes must never erase outer globals.

    This deliberately over-approximates references. The context resolver checks
    actual module/class bindings; even builtin names may be shadowed there.
    """
    return sorted(
        {
            n.id
            for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        }
    )


def declarations(node):
    result = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    for item in ast.walk(node):
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
            result.add(item.id)
        elif isinstance(item, (ast.Import, ast.ImportFrom)):
            result.update(
                alias.asname or alias.name.split(".")[0] for alias in item.names
            )
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(item.name)
    return sorted(result)


def inventory(path, raw):
    if not isinstance(raw, bytes) or len(raw) > 32 * 1024**2 or b"\x00" in raw:
        raise ValueError("source bytes must be bounded and contain no NUL")
    text = raw.decode("utf-8")
    lines = raw.splitlines(keepends=True)
    if b"".join(lines) != raw:
        raise ValueError("source line partition failed")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    units = []

    def add(
        start, end, kind, qualname, exports, refs, attributes, parent=None, imports=None
    ):
        if not 0 <= start < end <= len(lines):
            raise ValueError("source unit has invalid complete line bounds")
        units.append(
            {
                "path": path,
                "start_line": start,
                "end_line": end,
                "kind": kind,
                "qualname": qualname,
                "exports": sorted(set(exports)),
                "references": sorted(set(refs)),
                "attributes": sorted(set(attributes)),
                "parent_class": parent,
                "imports": imports or [],
                "text": b"".join(lines[start:end]).decode("utf-8"),
            }
        )

    if path.endswith(".py"):
        tree = ast.parse(text, filename=path)

        def visit(body, scope="", parent=None):
            for ordinal, node in enumerate(body):
                start = (
                    min(
                        [
                            node.lineno,
                            *[d.lineno for d in getattr(node, "decorator_list", [])],
                        ]
                    )
                    - 1
                )
                end = node.end_lineno
                exports = declarations(node)
                label = (
                    getattr(node, "name", None)
                    or ",".join(exports)
                    or f"{type(node).__name__}:{ordinal}"
                )
                qualname = scope + label
                attrs = [n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)]
                imports = []
                for item in ast.walk(node):
                    if isinstance(item, ast.Import):
                        imports += [
                            {
                                "module": a.name,
                                "name": None,
                                "alias": a.asname or a.name.split(".")[0],
                                "level": 0,
                            }
                            for a in item.names
                        ]
                    elif isinstance(item, ast.ImportFrom):
                        imports += [
                            {
                                "module": item.module or "",
                                "name": a.name,
                                "alias": a.asname or a.name,
                                "level": item.level,
                            }
                            for a in item.names
                        ]
                if isinstance(node, ast.ClassDef) and node.body[0].lineno > node.lineno:
                    first = node.body[0]
                    header_end = (
                        min(
                            [
                                first.lineno,
                                *[
                                    d.lineno
                                    for d in getattr(first, "decorator_list", [])
                                ],
                            ]
                        )
                        - 1
                    )
                    header_nodes = [*node.bases, *node.keywords, *node.decorator_list]
                    refs = {name for item in header_nodes for name in names(item)}
                    add(
                        start,
                        header_end,
                        "class_header",
                        qualname,
                        [node.name],
                        refs,
                        [],
                        parent,
                    )
                    visit(node.body, qualname + ".", qualname)
                else:
                    kind = (
                        "function"
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        else "statement"
                    )
                    add(
                        start,
                        end,
                        kind,
                        qualname,
                        exports,
                        names(node),
                        attrs,
                        parent,
                        imports,
                    )

        visit(tree.body)
    elif path.endswith(".pyx"):
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        depth, start_token, start_line = 0, None, None
        ordinal = 0
        for i, token in enumerate(tokens):
            if start_token is None and token.type not in (
                tokenize.ENCODING,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.COMMENT,
                tokenize.ENDMARKER,
                tokenize.DEDENT,
            ):
                start_token, start_line = i, token.start[0] - 1
            if token.type == tokenize.INDENT:
                depth += 1
            elif token.type == tokenize.DEDENT:
                depth -= 1
            if start_token is None:
                continue
            finished = token.type == tokenize.DEDENT and depth == 0
            if token.type == tokenize.NEWLINE and depth == 0:
                following = i + 1
                while following < len(tokens) and tokens[following].type in (
                    tokenize.NL,
                    tokenize.COMMENT,
                ):
                    following += 1
                finished = (
                    following == len(tokens)
                    or tokens[following].type != tokenize.INDENT
                )
                # A decorator belongs to the following complete function.
                first = tokens[start_token]
                if first.string == "@" and not any(
                    t.string in ("def", "cpdef", "cdef")
                    for t in tokens[start_token : i + 1]
                ):
                    finished = False
            if finished:
                group = tokens[start_token : i + 1]
                header = group[
                    : next(
                        (j for j, t in enumerate(group) if t.type == tokenize.INDENT),
                        len(group),
                    )
                ]
                keyword = next(
                    (j for j, t in enumerate(header) if t.string in ("def", "cpdef")),
                    None,
                )
                opening = next(
                    (
                        j
                        for j, t in enumerate(header)
                        if t.string == "(" and keyword is not None and j > keyword
                    ),
                    None,
                )
                function = keyword is not None
                label = header[opening - 1].string if function and opening else None
                words = [t.string for t in group if t.type == tokenize.NAME]
                if label is None:
                    eq = next(
                        (j for j, t in enumerate(header) if t.string == "="), None
                    )
                    bound = (
                        [t.string for t in header[:eq] if t.type == tokenize.NAME]
                        if eq is not None
                        else []
                    )
                    label = bound[-1] if bound else f"cython_declaration:{ordinal}"
                end = (
                    token.start[0] - 1
                    if token.type == tokenize.DEDENT
                    else token.end[0]
                )
                add(
                    start_line,
                    min(end, len(lines)),
                    "cython_function" if function else "cython_declaration",
                    label,
                    [label],
                    words,
                    [],
                    None,
                )
                ordinal += 1
                start_token, start_line = None, None
        if start_token is not None or depth:
            raise ValueError("Cython logical boundary is incomplete")
    else:
        raise ValueError("only Python and Cython source units are supported")

    units.sort(key=lambda u: (u["start_line"], u["end_line"]))
    # Same physical-line statements are inseparable source, not two edit slots.
    merged = []
    for unit in units:
        if merged and unit["start_line"] < merged[-1]["end_line"]:
            previous = merged[-1]
            previous["end_line"] = max(previous["end_line"], unit["end_line"])
            previous["kind"] = "compound_line"
            for key in ("exports", "references", "attributes"):
                previous[key] = sorted(set(previous[key]) | set(unit[key]))
            previous["imports"] += unit["imports"]
            previous["text"] = b"".join(
                lines[previous["start_line"] : previous["end_line"]]
            ).decode()
        else:
            merged.append(unit)
    for ordinal, unit in enumerate(merged):
        unit["unit_id"] = f"{sha(path.encode())[:12]}:u{ordinal:04d}"
        unit["source_sha256"] = sha(raw)
        unit["text_sha256"] = sha(unit["text"].encode())
    return merged
