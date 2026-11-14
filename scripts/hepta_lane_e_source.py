"""Bounded qualification-item proof for the Lane E source guard.

This is deliberately not Rust macro expansion or Cargo build qualification.
Unproved syntax retains the original raw-token check. Source includes must be
literal so archived source cannot silently reenter through an opaque expression.
"""

import json
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the scripts project's locked dependency.
    import tomli as tomllib

AGENT = "codex-hepta-agentd"
LEDGER = "codex-hepta-learning-ledger"
FEATURE = "qualification-legacy-learning-write"
LEDGER_FEATURE = "qualification-legacy-write"
CUSTODY = Path("library-recovery/lane-e-unwired-objective-03ec")
_CFG = ("cfg", "(", "feature", "=", f'"{FEATURE}"', ")")
_ALLOW = ("allow", "(", "clippy", ":", ":", "too_many_arguments", ")")

_RAW = re.compile(r'(?:br|cr|r)(#{0,255})"')
_QUOTED = re.compile(r'(?:b|c)?"')
_CHAR = re.compile(r"b?'(?:\\(?:u\{[0-9A-Fa-f_]+\}|x[0-9A-Fa-f]{2}|[^\n])|[^'\\\n])'")
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def rust_tokens(source: str) -> tuple[list[tuple[str, int, int]], dict[int, int]]:
    """Retain token spans; comments/literals never contribute brace tokens."""
    tokens = []
    pairs = {}
    stack = []
    i = 0
    while i < len(source):
        start = i
        if source[i].isspace():
            i += 1
            continue
        if source.startswith("//", i):
            i = source.find("\n", i)
            if i < 0:
                break
            continue
        if source.startswith("/*", i):
            i, nesting = i + 2, 1
            while i < len(source) and nesting:
                if source.startswith("/*", i):
                    nesting, i = nesting + 1, i + 2
                elif source.startswith("*/", i):
                    nesting, i = nesting - 1, i + 2
                else:
                    i += 1
            if nesting:
                raise ValueError("unterminated block comment")
            continue
        raw = _RAW.match(source, i)
        quoted = _QUOTED.match(source, i)
        char = _CHAR.match(source, i)
        if raw:
            closing = '"' + raw.group(1)
            close = source.find(closing, raw.end())
            if close < 0:
                raise ValueError("unterminated raw string")
            i = close + len(closing)
        elif quoted:
            i = quoted.end()
            while i < len(source) and source[i] != '"':
                i += 2 if source[i] == "\\" else 1
            if i >= len(source):
                raise ValueError("unterminated string")
            i += 1
        elif char:
            i = char.end()
        else:
            word = _WORD.match(source, i)
            i = word.end() if word else i + 1
        value = source[start:i]
        index = len(tokens)
        tokens.append((value, start, i))
        if value in ("(", "[", "{"):
            stack.append(index)
        elif value in (")", "]", "}"):
            if (
                not stack
                or tokens[stack[-1]][0] != {")": "(", "]": "[", "}": "{"}[value]
            ):
                raise ValueError("unbalanced token group")
            opening = stack.pop()
            pairs[opening] = index
    if stack:
        raise ValueError("unclosed token group")
    return tokens, pairs


def mask_qualification_items(source: str) -> str:
    """Mask complete positively gated use/fn items, never adjacent source.

    Only root items and methods in a plain, unattributed inherent impl are
    recognized. Unknown attributes/macros/scopes cannot earn an exemption.
    """
    try:
        tokens, pairs = rust_tokens(source)
        values = [token[0] for token in tokens]
        if any(values[i : i + 3] == ["#", "!", "["] for i in range(len(values) - 2)):
            return source
        spans = []

        def items(start: int, end: int) -> None:
            i = start
            while i < end:
                if values[i] == ";":
                    i += 1
                    continue
                first = i
                attributes = []
                while i + 1 < end and values[i : i + 2] == ["#", "["]:
                    close = pairs[i + 1]
                    attributes.append(tuple(values[i + 2 : close]))
                    i = close + 1
                header = i
                # Rust visibility and the limited function qualifiers are inert.
                if i < end and values[i] == "pub":
                    i += 1
                    if i < end and values[i] == "(":
                        i = pairs[i] + 1
                while i < end and values[i] in ("async", "unsafe", "const"):
                    i += 1
                kind = values[i] if i < end else ""
                cursor = i
                body = None
                while cursor < end:
                    token = values[cursor]
                    if token == ";":
                        finish = cursor + 1
                        break
                    if token == "{" and kind != "use":
                        body = cursor
                        finish = pairs[cursor] + 1
                        break
                    if token in ("(", "[", "{"):
                        cursor = pairs[cursor] + 1
                    else:
                        cursor += 1
                else:
                    raise ValueError("cannot bound complete item")
                qualified = attributes.count(_CFG) == 1 and all(
                    attribute in (_CFG, _ALLOW) for attribute in attributes
                )
                if qualified and kind in ("fn", "use"):
                    spans.append((tokens[first][1], tokens[finish - 1][2]))
                elif (
                    not attributes
                    and body is not None
                    and values[header:body]
                    == ["impl", "AgentdIntelligenceProductRunnerV1"]
                ):
                    items(body + 1, pairs[body])
                i = finish

        items(0, len(tokens))
        masked = list(source)
        for start, end in spans:
            masked[start:end] = ["\n" if c == "\n" else " " for c in source[start:end]]
        return "".join(masked)
    except (ValueError, KeyError, IndexError):
        return source


def qualification_is_nondefault(root: Path) -> bool:
    """Conservatively close local default/normal dependency feature activation.

    All local packages are possible default roots; optional and target normal
    dependencies are included conservatively. Dev dependencies are not product
    activation. Unknown metadata cannot authorize a source exemption.
    """
    try:
        manifests = {}
        for path in sorted((root / "codex-rs").rglob("Cargo.toml")):
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            if "package" in data:
                if any(
                    not isinstance(items, list)
                    or not all(isinstance(item, str) for item in items)
                    for items in data.get("features", {}).values()
                ):
                    return False
                manifests[path.parent.resolve()] = data
        workspace = tomllib.loads(
            (root / "codex-rs/Cargo.toml").read_text(encoding="utf-8")
        )
        inherited = workspace.get("workspace", {}).get("dependencies", {})
        agent = (root / "codex-rs/hepta-agentd").resolve()
        ledger = (root / "codex-rs/hepta-learning-ledger").resolve()
        if manifests[agent]["package"]["name"] != AGENT:
            return False
        if manifests[ledger]["package"]["name"] != LEDGER:
            return False
        if manifests[agent].get("features", {}).get(FEATURE) != [
            f"{LEDGER}/{LEDGER_FEATURE}"
        ]:
            return False
        by_name = {}
        for path, data in manifests.items():
            by_name.setdefault(data["package"]["name"], []).append(path)

        def dependencies(path: Path) -> dict[str, list[tuple[Path, dict]]]:
            data = manifests[path]
            result = {}
            tables = [data, *data.get("target", {}).values()]
            for table in tables:
                for category in ("dependencies", "build-dependencies"):
                    for alias, original in table.get(category, {}).items():
                        spec = (
                            {"version": original}
                            if isinstance(original, str)
                            else dict(original)
                        )
                        origin = path
                        if spec.get("workspace"):
                            parent = inherited[alias]
                            parent = (
                                {"version": parent}
                                if isinstance(parent, str)
                                else dict(parent)
                            )
                            features = [
                                *parent.get("features", []),
                                *spec.get("features", []),
                            ]
                            default = parent.get("default-features", True) or spec.get(
                                "default-features", True
                            )
                            spec = {
                                **parent,
                                **spec,
                                "features": features,
                                "default-features": default,
                            }
                            origin = (root / "codex-rs").resolve()
                        if "path" in spec:
                            target = (origin / spec["path"]).resolve()
                            if target not in manifests:
                                raise ValueError("unindexed local dependency path")
                            targets = [target]
                        else:
                            targets = by_name.get(spec.get("package", alias), [])
                        result.setdefault(alias, []).extend(
                            (target, spec) for target in targets
                        )
            return result

        dependency_map = {path: dependencies(path) for path in manifests}

        def activation(roots: list[Path]) -> set[tuple[Path, str]]:
            pending = [(path, "default") for path in roots]
            seen = set()
            opened = set()
            while pending:
                path, feature = pending.pop()
                if (path, feature) in seen:
                    continue
                seen.add((path, feature))
                deps = dependency_map[path]
                if path not in opened:
                    opened.add(path)
                    for targets in deps.values():
                        for target, spec in targets:
                            pending.append((target, ""))
                            if spec.get("default-features", True):
                                pending.append((target, "default"))
                            pending.extend(
                                (target, item) for item in spec.get("features", [])
                            )
                for item in manifests[path].get("features", {}).get(feature, []):
                    if "/" in item:
                        alias, requested = item.split("/", 1)
                        pending.extend(
                            (target, requested)
                            for target, _ in deps.get(alias.rstrip("?"), [])
                        )
                    elif not item.startswith("dep:"):
                        pending.append((path, item))
            return seen

        all_defaults = activation(list(manifests))
        agent_defaults = activation([agent])
        return (
            (agent, FEATURE) not in all_defaults
            and (ledger, LEDGER_FEATURE) not in all_defaults
            and (ledger, LEDGER_FEATURE) not in agent_defaults
            and (ledger, LEDGER_FEATURE) not in activation([ledger])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def is_agentd_source(path: Path, root: Path) -> bool:
    """A cfg feature belongs to the compiling package, not a path prefix."""
    for parent in path.parents:
        if (parent / "Cargo.toml").is_file():
            return parent.resolve() == (root / "codex-rs/hepta-agentd").resolve()
    return False


def source_import_errors(source: str, path: Path, root: Path) -> list[str]:
    """Reject custody/cross-package imports and unproved include paths."""
    if "include" not in source and "path" not in source:
        return []
    try:
        tokens, pairs = rust_tokens(source)
    except ValueError:
        # The caller retains its raw scan; malformed imports must not pass it.
        return (
            ["unproved source-import syntax"]
            if re.search(r"\binclude\s*!|#\s*\[", source)
            else []
        )
    values = [token[0] for token in tokens]
    errors = []

    def check_literal(parts: list[str]) -> None:
        if len(parts) != 1:
            errors.append("non-literal source import")
            return
        literal = parts[0]
        try:
            raw = re.fullmatch(r'r(#{0,255})"(.*)"\1', literal, re.DOTALL)
            value = raw.group(2) if raw else json.loads(literal)
            if not isinstance(value, str):
                raise ValueError("not a string")
        except (ValueError, TypeError):
            errors.append("unproved source-import literal")
            return
        destination = (path.parent / value).resolve()
        if destination.is_relative_to(
            (root / "codex-rs/hepta-agentd").resolve()
        ) and not is_agentd_source(path, root):
            errors.append(
                "cross-package Agentd source import has unproved cfg ownership"
            )
        if (
            destination.is_relative_to((root / CUSTODY).resolve())
            or CUSTODY.as_posix() in value.replace("\\", "/")
            or Path(value).name in ("objective_ingress.rs", "objective_dispatch.rs")
        ):
            errors.append("archived Objective source reintroduced")

    def attribute(start: int, end: int) -> None:
        if values[start : start + 2] == ["r", "#"]:
            start += 2
        if start >= end:
            return
        if values[start] == "path":
            if values[start + 1 : start + 2] != ["="]:
                errors.append("unproved path attribute")
            else:
                check_literal(values[start + 2 : end])
        elif values[start : start + 2] == ["cfg_attr", "("]:
            opening = start + 1
            if pairs[opening] != end - 1:
                errors.append("unproved cfg_attr source path")
                return
            # Only cfg_attr arguments are attributes; e.g. tracing fields(path =
            # ?value) is data for another attribute, not a Rust module path.
            cursor = segment = opening + 1
            argument = 0
            while cursor <= end - 1:
                if cursor == end - 1 or values[cursor] == ",":
                    if argument and segment < cursor:
                        attribute(segment, cursor)
                    argument += 1
                    segment = cursor + 1
                if cursor < end - 1 and values[cursor] in ("(", "[", "{"):
                    cursor = pairs[cursor] + 1
                else:
                    cursor += 1

    for index, value in enumerate(values):
        if values[index : index + 2] == ["#", "["]:
            attribute(index + 2, pairs[index + 1])
        if value == "include" and values[index + 1 : index + 2] == ["!"]:
            opening = index + 2
            if opening not in pairs:
                errors.append("unproved include expression")
            else:
                check_literal(values[opening + 1 : pairs[opening]])
    return errors
