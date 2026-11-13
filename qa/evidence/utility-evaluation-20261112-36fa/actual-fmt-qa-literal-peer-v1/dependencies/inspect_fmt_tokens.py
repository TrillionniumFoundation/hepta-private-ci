"""Lossless source evidence inspection, not a Rust parser or execution test."""
import base64
import collections
import difflib
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json')

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

def main():
    raw = INPUT.read_bytes()
    assert ident(raw) == {'bytes':2175219,'sha256':'3309f2099b3545737f390f16928d5d085177e72a6e8194aa018fe5039121dc22','git_blob':'43f7dd7eaa1578a4d6d570252939084f80181685'}
    packet = json.loads(raw)
    assert packet['stage'] == 'fmt.after' and len(packet['changes']) == 62
    rows = []
    for row in packet['changes']:
        data = {}
        for side in ['before', 'after']:
            b = base64.b64decode(row[side+'_raw_base64'], validate=True)
            actual = ident(b)
            pin = row[side]
            assert actual['bytes'] == pin['bytes'] and actual['sha256'] == pin['sha256']
            assert actual['git_blob'] == pin['working_blob']
            data[side] = b.decode('utf-8')
            out = HERE / side / row['path']
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('xb') as f: f.write(b)
        at, ac = lex(data['before'])
        bt, bc = lex(data['after'])
        changes = changed_sequences(at, bt)
        comment_changes = changed_sequences(ac, bc)
        literals_equal = [x[1] for x in at if x[0]=='literal'] == [x[1] for x in bt if x[0]=='literal']
        diff = ''.join(difflib.unified_diff(data['before'].splitlines(keepends=True), data['after'].splitlines(keepends=True), fromfile=row['path']+'.before',tofile=row['path']+'.after'))
        diff_path = HERE / 'diffs' / (Path(row['path']).name + '.diff')
        diff_path.parent.mkdir(exist_ok=True)
        with diff_path.open('x') as f: f.write(diff)
        rows.append({'path':row['path'], 'before':ident(data['before'].encode()),'after':ident(data['after'].encode()),
                     'token_count_before':len(at),'token_count_after':len(bt),
                     'non_whitespace_token_sequences_equal':not changes,
                     'literal_sequence_exact_equal':literals_equal,'comments_exact_equal':not comment_changes,
                     'token_changes':changes,'comment_changes':comment_changes,'diff_bytes':len(diff.encode())})
    report={'schema':'hepta-actual-fmt62-independent-lexical-diagnostic-v1','source_packet':ident(raw),
            'tokens_ignore_only_outside_literal_whitespace_and_record_comments_separately':True,
            'not_a_rust_parser_or_runtime_result':True,'rows':rows}
    encoded=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
    with (HERE/'LEXICAL_DIAGNOSTIC.json').open('xb') as f:f.write(encoded)
    print(json.dumps({'report':ident(encoded),'files':len(rows),'exact_token_sequences':sum(x['non_whitespace_token_sequences_equal'] for x in rows),'literal_sequence_differences':[x['path'] for x in rows if not x['literal_sequence_exact_equal']],
                      'comment_changes':[x['path'] for x in rows if not x['comments_exact_equal']],
                      'non_whitespace_changes':[{'path':x['path'],'hunks':len(x['token_changes'])} for x in rows if not x['non_whitespace_token_sequences_equal']]},indent=2))

if __name__ == '__main__': main()
