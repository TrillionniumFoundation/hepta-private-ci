"""Conservative source matching for methods on an explicit authority type.

Inputs are Rust with literals/comments/test items removed by the caller proof.
This is not a Rust type checker: unsupported possible authority receivers fail
closed, while explicit unrelated receiver types do not create false owners.
"""

from __future__ import annotations

import re


class UnresolvedTypedReceiver(ValueError):
    pass


class AuthorityFields(dict[tuple[str, str], str | None]):
    def __init__(self, aliases: frozenset[str]):
        super().__init__()
        self.aliases = aliases
        self.owners: frozenset[str] = frozenset()


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
    """Keep declared owner chains across split modules; no receiver-name allowlist."""
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
    declarations: dict[tuple[str, str], set[str]] = {}
    for code in source_index.values():
        code = _normalize_aliases(code, target, fields.aliases)
        for declaration in re.finditer(r"\bstruct\s+(\w+)(?:\s*<[^{};]*>)?\s*\{", code):
            end = _end(code, declaration.end() - 1, "{", "}")
            for field in re.finditer(
                r"\b(\w+)\s*:\s*([^,;{}]+)", code[declaration.end() : end]
            ):
                type_name = _type(field.group(2), target)
                if type_name:
                    key = (declaration.group(1), field.group(1))
                    declarations.setdefault(key, set()).add(type_name)
    reachable = {target}
    while True:
        owners = {
            owner
            for (owner, _), types in declarations.items()
            if types & reachable
        }
        if owners <= reachable:
            break
        reachable.update(owners)
    fields.owners = frozenset(reachable - {target})
    for key, types in declarations.items():
        if key[0] in reachable:
            # Same short owner/field names in different modules must not let
            # an unrelated declaration overwrite a possible authority origin.
            fields[key] = next(iter(types)) if len(types) == 1 else None
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
    fields: dict[tuple[str, str], str | None],
) -> str | None:
    parts = re.sub(r"\s+", "", receiver).split(".")
    current = owner if parts[0] == "self" else bindings.get(parts[0])
    for field in parts[1:]:
        current = fields.get((current, field)) if current else None
    return current


def _field_alias_type(
    expression: str,
    bindings: dict[str, str | None],
    owner: str | None,
    fields: dict[tuple[str, str], str | None],
) -> str | None:
    """Resolve fields through fixed borrow/clone and fallible error adapters.

    A transform/factory is never inferred from its receiver's type. The error
    adapters only preserve their success value and must propagate the error;
    fallback, map and arbitrary method bodies remain unresolved.
    """
    start = re.match(r"\s*&?\s*(?:mut\s+)?([A-Za-z_]\w*)", expression)
    if start is None:
        return None
    current = _receiver_type(start.group(1), bindings, owner, fields)
    position = start.end()
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        field = re.match(r"\.\s*([A-Za-z_]\w*)\s*", expression[position:])
        if field is None:
            return None
        name = field.group(1)
        position += field.end()
        if position >= len(expression) or expression[position] != "(":
            current = fields.get((current, name)) if current else None
            continue
        end = _end(expression, position, "(", ")")
        arguments = expression[position + 1 : end]
        position = end + 1
        if name in {"clone", "as_ref", "borrow", "deref"} and not arguments.strip():
            continue
        if name in {"ok_or", "ok_or_else", "map_err"} and arguments.strip():
            while position < len(expression) and expression[position].isspace():
                position += 1
            if position < len(expression) and expression[position] == "?":
                position += 1
                continue
        return None
    return current


def _initializers(scope: str):
    """Yield completed let initializers without splitting nested expressions.

    The current authority call can itself be inside an initializer. That new
    binding is not in scope yet, and its unfinished prefix must not be parsed
    as a field alias. Semicolons in method arguments and closure/block bodies
    likewise do not finish the containing let statement.
    """
    declaration = re.compile(
        r"\blet\s+(?:mut\s+)?(\w+)(?:\s*:\s*([^=;]+))?\s*=\s*"
    )
    cursor = 0
    while assignment := declaration.search(scope, cursor):
        stack = []
        cursor = assignment.end()
        for position in range(cursor, len(scope)):
            char = scope[position]
            if char in "([{":
                stack.append({"(": ")", "[": "]", "{": "}"}[char])
            elif char in ")]}" and (not stack or stack.pop() != char):
                break
            elif char == ";" and not stack:
                yield (*assignment.groups(), scope[cursor:position])
                # Declarations inside a completed initializer belong to its
                # nested scopes, not to the subsequent authority call.
                cursor = position + 1
                break


def _bindings(
    code: str,
    position: int,
    target: str,
    owner: str | None,
    fields: dict[tuple[str, str], str | None],
) -> dict[str, str | None]:
    scope = code[_function_start(code, position) : position]
    bindings = {}
    for parameter in re.finditer(r"\b(\w+)\s*:\s*([^,;={}]+)", scope):
        bindings[parameter.group(1)] = _type(parameter.group(2), target)
    for name, annotation, expression in _initializers(scope):
        if annotation:
            bindings[name] = _type(annotation, target)
            continue
        # Standard shared-owner cloning preserves the wrapped receiver type.
        # Treat an opaque clone argument as unresolved, never as an unrelated
        # `Arc`/`Rc` constructor that could silently hide an authority call.
        shared_clone = re.match(
            r"\s*(?:std\s*::\s*(?:sync|rc)\s*::\s*)?(?:Arc|Rc)\s*::\s*clone\s*\(",
            expression,
        )
        if shared_clone:
            argument = re.fullmatch(
                r"\s*&?\s*((?:self|[A-Za-z_]\w*)(?:\s*\.\s*\w+)*)\s*\)\s*",
                expression[shared_clone.end() :],
            )
            bindings[name] = (
                _receiver_type(argument.group(1), bindings, owner, fields)
                if argument
                else None
            )
            continue
        constructor = re.match(
            r"(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*::\s*\w+\s*\(", expression
        )
        if constructor:
            bindings[name] = constructor.group(1)
            continue
        bindings[name] = _field_alias_type(expression, bindings, owner, fields)
    return bindings


def has_authority_call(
    code: str, target: str, method: str, fields: AuthorityFields
) -> bool:
    code = _normalize_aliases(code, target, fields.aliases)
    # The field index is derived from type declarations, including declarations
    # in a parent module. A typed variable/impl must name either the authority
    # or an indexed field owner. Avoid parsing unrelated crates' homonyms.
    type_names = {target, *fields.owners}
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
