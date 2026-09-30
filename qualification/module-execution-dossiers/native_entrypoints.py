"""Structural Rust navigation; compilation and product use remain separate."""
import re

RAW = re.compile(r'(?:br|r)(#*)"')
CHAR = re.compile(r"(?:b)?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\])'")
TOKEN = re.compile(r'[A-Za-z_]\w*|::|->|.')

def rust_tokens(source: str) -> list[str]:
    """Exclude nested comments, quoted text and raw strings before navigation."""
    tokens = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
        elif source.startswith('//', i):
            end = source.find('\n', i + 2)
            i = len(source) if end < 0 else end
        elif source.startswith('/*', i):
            depth = 1
            i += 2
            while depth and i < len(source):
                if source.startswith('/*', i):
                    depth += 1
                    i += 2
                elif source.startswith('*/', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError('unterminated Rust comment')
        else:
            raw = RAW.match(source, i)
            char = CHAR.match(source, i)
            if raw:
                end_marker = '"' + raw[1]
                end = source.find(end_marker, raw.end())
                if end < 0:
                    raise ValueError('unterminated Rust raw string')
                i = end + len(end_marker)
            elif char:
                i = char.end()
            elif source[i] == '"' or source.startswith('b"', i):
                i += 1 if source[i] == '"' else 2
                while i < len(source) and source[i] != '"':
                    i += 2 if source[i] == '\\' else 1
                if i >= len(source):
                    raise ValueError('unterminated Rust string')
                i += 1
            else:
                token = TOKEN.match(source, i)
                tokens.append(token[0])
                i = token.end()
    return tokens


def rust_methods(tokens: list[str]) -> set[str]:
    """Bind a method declaration to its own impl and explicit module scope.

    Macro templates/invocations and function bodies are opaque. No macro
    expansion, visibility, cfg selection or compiler/API validity is proved.
    """
    methods = set()
    pairs = {'{': '}', '[': ']', '(': ')', '<': '>'}

    def closing(start):
        stack = [pairs[tokens[start]]]
        i = start + 1
        while i < len(tokens):
            token = tokens[i]
            # Angle brackets are balanced only when parsing generic headers.
            if token in pairs and (token != '<' or tokens[start] == '<'):
                stack.append(pairs[token])
            elif token == stack[-1]:
                stack.pop()
                if not stack:
                    return i
            i += 1
        raise ValueError('unbalanced Rust navigation delimiter')

    def macro_end(i, end):
        if tokens[i] == 'macro_rules' and i + 3 < end and tokens[i + 1] == '!' and tokens[i + 3] in '{[(':
            return closing(i + 3) + 1
        if i + 2 < end and tokens[i + 1] == '!' and tokens[i + 2] in '{[(':
            return closing(i + 2) + 1
        return None

    def body_start(i, end):
        while i < end:
            if tokens[i] == '{' or tokens[i] == ';':
                return i
            if tokens[i] in '<[(':
                i = closing(i) + 1
            else:
                i += 1
        return end

    def owner(header):
        i = 0
        if header and header[0] == '<':
            depth = 1
            i = 1
            while i < len(header) and depth:
                depth += (header[i] == '<') - (header[i] == '>')
                i += 1
        angle = 0
        for j in range(i, len(header)):
            angle += (header[j] == '<') - (header[j] == '>')
            if not angle and header[j] == 'for':
                i = j + 1
                break
        if i >= len(header) or not header[i].isidentifier():
            return None
        names = [header[i]]
        i += 1
        while i + 1 < len(header) and header[i] == '::' and header[i + 1].isidentifier():
            names.append(header[i + 1])
            i += 2
        return '::'.join(names)

    def walk(start, end, scope):
        i = start
        while i < end:
            skipped = macro_end(i, end)
            if skipped is not None:
                i = skipped
            elif tokens[i] == 'mod' and i + 2 < end and tokens[i + 1].isidentifier() and tokens[i + 2] == '{':
                stop = closing(i + 2)
                walk(i + 3, stop, scope + [tokens[i + 1]])
                i = stop + 1
            elif tokens[i] == 'impl':
                body = body_start(i + 1, end)
                target = owner(tokens[i + 1:body])
                if body == end or tokens[body] != '{':
                    i = body + 1
                    continue
                stop = closing(body)
                j = body + 1
                while target and j < stop:
                    skipped = macro_end(j, stop)
                    if skipped is not None:
                        j = skipped
                    elif tokens[j] in '{[(':
                        j = closing(j) + 1
                    else:
                        if tokens[j] == 'fn' and j + 2 < stop and tokens[j + 1].isidentifier() and tokens[j + 2] in '(<':
                            methods.add('::'.join(scope + [target, tokens[j + 1]]))
                        j += 1
                i = stop + 1
            elif tokens[i] == 'fn':
                body = body_start(i + 1, end)
                i = closing(body) + 1 if body < end and tokens[body] == '{' else body + 1
            elif tokens[i] in '{[(':
                i = closing(i) + 1
            else:
                i += 1

    walk(0, len(tokens), [])
    return methods
