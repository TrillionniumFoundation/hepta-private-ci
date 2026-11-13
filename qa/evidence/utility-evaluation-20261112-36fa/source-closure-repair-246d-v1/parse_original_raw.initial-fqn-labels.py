#!/usr/bin/env python3
"""Parse only the exact original 246d closure log; never execute repository code."""
import argparse
import hashlib
import json
import re
from pathlib import Path

EXPECTED_BYTES = 118496
EXPECTED_SHA256 = 'f51a3e278d6e5072b0c13b94c2279eaa890419e8445af5e12eb9021565ecb29f'
EXPECTED_BLOB = 'f84b983ace7dfd3dbe8de0a3972274d0f8a930e3'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.raw.read_bytes()
    assert len(raw) == EXPECTED_BYTES
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SHA256
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == EXPECTED_BLOB
    text = raw.decode('utf-8')
    lines = text.splitlines(keepends=True)
    statuses = []
    starts = []
    for index, line in enumerate(lines):
        value = line.rstrip('\r\n')
        match = re.match(r'^\s*(test\w*) \(([^)]+)\)(.*)$', value)
        if match:
            tail = match.group(3)
            outcome = next((x for x in ('ok', 'FAIL', 'ERROR', 'skipped') if re.search(r'\b'+x+r'(?:\s|$)', tail)), None)
            statuses.append({'line': index+1, 'method': match.group(1), 'class': match.group(2),
                             'fqn': match.group(2)+'.'+match.group(1), 'outcome': outcome, 'original': value})
        failure = re.match(r'^(FAIL|ERROR): (test\w*) \(([^)]+)\)(.*)$', value)
        if failure:
            starts.append({'line': index+1, 'index': index, 'kind': failure.group(1),
                           'fqn': failure.group(3)+'.'+failure.group(2), 'original_header': value})
    sections = []
    for item in starts:
        finish = item['index']+1
        while finish < len(lines):
            if re.match(r'^(?:={15,}|-{15,}|Ran \d+ tests? in )', lines[finish]):
                break
            finish += 1
        block = ''.join(lines[item['index']:finish])
        sections.append({k:v for k,v in item.items() if k != 'index'} | {
            'last_line': finish, 'original_block': block,
            'block_sha256': hashlib.sha256(block.encode()).hexdigest()})
    summary = [line.rstrip('\r\n') for line in lines if re.match(r'^(Ran \d+ tests? in |FAILED \(|OK(?:\s|$))', line)]
    output = {
        'format': 'hepta-exact-246d-source-closure-raw-index-v1',
        'source_commit': '246d8cb614770252ee42029a5c014f2a4904176a',
        'original_raw': {'bytes': len(raw), 'sha256': EXPECTED_SHA256, 'git_blob': EXPECTED_BLOB},
        'raw_complete_identity_verified': True, 'test_execution_performed': False,
        'summary_lines': summary, 'status_entries': statuses, 'failure_sections': sections,
        'distinct_ok_fqns': sorted({x['fqn'] for x in statuses if x['outcome']=='ok'}),
        'distinct_failure_fqns': sorted({x['fqn'] for x in sections}),
        'cause_classification': 'Requires exact source and original test-intent review; this parser assigns no cause.',
    }
    args.output.mkdir(parents=True, exist_ok=True)
    destinations = {'raw.log': raw, 'RAW_FAILURE_INDEX.json': (json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode(),
                    'FAILURES.original-excerpts.txt': '\n'.join(x['original_block'] for x in sections).encode()}
    for name, payload in destinations.items():
        target = args.output/name
        if target.exists():
            assert target.read_bytes() == payload
        else:
            target.write_bytes(payload)
    print(json.dumps({'summary_lines': summary, 'failure_sections': len(sections),
                      'distinct_failed_methods': len(output['distinct_failure_fqns']),
                      'distinct_ok_methods': len(output['distinct_ok_fqns']),
                      'failures': output['distinct_failure_fqns']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
