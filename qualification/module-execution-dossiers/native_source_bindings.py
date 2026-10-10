"""Observe registered native sources in the actual committed checkout.

Manifest blob IDs describe historical observations. Current identity comes from
Git HEAD, its tree and the bytes inspected here; neither proves product use.
"""

import hashlib
import io
import json
import re
import subprocess
import tokenize
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


def identifiers(path: Path, data: bytes) -> set[str]:
    source = data.decode("utf-8")
    if path.suffix == ".py":
        return {
            token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.NAME
        }
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
