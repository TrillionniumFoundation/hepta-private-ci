"""Conservative source projection for an explicitly disabled Rust feature.

This does not infer arbitrary cfg expressions. Only an exact cfg(feature=...)
item is removed, and malformed or unrecognized syntax stays visible. Callers
must separately establish that the feature is absent from product builds.
"""
from __future__ import annotations
import re


def _code_mask(text: str) -> str:
    chars = list(text)
    raw_pattern = re.compile(r'(?:br|r)(#{0,255})"')
    char_pattern = re.compile(r"'(?:\\.|[^'\\\n])'")
    i = 0
    while i < len(text):
        start = i
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            i += 2
            depth = 1
            while i < len(text) and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                return text  # do not hide malformed source
        else:
            raw = raw_pattern.match(text, i)
            if raw:
                delimiter = '"' + raw.group(1)
                end = text.find(delimiter, raw.end())
                if end < 0:
                    return text
                i = end + len(delimiter)
            elif text[i] == '"':
                i += 1
                while i < len(text):
                    if text[i] == "\\":
                        i += 2
                    elif text[i] == '"':
                        i += 1
                        break
                    else:
                        i += 1
            else:
                char = char_pattern.match(text, i)
                if char:
                    i = char.end()
                else:
                    i += 1
                    continue
        for j in range(start, min(i, len(chars))):
            if chars[j] != "\n":
                chars[j] = " "
    return "".join(chars)


def without_disabled_feature_items(text: str, feature: str) -> str:
    output = list(text)
    pattern = re.compile(r'(?m)^[ \t]*#\[cfg\(feature\s*=\s*"'
                         + re.escape(feature) + r'"\)\][ \t]*\n')
    matches = list(pattern.finditer(text))
    if not matches:
        return text
    code = _code_mask(text)
    for match in matches:
        # An apparent attribute inside a string or comment is not Rust syntax.
        if "#[cfg" not in code[match.start():match.end()]:
            continue
        i = match.end()
        while i < len(code):
            if code[i].isspace():
                i += 1
            elif code.startswith("#[", i):
                end = code.find("]", i + 2)
                if end < 0:
                    return text
                i = end + 1
            else:
                break
        # Remove only ordinary items. Never treat an expression or macro as a
        # declaration on the strength of an adjacent attribute.
        declaration = re.match(r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?"
                               r"(?:fn|use|struct|enum|impl|mod|type|const|static|trait)\b", code[i:])
        if not declaration:
            continue
        stack = []
        end = None
        pairs = {')': '(', ']': '[', '}': '{'}
        for j in range(i, len(code)):
            c = code[j]
            if c in "([{":
                stack.append(c)
            elif c in ")]}":
                if not stack or stack.pop() != pairs[c]:
                    return text
                if c == "}" and not stack:
                    end = j + 1
                    break
            elif c == ";" and not stack:
                end = j + 1
                break
        if end is None:
            return text
        for j in range(match.start(), end):
            if output[j] != "\n":
                output[j] = " "
    return "".join(output)
