"""Observe registered native sources in the actual committed checkout.

Manifest blob IDs describe historical observations. Current identity comes from
Git HEAD, its tree and the bytes inspected here; neither proves product use.
"""

import hashlib
import io
import importlib.util
import json
import re
import subprocess
import tokenize
from functools import lru_cache
from pathlib import Path
from typing import Any


class BindingError(ValueError):
    """A registered source cannot be bound to this committed checkout."""


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, timeout=30
    )
    if result.returncode:
        raise BindingError("native binding Git read failed: " + " ".join(args))
    return result.stdout


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


@lru_cache(maxsize=1)
def _rust_lexer():
    # Repository checks share the reviewed masker; exported bundle checks do not
    # require repository scripts or load this helper.
    path = Path(__file__).resolve().parents[2] / "scripts/hepta_lane_e_writer_source.py"
    spec = importlib.util.spec_from_file_location("native_binding_rust_lexer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rust_code


def _rust_qualified_symbols(source: str) -> set[str]:
    """Locate direct inherent methods, without inferring types or active cfgs."""
    tokens = re.findall(r"[A-Za-z_]\w*|::|->|[^\s]", _rust_lexer()(source))
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}

    def close(start):
        opening, index = tokens[start], start + 1
        while index < len(tokens):
            token = tokens[index]
            if token == pairs[opening]:
                return index
            # Delimited const expressions and macro inputs are opaque even in
            # generics: their comparison operators cannot close an outer `<`.
            if token in {"(", "[", "{"} or (opening == "<" and token == "<"):
                index = close(index) + 1
            elif token in {")", "]", "}"}:
                raise ValueError("mismatched Rust source group")
            else:
                index += 1
        raise ValueError("unbalanced Rust source item")

    found = set()

    def items(start, end, modules, owner=None):
        index = start
        while index < end:
            token = tokens[index]
            if token == "mod" and owner is None and index + 2 < end and tokens[index + 2] == "{":
                closing = close(index + 2)
                items(index + 3, closing, modules + (tokens[index + 1],))
                index = closing + 1
                continue
            if token == "impl" and owner is None:
                cursor = index + 1
                if cursor < end and tokens[cursor] == "<":
                    cursor = close(cursor) + 1
                names = []
                if cursor < end and tokens[cursor].isidentifier():
                    names.append(tokens[cursor])
                    cursor += 1
                    while cursor + 1 < end and tokens[cursor] == "::" and tokens[cursor + 1].isidentifier():
                        names.append(tokens[cursor + 1])
                        cursor += 2
                if cursor < end and tokens[cursor] == "<":
                    cursor = close(cursor) + 1
                if cursor < end and tokens[cursor] == "where":
                    while cursor < end and tokens[cursor] != ";":
                        token = tokens[cursor]
                        if token in {"(", "[", "<"} or (token == "{" and tokens[cursor - 1] == "!"):
                            cursor = close(cursor) + 1
                        elif token == "{":
                            break
                        else:
                            cursor += 1
                if names and cursor < end and tokens[cursor] == "{":
                    closing = close(cursor)
                    items(cursor + 1, closing, modules, tuple(names))
                    index = closing + 1
                    continue
            if token == "fn" and index + 1 < end and tokens[index + 1].isidentifier():
                if owner is not None:
                    found.add("::".join(modules + owner + (tokens[index + 1],)))
                # A return-position `impl Trait` is not an inherent impl item.
                cursor = index + 2
                while cursor < end and tokens[cursor] not in {"{", ";"}:
                    if tokens[cursor] in {"(", "[", "<"}:
                        cursor = close(cursor) + 1
                    else:
                        cursor += 1
                index = close(cursor) + 1 if cursor < end and tokens[cursor] == "{" else cursor + 1
                continue
            # Bodies, macro inputs, attributes and function parameters are opaque.
            # Only explicit inline modules and inherent impls recurse above.
            if token in {"(", "[", "{"}:
                index = close(index) + 1
            else:
                index += 1

    items(0, len(tokens), ())
    return found


def source_symbol_exists(path: Path, data: bytes, symbol: str) -> bool:
    """Keep bare observations; qualified Rust names require structural ownership."""
    if not isinstance(symbol, str):
        return False
    if "::" not in symbol:
        return symbol.isidentifier() and symbol in identifiers(path, data)
    if path.suffix != ".rs" or re.fullmatch(r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)+", symbol) is None:
        return False
    try:
        return symbol in _rust_qualified_symbols(data.decode("utf-8"))
    except ValueError:
        return False


def identifiers(path: Path, data: bytes) -> set[str]:
    source = data.decode("utf-8")
    if path.suffix == ".py":
        return {
            token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.NAME
        }
    if path.suffix == ".rs":
        source = _rust_lexer()(source)
        return set(re.findall(r"\b[A-Za-z_]\w*\b", source))
    # Exclude comments and quoted strings from observed-identifier checks.
    # Compiler/native tests, rather than this structural check, own API validity.
    quoted = r"'(?:\\.|[^'\\\n])*'" if path.suffix != ".rs" else r"'(?:\\.|[^'\\])'"
    source = re.sub(
        r'//[^\n]*|/\*[\s\S]*?\*/|(?:br|r)(?P<marks>#+)"[\s\S]*?"(?P=marks)'
        r'|"(?:\\.|[^"\\])*"|' + quoted,
        " ",
        source,
    )
    return set(re.findall(r"\b[A-Za-z_]\w*\b", source))


def observe_native_bindings(
    root: Path, rows: list[dict[str, Any]], expected_modules: list[str]
) -> dict[str, Any]:
    """Bind each registered path, owner and observed symbol to one actual HEAD."""
    root = root.resolve()
    if (
        Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        != root
    ):
        raise BindingError("complete repository root required")
    source = git(root, "rev-parse", "HEAD").decode().strip()
    tree = git(root, "rev-parse", source + "^{tree}").decode().strip()
    registry_path = "docs/modules/SOURCE_BINDINGS.json"
    registry_data = git(root, "show", f"{source}:{registry_path}")
    if (root / registry_path).read_bytes() != registry_data:
        raise BindingError("uncommitted module ownership registry")
    ownership = {
        row["module"]: row["declaredRoots"]
        for row in json.loads(registry_data)["bindings"]
    }
    if (
        any(not isinstance(row, dict) for row in rows)
        or [row.get("module") for row in rows] != expected_modules
        or len(set(expected_modules)) != len(expected_modules)
    ):
        raise BindingError("native binding module coverage mismatch")
    observations = []
    for row in rows:
        module, relative = row["module"], row.get("path")
        historical, symbols = row.get("blobSha"), row.get("exports")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(historical, str)
            or re.fullmatch(r"[0-9a-f]{40}", historical) is None
            or not isinstance(symbols, list)
            or not symbols
            or any(
                not isinstance(symbol, str) or not symbol.isidentifier()
                for symbol in symbols
            )
        ):
            raise BindingError(f"{module}: invalid native binding row")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not any(
            path.is_relative_to((root / owned).resolve())
            for owned in ownership.get(module, [])
        ):
            raise BindingError(
                f"{module}: source outside declared module roots: {relative}"
            )
        data = path.read_bytes()
        if data != git(root, "show", f"{source}:{relative}"):
            raise BindingError(f"{module}: uncommitted native source: {relative}")
        missing = set(symbols) - identifiers(path, data)
        if missing:
            raise BindingError(
                f"{module}: missing native symbols in {relative}: {sorted(missing)}"
            )
        observations.append(
            {
                "module": module,
                "path": relative,
                "blobSha": git_blob(data),
                "historicalBlobSha": historical,
                "exports": symbols,
            }
        )
    if git(root, "rev-parse", "HEAD").decode().strip() != source:
        raise BindingError("checkout changed during native source observation")
    return {
        "sourceSha": source,
        "sourceTree": tree,
        "observations": observations,
        "consumerCallsitesProved": False,
        "productExecutionProved": False,
    }
