"""Conservative source matching for methods on an explicit authority type.

Inputs are Rust with literals/comments/test items removed by the caller proof.
This is not a Rust type checker: unsupported possible authority receivers fail
closed, while explicit unrelated receiver types do not create false owners.
"""

from __future__ import annotations

import re
import unicodedata


class UnresolvedTypedReceiver(ValueError):
    pass


class AuthorityFields(dict[tuple[str, str], str | None]):
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


def _raw_identifiers(code: str) -> str:
    # Literals/comments are removed by the caller before this lexical pass.
    # A raw identifier names the same symbol as its unprefixed spelling. Strip
    # only the token prefix so alias discovery cannot mistake r#Gate for `r`.
    if "r#" in code:
        code = re.sub(r"\br#(?=[^\W\d])", "", code)
    return code if code.isascii() else unicodedata.normalize("NFC", code)


def _identifier_tokens(code: str):
    """Yield complete identifiers, including non-composing Unicode marks."""
    consumed = 0
    for match in re.finditer(r"[^\W\d]\w*", code):
        if match.start() < consumed:
            continue
        end = match.end()
        while end < len(code) and ("x" + code[end]).isidentifier():
            end += 1
        token = code[match.start() : end]
        if token.isidentifier():
            yield match.start(), end, token
        consumed = end


def _declared_aliases(code: str, target: str) -> set[str]:
    code = _raw_identifiers(code)
    if target not in code:
        return set()
    aliases = set()
    # Restrict `as` to use declarations: a function cast `callee as fn()`
    # must not turn the Rust keyword `fn` into a spurious import alias.
    for declaration in re.finditer(r"\buse\s+[^;]+;", code):
        tokens = [token for _, _, token in _identifier_tokens(declaration.group())]
        for index in range(len(tokens) - 2):
            if tokens[index : index + 2] == [target, "as"]:
                aliases.add(tokens[index + 2])
    for match in re.finditer(r"\btype\s+([^;={}]+)\s*=\s*([^;]+);", code):
        # A target-bearing RHS can be a Unicode path or a generic identity
        # alias. Conservatively retain that possible authority instead of
        # classifying the alias as an unrelated nominal type.
        rhs_names = {name for _, _, name in _identifier_tokens(match.group(2))}
        if target not in rhs_names:
            continue
        declaration = match.group(1).strip()
        names = list(_identifier_tokens(declaration))
        if not names or names[0][0] != 0:
            raise UnresolvedTypedReceiver("unsupported explicit authority type alias")
        aliases.add(names[0][2])
    return aliases


def _normalize_aliases(
    code: str,
    target: str,
    aliases: frozenset[str] = frozenset(),
    *,
    method: str | None = None,
    preserve_dot_methods: bool = False,
) -> str:
    code = _raw_identifiers(code)
    aliases = aliases | _declared_aliases(code, target)
    if not aliases or not any(alias in code for alias in aliases):
        return code
    parts = []
    cursor = 0
    for start, end, token in _identifier_tokens(code):
        replacement = token
        if token in aliases:
            prefix = code[:start].rstrip()
            invocation = re.match(r"\s*(?:\(|::\s*<)", code[end:]) is not None
            qualified_slot = False
            if method == token and prefix.endswith("::"):
                receiver = prefix[:-2].rstrip()
                names = list(_identifier_tokens(receiver[-8192:]))
                qualified_slot = receiver.endswith(">") or bool(
                    names
                    and names[-1][2] in aliases | {target}
                    and names[-1][1] == len(receiver[-8192:])
                )
            method_slot = (
                method == token and (prefix.endswith(".") or qualified_slot)
            ) or (invocation and preserve_dot_methods and prefix.endswith("."))
            # Rust's type/import and method namespaces can use the same word.
            # Normalize `verify::verify`'s receiver, never its final method.
            replacement = token if method_slot else target
        parts.extend((code[cursor:start], replacement))
        cursor = end
    parts.append(code[cursor:])
    return "".join(parts)


def symbol_aliases(source_index: dict[str, str], target: str) -> frozenset[str]:
    """Follow explicit import/type alias chains using the existing lexical rules."""
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
    return frozenset(aliases - {target})


def normalize_symbol_aliases(code: str, target: str, aliases: frozenset[str]) -> str:
    return _normalize_aliases(code, target, aliases, preserve_dot_methods=True)


def authority_fields(source_index: dict[str, str], target: str) -> AuthorityFields:
    """Keep typed fields across split impl modules; no variable-name allowlist."""
    aliases = symbol_aliases(source_index, target)
    fields = AuthorityFields(aliases)
    for code in source_index.values():
        code = _normalize_aliases(code, target, fields.aliases)
        if target not in code:
            continue
        for declaration in re.finditer(r"\bstruct\s+(\w+)(?:\s*<[^{};]*>)?\s*\{", code):
            end = _end(code, declaration.end() - 1, "{", "}")
            declared_fields = {}
            for field in re.finditer(
                r"\b(\w+)\s*:\s*([^,;{}]+)", code[declaration.end() : end]
            ):
                raw_type = field.group(2).strip()
                type_name = _type(raw_type, target)
                if (
                    type_name != target
                    and re.fullmatch(
                        r"(?:&\s*(?:'\w+\s*)?(?:mut\s+)?)?(?:::)?\w+(?:::\w+)*",
                        raw_type,
                    )
                    is None
                ):
                    # A comma may belong to a generic argument rather than the
                    # next field. Never turn a partial generic type into a
                    # known unrelated receiver (including Deref wrappers).
                    type_name = None
                declared_fields[declaration.group(1), field.group(1)] = type_name
            # Keep unknown fields of a target-bearing owner in the index too;
            # a split impl must not disappear when the target is a later type
            # argument which this conservative field matcher does not parse.
            if re.search(rf"\b{re.escape(target)}\b", code[declaration.end() : end]):
                fields.update(declared_fields)
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


def _bindings(
    code: str,
    position: int,
    target: str,
    owner: str | None,
    fields: dict[tuple[str, str], str | None],
) -> dict[str, str | None]:
    scope = code[_function_start(code, position) : position]
    bindings = {}

    def record(name: str, inferred: str | None) -> None:
        # This lexical pass does not prove nested-block shadow lifetimes.
        # Conflicting bindings must remain unknown, never erase a possible
        # authority after an inner shadow has gone out of scope.
        if name in bindings and bindings[name] != inferred:
            bindings[name] = None
        else:
            bindings[name] = inferred

    for parameter in re.finditer(r"\b(\w+)\s*:\s*([^,;={}]+)", scope):
        raw_type = parameter.group(2)
        inferred = _type(raw_type, target)
        if inferred != target:
            # This lexical match can stop at a comma inside a generic/tuple
            # type. A partial type is not proof of an unrelated receiver: a
            # later argument may be the authority behind an alias or Deref.
            stack = []
            pairs = {">": "<", ")": "(", "]": "["}
            for index, char in enumerate(raw_type):
                if char in "<([":
                    stack.append(char)
                elif char in ">)]" and not (
                    char == ">" and index > 0 and raw_type[index - 1] == "-"
                ):
                    if not stack:
                        break  # End of the enclosing function parameter list.
                    if stack.pop() != pairs[char]:
                        inferred = None
                        break
            if stack:
                inferred = None
        record(parameter.group(1), inferred)
    for assignment in re.finditer(
        r"\blet\s+(?:mut\s+)?(\w+)(?:\s*:\s*([^=;]+))?\s*=\s*([^;]+)", scope
    ):
        name, annotation, expression = assignment.groups()
        if annotation:
            record(name, _type(annotation, target))
            continue
        constructor = re.match(
            r"(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*::\s*\w+\s*\(", expression
        )
        if constructor:
            # A different type's associated constructor may return or wrap the
            # authority (Arc/Box can auto-deref). Only an explicit annotation
            # proves an unrelated type; otherwise retain unknown/fail-closed.
            record(name, target if constructor.group(1) == target else None)
            continue
        alias = re.fullmatch(
            r"\s*&?\s*(?:mut\s+)?((?:[A-Za-z_]\w*)(?:\s*\.\s*\w+)*?)(?:\s*\.\s*(?:clone|as_ref|borrow|deref)\s*\(\s*\))?\s*",
            expression,
        )
        record(
            name,
            _receiver_type(alias.group(1), bindings, owner, fields) if alias else None,
        )
    return bindings


def _is_invocation(
    code: str, position: int, *, receiver_end: int | None = None
) -> bool:
    """Recognize a call suffix without scanning past a malformed generic list.

    Inputs are already stripped of comments and literals. Delimiters inside a
    const block do not make its comparison/shift operators into type brackets.
    Unsupported, incomplete, or excessively large generic syntax fails closed.
    """
    suffix = re.match(r"\s*(\(|::\s*<)", code[position:])
    if suffix is None:
        return False
    if suffix.group(1) == "(":
        return True
    opening = position + suffix.end() - 1
    stack = ["<"]
    pairs = {">": "<", ")": "(", "]": "[", "}": "{"}
    for index in range(opening + 1, min(len(code), opening + 8192)):
        char = code[index]
        in_const = "{" in stack
        if char in "([{":
            stack.append(char)
        elif char == "<" and not in_const:
            stack.append(char)
        elif char in ")]}":
            if stack[-1] != pairs[char]:
                raise UnresolvedTypedReceiver("unbalanced authority generic suffix")
            stack.pop()
        elif char == ">" and not in_const and code[index - 1] != "-":
            if stack[-1] != "<":
                raise UnresolvedTypedReceiver("unsupported authority generic suffix")
            stack.pop()
            if not stack:
                if receiver_end is not None:
                    return (
                        index < receiver_end
                        and not code[index + 1 : receiver_end].strip()
                    )
                if re.match(r"\s*\(", code[index + 1 :]) is None:
                    raise UnresolvedTypedReceiver(
                        "authority generic reference is not a direct call"
                    )
                return True
        elif char == ";" and not any(group in stack for group in ("[", "{")):
            raise UnresolvedTypedReceiver(
                "authority generic suffix crosses a statement"
            )
        if len(stack) > 128:
            raise UnresolvedTypedReceiver(
                "authority generic suffix nesting exceeds bound"
            )
    raise UnresolvedTypedReceiver("unclosed or oversized authority generic suffix")


def _qualified_target(code: str, position: int, target: str) -> bool:
    """Accept named authority paths; reject unsupported explicit target types.

    This recognizes callers conservatively, not the complete Rust type grammar.
    A target-bearing qualified type that is not a plain path needs review rather
    than being silently omitted from the closed set.
    """
    end = position
    while end > 0 and code[end - 1].isspace():
        end -= 1
        if position - end > 8192:
            raise UnresolvedTypedReceiver("authority receiver whitespace exceeds bound")
    prefix = code[max(0, end - 8192) : end]
    if not prefix.endswith(">"):
        return re.search(rf"\b(?:r#)?{re.escape(target)}$", prefix) is not None
    # A named generic receiver such as BTreeMap::<K, V>::new has an explicit
    # nominal type. Reuse the bounded balanced suffix pass; do not mistake a
    # homonymous constructor on that unrelated type for this authority.
    nominal = list(re.finditer(r"\b([^\W\d]\w*)\s*(?=::\s*<)", prefix))
    if nominal:
        candidate = nominal[-1]
        offset = end - len(prefix)
        if _is_invocation(code, offset + candidate.end(), receiver_end=position):
            if candidate.group(1) == target:
                return True
            if re.search(
                rf"\b{re.escape(target)}\b", code[offset + candidate.start() : position]
            ):
                # Identity<T> = T (and other aliases) need not retain the
                # outer nominal type. A target-bearing argument is not proof
                # of an unrelated receiver.
                raise UnresolvedTypedReceiver(
                    "target-bearing generic receiver requires review"
                )
            return False
    # Only a plain path is positively classified here. Do not guess balancing
    # of const expressions or traits in a qualified type: an unsupported form
    # must not disappear because the last '<' belongs to a comparison operator.
    opening = prefix.rfind("<")
    if opening < 0:
        raise UnresolvedTypedReceiver("unclosed or oversized authority receiver")
    receiver = prefix[opening + 1 : -1].strip()
    segments = receiver.removeprefix("::").strip().split("::")
    names = [segment.strip().removeprefix("r#") for segment in segments]
    if not all(name.isidentifier() for name in names):
        raise UnresolvedTypedReceiver("unsupported authority qualified receiver")
    return names[-1] == target


def has_authority_call(
    code: str,
    target: str,
    method: str,
    fields: AuthorityFields,
    *,
    associated_only: bool = False,
) -> bool:
    code = _normalize_aliases(code, target, fields.aliases, method=method)
    # The field index is derived from type declarations, including declarations
    # in a parent module. A typed variable/impl must name either the authority
    # or an indexed field owner. Avoid parsing unrelated crates' homonyms.
    type_names = {target, *(owner for owner, _ in fields)}
    if not any(
        name in code and re.search(rf"\b{re.escape(name)}\b", code)
        for name in type_names
    ):
        return False
    method_name = rf"(?:r#)?{re.escape(method)}"
    qualified = rf"::\s*{method_name}\b"
    found = False
    for call in re.finditer(qualified, code):
        if _qualified_target(code, call.start(), target):
            if not _is_invocation(code, call.end()):
                raise UnresolvedTypedReceiver(
                    "authority method reference is not a direct call"
                )
            found = True
    if associated_only:
        return found
    potential = re.compile(rf"\.\s*{method_name}\b(?=\s*(?:\(|::\s*<))")
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
            found = _is_invocation(code, call.end()) or found
        elif resolved is None:
            raise UnresolvedTypedReceiver(
                f"unresolved possible {target}::{method} receiver"
            )
    return found
