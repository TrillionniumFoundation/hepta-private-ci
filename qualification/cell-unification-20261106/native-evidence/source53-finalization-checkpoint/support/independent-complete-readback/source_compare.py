"""Pure-data patch/token reader. Does not import or execute any project code."""
from __future__ import annotations

import ast
import difflib
import hashlib
import io
import json
import re
import tarfile
from pathlib import PurePosixPath


def pin(raw: bytes) -> dict:
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_tar(raw: bytes) -> tuple[dict, list]:
    contents, members = {}, []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts and str(path) == member.name,
                    "unsafe archive name: " + member.name)
            require(member.isfile() and not member.issym() and not member.islnk(),
                    "nonregular archive member: " + member.name)
            require(member.name not in contents, "duplicate archive member")
            data = archive.extractfile(member).read()
            require(len(data) == member.size, "tar size differs")
            contents[member.name] = data
            members.append({"path": member.name, "mode": format(member.mode, "o"),
                            "mtime": member.mtime, **pin(data)})
    return contents, members


def parse_patch(raw: bytes) -> list[dict]:
    """Parse only ordinary full-index same-path Git text diffs; fail on anything else."""
    if not raw:
        return []
    lines = raw.splitlines(keepends=True)
    sections, current = [], None
    for line in lines:
        if line.startswith(b"diff --git "):
            match = re.fullmatch(rb"diff --git a/([^\r\n ]+) b/([^\r\n ]+)\n", line)
            require(match and match[1] == match[2], "unexpected rename/quoted diff path")
            path = match[1].decode("utf-8")
            require(".." not in PurePosixPath(path).parts and not path.startswith("/"), "unsafe patch path")
            current = {"path": path, "lines": [], "hunks": []}
            sections.append(current)
        else:
            require(current is not None, "patch bytes before first diff")
            current["lines"].append(line)
    require(len({x["path"] for x in sections}) == len(sections), "duplicate patch path")
    for section in sections:
        lines = section.pop("lines")
        match = re.fullmatch(rb"index ([a-f0-9]{40})\.\.([a-f0-9]{40}) (100644|100755)\n", lines[0])
        require(match is not None, "not an ordinary full-index same-mode patch")
        section.update(before_blob=match[1].decode(), after_blob=match[2].decode(), mode=match[3].decode())
        require(lines[1] == ("--- a/" + section["path"] + "\n").encode(), "minus path")
        require(lines[2] == ("+++ b/" + section["path"] + "\n").encode(), "plus path")
        hunk = None
        for line in lines[3:]:
            if line.startswith(b"@@ "):
                match = re.match(rb"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:[^\n]*)\n$", line)
                require(match is not None, "invalid hunk header")
                hunk = {"old_start": int(match[1]), "old_count": int(match[2] or b"1"),
                        "new_start": int(match[3]), "new_count": int(match[4] or b"1"), "body": []}
                section["hunks"].append(hunk)
            elif line == b"\\ No newline at end of file\n":
                require(hunk and hunk["body"] and hunk["body"][-1][1].endswith(b"\n"), "bad no-newline marker")
                op, old = hunk["body"][-1]
                hunk["body"][-1] = (op, old[:-1])
            else:
                require(hunk and line[:1] in (b" ", b"+", b"-"), "unexpected patch body")
                hunk["body"].append((line[:1], line[1:]))
        for hunk in section["hunks"]:
            require(sum(op != b"+" for op, _ in hunk["body"]) == hunk["old_count"], "old hunk length")
            require(sum(op != b"-" for op, _ in hunk["body"]) == hunk["new_count"], "new hunk length")
    return sections


def apply_section(raw: bytes, section: dict, reverse: bool = False) -> bytes:
    old_lines = raw.splitlines(keepends=True)
    cursor, output = 0, []
    for hunk in section["hunks"]:
        start = hunk["new_start" if reverse else "old_start"]
        count = hunk["new_count" if reverse else "old_count"]
        index = start - 1 if count else start
        require(index >= cursor, "overlapping hunks")
        output.extend(old_lines[cursor:index]); cursor = index
        for op, data in hunk["body"]:
            if reverse:
                op = {b"+": b"-", b"-": b"+", b" ": b" "}[op]
            if op in (b" ", b"-"):
                require(cursor < len(old_lines) and old_lines[cursor] == data,
                        "hunk context mismatch: " + section["path"] + ":" + str(cursor + 1))
                cursor += 1
            if op in (b" ", b"+"):
                output.append(data)
    output.extend(old_lines[cursor:])
    return b"".join(output)


def check_patch(raw: bytes, before: dict[str, bytes], after: dict[str, bytes]) -> list[dict]:
    sections = parse_patch(raw)
    changed = {path for path in before if before[path] != after[path]}
    require(set(before) == set(after), "source path set changed")
    require({s["path"] for s in sections} == changed, "patch does not exactly cover changed source bytes")
    rows = []
    for section in sections:
        path = section["path"]
        require(pin(before[path])["git_blob"] == section["before_blob"], "before blob header mismatch")
        require(pin(after[path])["git_blob"] == section["after_blob"], "after blob header mismatch")
        require(apply_section(before[path], section) == after[path], "forward patch mismatch")
        require(apply_section(after[path], section, reverse=True) == before[path], "reverse patch mismatch")
        rows.append({"path": path, "hunks": len(section["hunks"]), "mode": section["mode"],
                     "before": pin(before[path]), "after": pin(after[path]), "forward_exact": True,
                     "reverse_exact": True})
    return rows


def rust_tokens(raw: bytes) -> list[str]:
    """Lexical review only, not a Rust compiler/parser. Preserve literal token contents."""
    text = raw.decode("utf-8")
    tokens, i, n = [], 0, len(text)
    punctuation = sorted(["<<=", ">>=", "...", "..=", "::", "->", "=>", "==", "!=", "<=", ">=",
                          "&&", "||", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", ".."],
                         key=len, reverse=True)
    while i < n:
        if text[i].isspace():
            i += 1; continue
        if text.startswith("//", i):
            end = text.find("\n", i); i = n if end < 0 else end + 1; continue
        if text.startswith("/*", i):
            level, j = 1, i + 2
            while j < n and level:
                if text.startswith("/*", j): level += 1; j += 2
                elif text.startswith("*/", j): level -= 1; j += 2
                else: j += 1
            require(level == 0, "unclosed Rust block comment")
            i = j; continue
        raw_start = re.match(r'(?:br|cr|r)(#*)"', text[i:])
        if raw_start:
            closing = '"' + raw_start[1]
            end = text.find(closing, i + len(raw_start[0]))
            require(end >= 0, "unclosed raw string")
            end += len(closing); tokens.append(text[i:end]); i = end; continue
        prefix = 1 if text[i] in "bc" and i + 1 < n and text[i+1] in "\"'" else 0
        quote_index = i + prefix
        if quote_index < n and text[quote_index] == '"':
            j = quote_index + 1
            while j < n:
                if text[j] == "\\": j += 2
                elif text[j] == '"': j += 1; break
                else: j += 1
            require(j <= n and text[j-1] == '"', "unclosed quoted string")
            tokens.append(text[i:j]); i = j; continue
        if quote_index < n and text[quote_index] == "'":
            # A character has one scalar/escape followed by a closing quote; lifetimes do not.
            j = quote_index + 1
            if j < n and text[j] == "\\":
                if j + 1 < n and text[j+1] == "u" and j + 2 < n and text[j+2] == "{":
                    end = text.find("}", j+3); j = n if end < 0 else end + 1
                elif j + 1 < n and text[j+1] == "x": j += 4
                else: j += 2
            else: j += 1
            if j < n and text[j] == "'":
                tokens.append(text[i:j+1]); i = j + 1; continue
        match = re.match(r'(?:r#)?(?:[^\W\d]|_)[\w]*|[0-9][A-Za-z0-9_]*(?:\.[0-9][A-Za-z0-9_]*)?', text[i:], re.UNICODE)
        if match:
            tokens.append(match[0]); i += len(match[0]); continue
        operator = next((x for x in punctuation if text.startswith(x, i)), None)
        if operator:
            tokens.append(operator); i += len(operator)
        else:
            tokens.append(text[i]); i += 1
    return tokens


def lexical_deltas(before: bytes, after: bytes) -> dict:
    old, new = rust_tokens(before), rust_tokens(after)
    deltas = []
    if old != new:
        matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        for tag, i, j, k, l in matcher.get_opcodes():
            if tag != "equal":
                deltas.append({"tag": tag, "old_index": [i, j], "new_index": [k, l],
                               "before": old[i:j], "after": new[k:l],
                               "old_context_before": old[max(0,i-12):i],
                               "old_context_after": old[j:j+12]})
    return {"before_token_count": len(old), "after_token_count": len(new),
            "exact_token_equality": old == new, "deltas": deltas}


def python_ast_readback(before: bytes, after: bytes) -> dict:
    old = ast.dump(ast.parse(before), include_attributes=False)
    new = ast.dump(ast.parse(after), include_attributes=False)
    return {"ast_equal": old == new, "before_ast_sha256": hashlib.sha256(old.encode()).hexdigest(),
            "after_ast_sha256": hashlib.sha256(new.encode()).hexdigest(),
            "scope": "Python AST comparison only; neither module imported or executed"}


def top_level_declarations(tokens: list[str]) -> tuple[list[tuple], list[str]]:
    """Separate top-level use/mod declarations, retaining their exact attached attributes."""
    declarations, residual, i, depth = [], [], 0, 0
    n = len(tokens)
    while i < n:
        start, j = i, i
        if depth == 0:
            while j + 1 < n and tokens[j:j+2] == ["#", "["]:
                j += 2; brackets = 1
                while j < n and brackets:
                    if tokens[j] == "[": brackets += 1
                    elif tokens[j] == "]": brackets -= 1
                    j += 1
            if j < n and tokens[j] == "pub":
                j += 1
                if j < n and tokens[j] == "(":
                    j += 1; parens = 1
                    while j < n and parens:
                        if tokens[j] == "(": parens += 1
                        elif tokens[j] == ")": parens -= 1
                        j += 1
            if j < n and tokens[j] == "mod" and j + 2 < n and tokens[j+2] == ";":
                end = j + 3
                declarations.append(tuple(tokens[start:end])); i = end; continue
            if j < n and tokens[j] == "use":
                end, nest = j + 1, 0
                while end < n:
                    token = tokens[end]
                    if token in ("{", "(", "["): nest += 1
                    elif token in ("}", ")", "]"): nest -= 1
                    if token == ";" and nest == 0:
                        end += 1; break
                    end += 1
                require(end <= n and tokens[end-1] == ";", "unclosed use declaration")
                declarations.append(tuple(tokens[start:end])); i = end; continue
        token = tokens[i]
        if token == "{": depth += 1
        elif token == "}": depth -= 1
        residual.append(token); i += 1
    require(depth == 0, "unbalanced file braces")
    return declarations, residual


def macro_oracles(tokens: list[str]) -> list[dict]:
    """Extract actual assert/panic macro token sequences; ignore punctuation commas only in this limited comparison."""
    records = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    for i in range(len(tokens)-2):
        name = tokens[i]
        if (name.startswith("assert") or name.startswith("debug_assert") or name in ("panic", "unreachable")) and tokens[i+1] == "!" and tokens[i+2] in pairs:
            stack, j = [pairs[tokens[i+2]]], i + 3
            while j < len(tokens) and stack:
                token = tokens[j]
                if token in pairs: stack.append(pairs[token])
                elif token in pairs.values():
                    require(stack[-1] == token, "macro delimiter mismatch")
                    stack.pop()
                j += 1
            require(not stack, "unclosed protected macro")
            body = tokens[i:j]
            normal = [t for t in body if t != ","]
            records.append({"name": name, "tokens_without_commas": normal})
    return records
