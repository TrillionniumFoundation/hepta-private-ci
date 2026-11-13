"""Pure lexical helpers extracted unchanged from the previous independent formatter review; no project code execution."""

import re, difflib, hashlib

def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

RAW = re.compile(r'(?:br|cr|r)(#{0,255})"')

CHAR = re.compile(r"(?:b)?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|[^\r\n])|[^\\'\r\n])'")

IDENT = re.compile(r'(?:r#)?[A-Za-z_][A-Za-z_0-9]*')

LIFETIME = re.compile(r"'[A-Za-z_][A-Za-z_0-9]*")

NUMBER = re.compile(r'[0-9][A-Za-z_0-9]*')

PUNCTS = sorted(['<<=', '>>=', '..=', '...', '::', '->', '=>', '==', '!=', '>=', '<=', '&&', '||',
                 '+=', '-=', '*=', '/=', '%=', '^=', '&=', '|=', '<<', '>>', '..'], key=len, reverse=True)

def lex(s):
    tokens, comments = [], []
    i, n = 0, len(s)
    while i < n:
        start = i
        if s[i].isspace():
            i += 1
            continue
        if s.startswith('//', i):
            end = s.find('\n', i)
            i = n if end < 0 else end
            comments.append(('line-comment', s[start:i], start, i))
            continue
        if s.startswith('/*', i):
            i += 2
            depth = 1
            while i < n and depth:
                if s.startswith('/*', i): depth += 1; i += 2
                elif s.startswith('*/', i): depth -= 1; i += 2
                else: i += 1
            assert depth == 0, ('unterminated comment', start)
            comments.append(('block-comment', s[start:i], start, i))
            continue
        m = RAW.match(s, i)
        if m:
            ending = '"' + m.group(1)
            end = s.find(ending, m.end())
            assert end >= 0, ('unterminated raw literal', start)
            i = end + len(ending)
            tokens.append(('literal', s[start:i], start, i))
            continue
        quote = i if s[i] == '"' else i + 1 if s.startswith(('b"', 'c"'), i) else None
        if quote is not None:
            i = quote + 1
            while i < n:
                if s[i] == '\\': i += 2
                elif s[i] == '"': i += 1; break
                else: i += 1
            else: raise AssertionError(('unterminated literal', start))
            tokens.append(('literal', s[start:i], start, i))
            continue
        m = CHAR.match(s, i)
        if m:
            i = m.end(); tokens.append(('literal', m.group(), start, i)); continue
        m = LIFETIME.match(s, i)
        if m:
            i = m.end(); tokens.append(('lifetime', m.group(), start, i)); continue
        m = IDENT.match(s, i)
        if m:
            i = m.end(); tokens.append(('identifier', m.group(), start, i)); continue
        m = NUMBER.match(s, i)
        if m:
            i = m.end(); tokens.append(('number', m.group(), start, i)); continue
        multi = next((p for p in PUNCTS if s.startswith(p, i)), None)
        if multi:
            i += len(multi); tokens.append(('punct', multi, start, i)); continue
        assert not s[i].isalnum(), ('unhandled identifier character', i, s[i])
        i += 1
        tokens.append(('punct', s[start:i], start, i))
    return tokens, comments

def changed_sequences(a, b):
    av, bv = [x[:2] for x in a], [x[:2] for x in b]
    result = []
    for op, i, j, k, l in difflib.SequenceMatcher(a=av, b=bv, autojunk=False).get_opcodes():
        if op == 'equal': continue
        result.append({'op': op, 'before_range': [i,j], 'after_range':[k,l],
                       'before': av[i:j], 'after': bv[k:l],
                       'before_context': av[max(0,i-14):min(len(av),j+14)],
                       'after_context': bv[max(0,k-14):min(len(bv),l+14)]})
    return result
