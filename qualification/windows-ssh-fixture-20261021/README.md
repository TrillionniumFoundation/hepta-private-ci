# Original Windows SSH fixture packet

`original-packet.tar.xz` contains all 21 original packet files at their original relative paths, including the full original `MANIFEST.json`, source bundle, source patch, source copies and Windows failure log. No original bytes were changed. `TRANSPORT.json` records every member length and SHA-256, the original manifest digest and the archive digest.

The first flat-file staging check returned exit 2 because the original Git bundle stdout includes a trailing space and the patch contains literal blank context lines. The raw check and exit are retained in the adjacent combined-durability evidence. The packet is compressed to preserve those original bytes while the unchanged repository whitespace and blob gates still apply to the published tree.

To verify, extract into an empty directory, then run the original manifest verification and bundle check from a checkout that contains prerequisite commit `29f845b6a214472906416cc0626551c19a4ab54e`:

```bash
mkdir extracted-packet
tar -xJf original-packet.tar.xz -C extracted-packet
python3 - <<'PYVERIFY'
import hashlib, json
from pathlib import Path
p = Path('extracted-packet')
m = json.loads((p / 'MANIFEST.json').read_text())
for entry in m['files']:
    data = (p / entry['path']).read_bytes()
    assert len(data) == entry['bytes'], entry['path']
    assert hashlib.sha256(data).hexdigest() == entry['sha256'], entry['path']
assert len(list(x for x in p.rglob('*') if x.is_file())) == 21
print('All 20 manifest entries verified; original manifest retained as file 21.')
PYVERIFY
git bundle verify extracted-packet/source.bundle
```

The source changes were independently reviewed, formatted and integrated without changes to production trust or either dependency lock. The original Windows failure was observed; its exact cause was not reproduced. Linux boundary probes are recorded in the original packet, and the full original Windows 43-test crate remains pending CI on the new source.
