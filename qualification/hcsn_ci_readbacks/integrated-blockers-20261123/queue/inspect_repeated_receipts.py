"""Independently bind the real per-attempt libtest log, not just its Bazel XML."""
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile

FOUR = (
    'caller_abort_after_core_started_keeps_exact_authority_until_persistence',
    'core_error_after_started_never_releases_ambiguous_dispatch',
    'explicitly_started_rejected_queue_messages_remain_durable',
    'rejected_queue_messages_remain_durable_and_block_followups',
)
ROW = re.compile(r'^test (\w+) \.\.\. (ok|FAILED|ignored)$', re.MULTILINE)
SUMMARY = re.compile(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in (\d+(?:\.\d+)?)s$',re.M)


def digest(b):
    return hashlib.sha256(b).hexdigest()


def read_archive(filename):
    path = Path(filename)
    record = {'file':path.name, 'sha256':digest(path.read_bytes())}
    attempts = []
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        record['source_objects'] = archive.read('sources.txt').decode().splitlines()
        for phase in ['first','second']:
            prefix = phase + '/'
            outcome = json.loads(archive.read(prefix+'outcome.json'))
            for name in ('test.log','test.xml'):
                assert digest(archive.read(prefix+name)) == outcome[name]
            raw = archive.read(prefix+'test.log').decode('utf-8').replace('\r\n','\n')
            rows = ROW.findall(raw)
            cases = dict(rows)
            assert len(rows) == len(cases) == 39
            assert all(k in cases for k in FOUR)
            assert cases == outcome['cases']
            m = SUMMARY.search(raw)
            assert m is not None
            status,passed,failed,ignored,measured,filtered,elapsed = m.groups()
            assert list(map(int,(passed,failed,ignored))) == [sum(s == t for s in cases.values()) for t in ('ok','FAILED','ignored')]
            assert int(measured) == int(filtered) == 0
            assert (outcome['original_returncode']==0) == (status=='ok')
            attempts.append(dict(phase=phase,head=outcome['head'],status=status,passed=int(passed),failed=int(failed),ignored=int(ignored),filtered=int(filtered),elapsed=float(elapsed),four={k:cases[k] for k in FOUR},case_set_sha256=digest(('\n'.join(sorted(cases))+'\n').encode()),source_log_sha256=outcome['test.log'],source_xml_sha256=outcome['test.xml']))
    record['attempts']=attempts
    return record


if __name__ == '__main__':
    records = [read_archive(p) for p in sys.argv[1:]]
    assert len({a['case_set_sha256'] for r in records for a in r['attempts']}) == 1
    print(json.dumps(records,indent=2))
