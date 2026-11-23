"""Validate the downloaded ZIP and the exact log prefix sealed by its cancellation-time manifest."""
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re

d=Path(__file__).resolve().parent
archive=d/'partial.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='0d231435265e26885896bb6e51a28e79a5dc49f6dd297547c670dfec18d0e052'
with ZipFile(archive) as z:
    source=z.read('tested-commit.txt').decode().strip()
    assert source=='a4ff555f72833160e24217ecb57612d3943db2cd'
    for row in z.read('SHA256SUMS').decode().splitlines():
        digest,name=row.split(maxsplit=1)
        name=name.removeprefix('./')
        if name=='all-agentd-unit-tests.log':
            target=digest
        else:
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
    raw=z.read('all-agentd-unit-tests.log')
    h=hashlib.sha256(); end=0
    for line in raw.splitlines(keepends=True):
        h.update(line); end+=len(line)
        if h.hexdigest()==target:
            break
    assert h.hexdigest()==target and end<len(raw)
    def passes(data):
        return len(set(re.findall(rb'^\s*PASS \[[^\n]*\]\s*\([^\n]*?\) codex-hepta-agentd (\S+)\s*$',data,re.M)))
    assert passes(raw)==615 and passes(raw[:end])==611 and b'Summary [' not in raw
    print(json.dumps(dict(source=source,run=45120356492,job=137516904575,artifact=14795645660,
        full_job='cancelled',cold_startup_step_seconds=1687,full_suite_step_seconds=36,selected=1552,
        archive_pass_lines=615,manifest_pass_lines=611,original_log_bytes=len(raw),
        manifest_prefix_bytes=end,additional_bytes=len(raw)-end,
        whole_log_sha256=hashlib.sha256(raw).hexdigest(),internally_sealed_prefix_sha256=target),indent=2))
