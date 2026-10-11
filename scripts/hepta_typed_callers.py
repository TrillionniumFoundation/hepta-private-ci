"""Conservative source matching for methods on an explicit authority type.

Inputs are Rust with literals/comments/test items removed by the caller proof.
This is not a Rust type checker: unsupported possible authority receivers fail
closed, while explicit unrelated receiver types do not create false owners.
"""

from __future__ import annotations

import re


class UnresolvedTypedReceiver(ValueError):
    pass


class AuthorityFields(dict[tuple[str, str], str]):
    def __init__(self, aliases: frozenset[str]):
        super().__init__()
        self.aliases = aliases


def _end(code: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(code)):
        if code[index] == opening:
            depth += 1
        elif code[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    raise UnresolvedTypedReceiver("unbalanced Rust authority context")


def _declared_aliases(code: str, target: str) -> set[str]:
    aliases = set(re.findall(rf"\b{re.escape(target)}\s+as\s+(\w+)", code))
    aliases.update(
        re.findall(rf"\btype\s+(\w+)\s*=\s*(?:\w+::)*{re.escape(target)}\s*;", code)
    )
    return aliases


def _normalize_aliases(
    code: str, target: str, aliases: frozenset[str] = frozenset()
) -> str:
    aliases = aliases | _declared_aliases(code, target)
    for alias in aliases:
        code = re.sub(rf"\b{re.escape(alias)}\b", target, code)
    return code


def authority_fields(source_index: dict[str, str], target: str) -> AuthorityFields:
    """Keep typed fields across split impl modules; no variable-name allowlist."""
    aliases = {target}
    while True:
        discovered = {
            alias
            for code in source_index.values()
            for name in aliases
            for alias in _declared_aliases(code, name)
        }
        if discovered <= aliases:
            break
        aliases.update(discovered)
    fields = AuthorityFields(frozenset(aliases - {target}))
    for code in source_index.values():
        code = _normalize_aliases(code, target, fields.aliases)
        if target not in code:
            continue
        for declaration in re.finditer(r"\bstruct\s+(\w+)(?:\s*<[^{};]*>)?\s*\{", code):
            end = _end(code, declaration.end() - 1, "{", "}")
            for field in re.finditer(
                r"\b(\w+)\s*:\s*([^,;{}]+)", code[declaration.end() : end]
            ):
                type_name = _type(field.group(2), target)
                if type_name == target:
                    fields[declaration.group(1), field.group(1)] = target
    return fields


def _type(raw: str, target: str) -> str | None:
    if re.search(rf"\b{re.escape(target)}\b", raw):
        return target
    names = re.findall(r"\b[A-Za-z_]\w*\b", raw)
    names = [
        name for name in names if name not in {"mut", "pub", "crate", "self", "super"}
    ]
    return names[-1] if names else None


def _impl_owner(code: str, position: int) -> str | None:
    owner = None
    for match in re.finditer(
        r"\bimpl(?:\s*<[^{}]*>)?\s+(?:[\w:]+(?:\s*<[^{}]*>)?\s+for\s+)?([\w:]+)(?:\s*<[^{}]*>)?\s*\{",
        code[:position],
    ):
        if _end(code, match.end() - 1, "{", "}") >= position:
            owner = match.group(1).split("::")[-1]
    return owner


def _function_start(code: str, position: int) -> int:
    start = 0
    for match in re.finditer(r"\bfn\s+\w+", code[:position]):
        opening = code.find("(", match.end())
        if opening < 0:
            continue
        closing = _end(code, opening, "(", ")")
        brace = code.find("{", closing)
        semicolon = code.find(";", closing)
        if (
            brace >= 0
            and (semicolon < 0 or brace < semicolon)
            and _end(code, brace, "{", "}") >= position
        ):
            start = match.start()
    return start


def _receiver_type(
    receiver: str,
    bindings: dict[str, str | None],
    owner: str | None,
    fields: dict[tuple[str, str], str],
) -> str | None:
    parts = re.sub(r"\s+", "", receiver).split(".")
    current = owner if parts[0] == "self" else bindings.get(parts[0])
    for field in parts[1:]:
        current = fields.get((current, field)) if current else None
    return current


def _bindings(
    code: str,
    position: int,
    target: str,
    owner: str | None,
    fields: dict[tuple[str, str], str],
) -> dict[str, str | None]:
    scope = code[_function_start(code, position) : position]
    bindings = {}
    for parameter in re.finditer(r"\b(\w+)\s*:\s*([^,;={}]+)", scope):
        bindings[parameter.group(1)] = _type(parameter.group(2), target)
    for assignment in re.finditer(
        r"\blet\s+(?:mut\s+)?(\w+)(?:\s*:\s*([^=;]+))?\s*=\s*([^;]+)", scope
    ):
        name, annotation, expression = assignment.groups()
        if annotation:
            bindings[name] = _type(annotation, target)
            continue
        constructor = re.match(
            r"(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*::\s*\w+\s*\(", expression
        )
        if constructor:
            bindings[name] = constructor.group(1)
            continue
        alias = re.fullmatch(
            r"\s*&?\s*(?:mut\s+)?((?:[A-Za-z_]\w*)(?:\s*\.\s*\w+)*?)(?:\s*\.\s*(?:clone|as_ref|borrow|deref)\s*\(\s*\))?\s*",
            expression,
        )
        bindings[name] = (
            _receiver_type(alias.group(1), bindings, owner, fields) if alias else None
        )
    return bindings


def has_authority_call(
    code: str, target: str, method: str, fields: AuthorityFields
) -> bool:
    code = _normalize_aliases(code, target, fields.aliases)
    # The field index is derived from type declarations, including declarations
    # in a parent module. A typed variable/impl must name either the authority
    # or an indexed field owner. Avoid parsing unrelated crates' homonyms.
    type_names = {target, *(owner for owner, _ in fields)}
    if not any(re.search(rf"\b{re.escape(name)}\b", code) for name in type_names):
        return False
    qualified = rf"\b{re.escape(target)}\s*::\s*{re.escape(method)}\s*\("
    found = bool(re.search(qualified, code))
    potential = re.compile(rf"\.\s*{re.escape(method)}\s*\(")
    for call in potential.finditer(code):
        owner = _impl_owner(code, call.start())
        bindings = _bindings(code, call.start(), target, owner, fields)
        receiver = re.search(
            r"\b(?:self|[A-Za-z_]\w*)(?:\s*\.\s*\w+)*\s*$", code[: call.start()]
        )
        resolved = (
            _receiver_type(receiver.group(), bindings, owner, fields)
            if receiver
            else None
        )
        if resolved == target:
            found = True
        elif resolved is None:
            raise UnresolvedTypedReceiver(
                f"unresolved possible {target}::{method} receiver"
            )
    return found
