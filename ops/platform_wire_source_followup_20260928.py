#!/usr/bin/env python3
"""Complete a reviewed ordinary source proposal; this does not qualify it."""
from pathlib import Path
import json
import os
import subprocess
import sys

AUTHOR_ROOT = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve()
os.chdir(ROOT)
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == 'df550741c58081c3271ce2b2dce92e95d1bfb4d4'

def replace(path, old, new, count=1):
    p = Path(path)
    source = p.read_text()
    assert source.count(old) == count, (path, old, source.count(old))
    p.write_text(source.replace(old, new))

http_source = (AUTHOR_ROOT / 'platform_wire_http_accept_20260928.rs').read_text()
http_source = http_source.replace('name == expected_name', 'name.as_str() == *expected_name')
http_source = http_source.replace('value == expected', 'value.as_str() == *expected')
Path('codex-rs/hepta-native-gateway/src/http_accept.rs').write_text(http_source)
replace('.github/workflows/lane-a-foundation.yml',
        'HEPTA_CI_LANE: synthetic-merge', 'HEPTA_CI_LANE: base-merge')
replace('.github/workflows/platform-wire-fuzz.yml',
        'CARGO_FUZZ_VERSION: "0.12.0"', 'CARGO_FUZZ_VERSION: "0.13.2"')

note = '''\n## HTTP representation precedence and exact qualification\n\nThe runtime route applies media-range specificity separately to JSON and HPTA\nV2 before comparing quality weights. An explicit `q=0` cannot be overridden by\na wildcard. Unsupported media parameters do not match; repeated equal-specificity\nranges use the lower quality regardless of header order. JSON remains the\ndefault when Accept is absent or the supported representations tie. A wildcard\ncan select wire when JSON is explicitly excluded; this selects a representation\nonly and confers no session authentication or domain authority.\n\nThe Lane A synthetic-merge command wrapper uses its canonical `base-merge` lane\nidentifier; the tested subject remains the deterministic ordered-parent merge.\nThe fuzz runner pins cargo-fuzz 0.13.2 rather than the unavailable 0.12.0. Setup\nfailures are infrastructure-invalid, not a successful campaign or a found crash.\nSource changes require new exact-commit receipts; the old failed run is retained\nas history and cannot qualify this proposal.\n'''
with Path('docs/modules/platform.wire/STREAM_AND_SESSION_V2_REPAIR.md').open('a') as out:
    out.write(note)

subprocess.run(['cargo', 'fmt', '--manifest-path', 'codex-rs/Cargo.toml',
                '--package', 'codex-hepta-wire', '--package', 'codex-hepta-native-gateway'], check=True)
subprocess.run(['git', 'add', 'codex-rs/hepta-wire', 'codex-rs/hepta-native-gateway/src/http_accept.rs',
                '.github/workflows/lane-a-foundation.yml', '.github/workflows/platform-wire-fuzz.yml',
                'docs/modules/platform.wire/STREAM_AND_SESSION_V2_REPAIR.md'], check=True)
tree = subprocess.check_output(['git', 'write-tree'], text=True).strip()
path = Path('docs/modules/platform.wire/IMPLEMENTATION_MAP.json')
mapping = json.loads(path.read_text())
paths = {row['path'] for row in mapping['sourceObjects']}
paths.add('codex-rs/hepta-native-gateway/src/http_accept.rs')
mapping['sourceObjects'] = [
    {'path': p, 'object': subprocess.check_output(['git', 'rev-parse', f'{tree}:{p}'], text=True).strip()}
    for p in sorted(paths)
]
assert mapping['productionImplementation'] is False
path.write_text(json.dumps(mapping, indent=2) + '\n')
subprocess.run(['git', 'add', str(path)], check=True)
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
print('FOLLOWUP_SOURCE_READY', flush=True)
