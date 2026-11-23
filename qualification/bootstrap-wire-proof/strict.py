import collections
import json
import re
import sys
from pathlib import Path

evidence, baseline = map(Path, sys.argv[1:3])
expected = json.loads(baseline.read_text())
assert expected['source'] == '43e5da1bb81369e4e999adfa8558f5ccb5460eb6'
assert expected['compiler_exit'] == 101 and len(expected['diagnostics']) == 115
before = collections.Counter((r['path'], r['line'], r['column'], r['diagnostic']) for r in expected['diagnostics'])
text = (evidence/'strict.log').read_text()
after = collections.Counter()
assert not re.search(r'^error\[E\d+\]', text, re.M) and 'error: could not compile' in text
for block in re.split(r'^error: ', text, flags=re.M)[1:]:
    message = block.splitlines()[0]
    if message.startswith('could not compile'):
        continue
    location = re.search(r'^\s*--> ([^:\n]+):(\d+):(\d+)\s*$', block, re.M)
    assert location, message
    path = location[1].removeprefix('codex-rs/')
    after['codex-rs/'+path, int(location[2]), int(location[3]), message] += 1
removed, added = sorted((before-after).elements()), sorted((after-before).elements())
actual = int((evidence/'strict.exit').read_text())
result = {'base_count': before.total(), 'candidate_count': after.total(), 'base_exit': 101,
          'candidate_exit': actual, 'removed': removed, 'added': added}
(evidence/'strict-comparison.json').write_text(json.dumps(result, indent=2)+'\n')
print(result)
assert actual == 101 and before.total() == 115 and after.total() == 114 and not added
assert len(removed) == 1 and removed[0][0].endswith('/authority_host_publication_bootstrap.rs') and removed[0][-1] == 'large size difference between variants'
