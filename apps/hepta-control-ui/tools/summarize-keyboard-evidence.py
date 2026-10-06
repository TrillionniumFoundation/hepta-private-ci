"""Collect exact keyboard outcomes without turning a failed contract or AX dump into acceptance."""
import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path


def collect(root, source):
    report = json.loads((root / 'robrix-keyboard-results.json').read_text())
    stats = report['stats']
    assert stats['expected'] + stats['unexpected'] == 3 and stats['skipped'] == stats['flaky'] == 0
    required_captures = {
        'cold-keyboard-entry': {'initial', 'after-first-tab', 'after-keyboard-entry', 'terminal-state'},
        'draft-theme-round-trip': {'initial', 'seeded-draft', 'theme-keyboard-focus', 'theme-keyboard-activated', 'draft-after-theme-keyboard', 'terminal-state'},
        'escape-restores-opener': {'initial', 'seeded-draft', 'navigation-open', 'navigation-search-focused', 'navigation-dismissed', 'navigation-keyboard-reopened', 'draft-after-search-dismissal', 'terminal-state'},
    }
    subjects = []
    for path in sorted((root / 'robrix-keyboard').glob('*/keyboard-evidence.json')):
        data = json.loads(path.read_text())
        assert data['sourceSha'] == source
        assert data['physicalImeQualified'] is False and data['screenReaderQualified'] is False
        assert data['scenario'] in required_captures
        names = [capture['name'] for capture in data['captures']]
        assert len(set(names)) == len(names), 'Duplicate capture names'
        if data['complete']:
            assert set(names) == required_captures[data['scenario']], 'Missing required completed-case capture'
        for capture in data['captures']:
            name = capture['name']
            assert '/' not in name and '\\' not in name and name not in ('.', '..')
            assert hashlib.sha256(path.with_name(name + '.png').read_bytes()).hexdigest() == capture['pngSha256']
        requests = Counter(x['url'] for x in data['fonts'] if x['event'] == 'request')
        finished = Counter(x['url'] for x in data['fonts'] if x['event'] == 'finished')
        font_pass = bool(requests) and requests == finished and not data['pendingFonts'] and not any(x['event'] == 'failed' or x['event'] == 'response' and x['status'] != 200 for x in data['fonts'])
        if data['complete']:
            assert font_pass and not data['errors']
        trace = data.get('rustFocusTrace', [])
        assert data.get('focusTraceExpected') is True and 0 < len(trace) <= 64
        assert all(isinstance(line, str) and len(line) <= 16384 and '\n' not in line and '\r' not in line and re.fullmatch(r'HEPTA_KEYBOARD_FOCUS phase=(before|after)-dispatch kind=(down|up) key=(Tab|Space|ReturnKey|Escape) shift=(true|false) focus=.+ valid=(true|false) candidates=\[.*\] public_nav_root=(None|Some\(.+\)) stops_truncated=(true|false) stops=\[.*\]', line) for line in trace), 'Invalid or unbounded Rust focus trace'
        subjects.append({'diagnosticInstrumented': True, 'rustFocusTrace': trace, 'scenario': data['scenario'], 'complete': data['complete'], 'fontHealth': font_pass,
                         'captures': len(data['captures']), 'errors': data['errors'], 'axObservations': data['axObservations']})
    expected = {'cold-keyboard-entry', 'draft-theme-round-trip', 'escape-restores-opener'}
    assert len(subjects) == 3 and {x['scenario'] for x in subjects} == expected
    complete_count = sum(x['complete'] for x in subjects)
    assert complete_count == stats['expected'], 'Final authoritative result differs from completion receipt'
    return {'sourceSha': source, 'keyboardContractsPassed': complete_count == 3,
            'completeCount': complete_count, 'subjects': subjects, 'screenReaderQualified': False,
            'physicalImeQualified': False, 'diagnosticInstrumented': True, 'scope': '3 compact640px keyboard contracts; AX role/name inventory is observation only'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('source')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    summary = collect(args.root, args.source)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    # The browser step owns failure status. Collection success is not acceptance.
