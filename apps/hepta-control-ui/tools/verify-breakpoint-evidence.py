"""Require exact new breakpoint subjects and immutable original screenshots."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def verify(root, source, scope):
    assert scope in ('all', '759-only')
    widths = (360, 759, 760, 761) if scope == 'all' else (759,)
    expected_cases = 3 * len(widths)
    report = json.loads((root / 'robrix-breakpoints-results.json').read_text())
    stats = report['stats']
    assert stats['expected'] == expected_cases and all(stats[key] == 0 for key in ('unexpected', 'skipped', 'flaky'))
    rows = []
    for path in sorted((root / 'robrix-breakpoints').glob('*/breakpoint-evidence.json')):
        data = json.loads(path.read_text())
        assert data['sourceSha'] == source and data['completed'] is True
        assert not data['errors'] and not data['pendingFonts'] and not data['apiRequests']
        requested = Counter(item['url'] for item in data['fontEvents'] if item['event'] == 'request')
        finished = Counter(item['url'] for item in data['fontEvents'] if item['event'] == 'finished')
        assert requested and requested == finished
        assert not any(item['event'] == 'failed' or item['event'] == 'response' and item['status'] != 200 for item in data['fontEvents'])
        captures = data['captures']
        names = [item['name'] for item in captures]
        assert len(set(names)) == len(names)
        required = {'initial-chat', 'draft-before-console', 'console-top', 'console-bottom', 'console-before-return', 'chat-after-return'}
        assert required <= set(names)
        assert len(captures) == 6 + ('Aurora', 'Obsidian', 'Lunar').index(data['theme'])
        for item in captures:
            name = item['name']
            assert '/' not in name and '\\' not in name and name not in ('.', '..')
            png = path.with_name(name + '.png').read_bytes()
            assert hashlib.sha256(png).hexdigest() == item['pngSha256']
            assert png[:8] == b'\x89PNG\r\n\x1a\n'
            w, h = struct.unpack('>II', png[16:24])
            viewport = item['viewport']
            assert h == round(800 * w / viewport['width']) and viewport['height'] == 800
            if name in ('console-top', 'console-bottom'):
                assert viewport['width'] == data['targetWidth'] and item['theme'] == data['theme']
        rows.append({'theme': data['theme'], 'width': data['targetWidth'], 'captures': len(captures)})
    expected = {(theme, width) for theme in ('Aurora', 'Obsidian', 'Lunar') for width in widths}
    assert len(rows) == expected_cases and {(row['theme'], row['width']) for row in rows} == expected
    return {'sourceSha': source, 'passed': True, 'subjects': rows,
            'caseScope': scope, 'expectedCases': expected_cases,
            'scope': 'Source-bound selected Chromium breakpoint cases only; no physical IME, accessibility, native host or live owner qualification'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('source')
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--scope', choices=('all', '759-only'), default='all')
    args = p.parse_args()
    result = verify(args.root, args.source, args.scope)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
