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


def _live_prefix(scope: str) -> str:
    """Keep the open lexical block chain, retaining closed block delimiters."""
    result = list(scope)
    stack = []
    for position, char in enumerate(scope):
        if char == "{":
            stack.append(position)
        elif char == "}":
            if not stack:
                raise UnresolvedTypedReceiver("unbalanced Rust authority scope")
            opening = stack.pop()
            result[opening + 1 : position] = [
                "\n" if value == "\n" else " "
                for value in scope[opening + 1 : position]
            ]
    return "".join(result)


def _parameter_types(parameters: str, target: str) -> dict[str, str | None]:
    parts = []
    stack = []
    start = 0
    for position, char in enumerate(parameters):
        if char in "([{<":
            stack.append({"(": ")", "[": "]", "{": "}", "<": ">"}[char])
        elif char in ")]}>":
            if char == ">" and position and parameters[position - 1] == "-":
                continue
            if not stack or stack.pop() != char:
                raise UnresolvedTypedReceiver("unsupported Rust parameter type")
        elif char == "," and not stack:
            parts.append(parameters[start:position])
            start = position + 1
    if stack:
        raise UnresolvedTypedReceiver("unbalanced Rust parameter type")
    parts.append(parameters[start:])
    bindings = {}
    for part in parts:
        parameter = re.fullmatch(
            r"\s*(?:(?:mut|ref)\s+)*(\w+)\s*(?::(.*))?\s*", part, re.DOTALL
        )
        if parameter:
            name, annotation = parameter.groups()
            bindings[name] = _type(annotation, target) if annotation else None
        else:
            # Destructured/untyped captures cannot inherit an unrelated outer
            # binding. Do not guess their type from a pattern or transform.
            bindings.update(_unknown_pattern(part))
    return bindings


def _unknown_pattern(pattern: str) -> dict[str, None]:
    """Invalidate possible names without pretending to type-check a pattern."""
    return dict.fromkeys(re.findall(r"\b\w+\b", pattern))


def _function_parameters(scope: str) -> str:
    declaration = re.match(r"\bfn\s+(?:r#)?\w+", scope)
    if declaration is None:
        return ""
    angle = 0
    for position in range(declaration.end(), len(scope)):
        char = scope[position]
        if char == "<":
            angle += 1
        elif char == ">" and scope[position - 1] != "-":
            angle -= 1
        elif char == "(" and angle == 0:
            return scope[position + 1 : _end(scope, position, "(", ")")]
    raise UnresolvedTypedReceiver("unresolved Rust function parameters")


def _closure_spans(scope: str) -> dict[int, int]:
    spans = {}
    cursor = 0
    while (opening := scope.find("|", cursor)) >= 0:
        stack = []
        cursor = opening + 1
        for position in range(cursor, len(scope)):
            char = scope[position]
            if char in "([{":
                stack.append({"(": ")", "[": "]", "{": "}"}[char])
            elif char in ")]}":
                if not stack or stack.pop() != char:
                    break
            elif char == "|" and not stack:
                spans[opening] = position
                cursor = position + 1
                break
            elif char == ";" and not stack:
                break
    return spans


def _expression_end(scope: str, position: int, spans: dict[int, int]) -> int | None:
    if position < len(scope) and scope[position] == "{":
        try:
            return _end(scope, position, "{", "}")
        except UnresolvedTypedReceiver:
            return None
    stack = []
    body_start = position
    while position < len(scope):
        if position in spans:
            position = spans[position] + 1
            continue
        char = scope[position]
        if char == "<" and (
            (stack and stack[-1] == ">")
            or re.search(r"(?:^|::|[=({,+*/!&|?:-])\s*$", scope[body_start:position])
        ):
            # Turbofish/qualified paths contain commas that do not finish
            # the closure. A comparison's `<` must not swallow its semicolon.
            stack.append(">")
        elif char == ">" and stack and stack[-1] == ">":
            if scope[position - 1] != "-":
                stack.pop()
        elif char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif char in ")]}":
            if not stack:
                return position
            if stack.pop() != char:
                raise UnresolvedTypedReceiver("unbalanced Rust closure body")
        elif char in ",;" and not stack:
            return position
        position += 1
    return None


def _closure_is_live(scope: str, closing: int, spans: dict[int, int]) -> bool:
    position = closing + 1
    while position < len(scope) and scope[position].isspace():
        position += 1
    if scope.startswith("->", position):
        stack = []
        for position in range(position + 2, len(scope)):
            char = scope[position]
            if char == "{" and not stack:
                break
            if char in "([{<":
                stack.append({"(": ")", "[": "]", "{": "}", "<": ">"}[char])
            elif char in ")]}>":
                if char == ">" and scope[position - 1] == "-":
                    continue
                if not stack or stack.pop() != char:
                    raise UnresolvedTypedReceiver("unsupported Rust closure result")
        else:
            raise UnresolvedTypedReceiver("unresolved Rust closure body")
    return _expression_end(scope, position, spans) is None


def _binding_header(scope: str, start: int) -> tuple[str, int] | None:
    stack = []
    for position in range(start, len(scope)):
        char = scope[position]
        if char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif char in ")]}":
            if not stack or stack.pop() != char:
                raise UnresolvedTypedReceiver("unsupported Rust binding pattern")
        elif char in "=;" and not stack:
            return scope[start:position].strip(), position
    return None


def _conditional_let(scope: str, position: int) -> bool:
    return bool(re.search(r"(?:\b(?:if|while)|&&)\s*$", scope[:position]))


def _control_body(scope: str, start: int) -> tuple[int | None, int | None]:
    """Find the body and earlier let-chain boundary, outside RHS groups."""
    while start < len(scope) and scope[start].isspace():
        start += 1
    if start < len(scope) and scope[start] == "{":
        # A block used as the scrutinee/iterator precedes the control body.
        try:
            start = _end(scope, start, "{", "}") + 1
        except UnresolvedTypedReceiver:
            return None, None
    stack = []
    chain = None
    for position in range(start, len(scope)):
        char = scope[position]
        if char == "{" and not stack:
            return position, chain
        if char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif char in ")]}":
            if not stack or stack.pop() != char:
                return None, chain
        elif char == ";" and not stack:
            return None, chain
        elif scope.startswith("&&", position) and not stack and chain is None:
            chain = position + 2
    return None, chain


def _pattern_scope_events(scope: str, spans: dict[int, int], original: str):
    for declaration in re.finditer(r"\blet\s+", scope):
        if not _conditional_let(scope, declaration.start()):
            continue
        header = _binding_header(scope, declaration.end())
        if header is None or scope[header[1]] != "=":
            continue
        _, delimiter = header
        pattern = original[declaration.end() : delimiter]
        body, chain = _control_body(scope, delimiter + 1)
        if body is not None and _expression_end(scope, body, spans) is not None:
            continue
        visible = chain if chain is not None else body
        if visible is not None:
            yield visible, "parameters", _unknown_pattern(pattern)
    for declaration in re.finditer(r"\bfor\s+(.+?)\s+in\b", scope, re.DOTALL):
        body, _ = _control_body(scope, declaration.end())
        if body is not None and _expression_end(scope, body, spans) is None:
            pattern = original[declaration.start(1) : declaration.end(1)]
            yield body, "parameters", _unknown_pattern(pattern)
    for declaration in re.finditer(r"\bmatch\b", scope):
        body, _ = _control_body(scope, declaration.end())
        if body is None or _expression_end(scope, body, spans) is not None:
            continue
        cursor = body + 1
        while cursor < len(scope):
            while cursor < len(scope) and scope[cursor] in " \t\r\n,":
                cursor += 1
            start = cursor
            stack = []
            guard = None
            arrow = None
            for position in range(cursor, len(scope)):
                char = scope[position]
                if char in "([{":
                    stack.append({"(": ")", "[": "]", "{": "}"}[char])
                elif char in ")]}":
                    if not stack or stack.pop() != char:
                        raise UnresolvedTypedReceiver("unsupported Rust match pattern")
                elif not stack:
                    if scope.startswith("=>", position):
                        arrow = position
                        break
                    if (
                        guard is None
                        and re.match(r"if\b", scope[position:])
                        and (position == 0 or not re.match(r"\w", scope[position - 1]))
                    ):
                        guard = position
            if arrow is None:
                if guard is not None:
                    yield guard, "parameters", _unknown_pattern(original[start:guard])
                break
            expression = arrow + 2
            while expression < len(scope) and scope[expression].isspace():
                expression += 1
            end = _expression_end(scope, expression, spans)
            if end is None:
                stop = guard if guard is not None else arrow
                yield stop, "parameters", _unknown_pattern(original[start:stop])
                break
            cursor = end + 1


def _initializers(scope: str, original: str):
    """Yield completed let declarations without splitting nested expressions.

    The current authority call can itself be inside an initializer. That new
    binding is not in scope yet, and its unfinished prefix must not be parsed
    as a field alias. Semicolons in method arguments and closure/block bodies
    likewise do not finish the containing let statement. An explicit typed
    declaration without an initializer also takes effect at its semicolon.
    """
    declaration = re.compile(r"\blet\s+")
    cursor = 0
    while assignment := declaration.search(scope, cursor):
        cursor = assignment.end()
        if _conditional_let(scope, assignment.start()):
            continue
        header = _binding_header(scope, cursor)
        if header is None:
            continue
        _, delimiter = header
        pattern = original[assignment.end() : delimiter].strip()
        simple = re.fullmatch(r"(?:mut\s+)?(\w+)(?:\s*:\s*(.+))?", pattern, re.DOTALL)
        stack = []
        cursor = delimiter + 1
        if scope[delimiter] == ";":
            if simple:
                yield cursor, *simple.groups(), ""
            else:
                for name in _unknown_pattern(pattern):
                    yield cursor, name, None, ""
            continue
        for position in range(cursor, len(scope)):
            char = scope[position]
            if char in "([{":
                stack.append({"(": ")", "[": "]", "{": "}"}[char])
            elif char in ")]}" and (not stack or stack.pop() != char):
                break
            elif char == ";" and not stack:
                if simple:
                    yield position + 1, *simple.groups(), scope[cursor:position].strip()
                else:
                    for name in _unknown_pattern(pattern):
                        yield position + 1, name, None, ""
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
    original = code[_function_start(code, position) : position]
    scope = _live_prefix(original)
    bindings = _parameter_types(_function_parameters(original), target)
    spans = _closure_spans(scope)
    events = [
        (closing, "parameters", _parameter_types(original[opening + 1 : closing], target))
        for opening, closing in spans.items()
        if _closure_is_live(scope, closing, spans)
    ]
    events.extend(
        (end, "declaration", (name, annotation, expression))
        for end, name, annotation, expression in _initializers(scope, original)
    )
    events.extend(_pattern_scope_events(scope, spans, original))
    for _, kind, value in sorted(events, key=lambda event: event[0]):
        if kind == "parameters":
            bindings.update(value)
            continue
        name, annotation, expression = value
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
