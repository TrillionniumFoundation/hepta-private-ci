#!/usr/bin/env python3
"""Verify immutable plan archive bytes and the narrow v2 textual erratum."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ARCHIVE = 'ORIGINAL_REVIEW.tar.xz'
EXPECTED_BLOB = '11a0ce75307c9d3088370a0de5fdc1be8610f4ee'
EXPECTED_SHA = 'ae0ff064a232591ad330a9d5b8debd12e696c7ec4191542ba7ab70112e5efc79'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def main():
    remote = HERE / 'ARCHIVE_READBACK.json'
    if remote.exists():
        payload = json.loads(remote.read_text())
        assert payload['encoding'] == 'base64'
        assert payload['sha'] == EXPECTED_BLOB
        data = base64.b64decode(''.join(payload['content'].split()), validate=True)
    else:
        data = (HERE / ARCHIVE).read_bytes()
    assert len(data) == 51076 and digest(data) == EXPECTED_SHA
    assert git_blob(data) == EXPECTED_BLOB
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
        for member in archive.getmembers():
            assert member.isfile(), member.name
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts
            assert member.name not in members
            members[member.name] = archive.extractfile(member).read()
    assert len(members) == 23
    manifest = json.loads(members['FILE_MANIFEST.json'])
    rows = manifest['members']
    assert set(members) == {'FILE_MANIFEST.json'} | {row['path'] for row in rows}
    for row in rows:
        content = members[row['path']]
        assert len(content) == row['bytes'] and digest(content) == row['sha256']
        assert git_blob(content) == row['gitBlob']
    expected = [
        ('REPORT_V2.md', 12275, '59bc4324667572c72aafce7557798d127203fd02bd8510bfad2730093176f62e', '98ab7760791682702bbd03d66f5c9f15700e29de'),
        ('PLAN_V2.json', 27533, 'b0ee6ada05a667dbe268a9bd9be286b1dfadb223f598610708d04c520f0df7df', '27e96138073db39636b521cdef246dcef3b36fdc'),
        ('BUDGET_ATTRIBUTION_ERRATUM.json', 2310, '41c5d9b11de893cba6fac828929748aec5b9a32d970a99d3df20320e4f273e81', 'eff627f5a5df1b15f7fbf1dd573a60483062ae4e'),
        ('V2_READBACK_AUDIT.json', 2449, 'aab569fddd7ddb6bd1a955732ab2bdfe9a9af7bad2949af26d3c0e3a1292394f', '941052a7fb71809b8a28c70458117a46fa46e144'),
    ]
    readbacks = HERE / 'V2_ROOT_GIT_READBACKS.json'
    decoded = json.loads(readbacks.read_text()) if readbacks.exists() else None
    for index, (name, size, sha, blob) in enumerate(expected):
        content = decoded[str(index)]['content'].encode() if decoded else (HERE / name).read_bytes()
        assert len(content) == size and digest(content) == sha and git_blob(content) == blob
        members[name] = content
    old_plan = json.loads(members['PLAN.json'])
    new_plan = json.loads(members['PLAN_V2.json'])
    evidence = new_plan['historicalOriginal'].pop('interruptionEvidence')
    assert old_plan == new_plan
    assert evidence['schedulerCancellationCause'] == 'UNKNOWN_NOT_INDEPENDENTLY_OBSERVED'
    old_lines = members['REPORT.md'].decode().splitlines()
    new_lines = members['REPORT_V2.md'].decode().splitlines()
    assert len(old_lines) == len(new_lines)
    changed = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    assert len(changed) == 1
    assert '该中断是作业窗口边界' in changed[0][0]
    assert '只是时间一致性推断' in changed[0][1]
    result = {
        'schema': 'hepta.windows-successor-root-byte-audit.v1',
        'checkedAt': datetime.now(timezone.utc).isoformat(),
        'result': 'PASS_FULL_REMOTE_ARCHIVE_BYTES_AND_NARROW_ERRATUM',
        'archiveGitBlob': EXPECTED_BLOB, 'archiveSha256': EXPECTED_SHA,
        'archiveBytes': len(data), 'regularMembers': 23,
        'manifestRowsVerified': len(rows), 'fullV2GitTextReadbacks': 4,
        'reportChangedLines': 1, 'planChange': 'historicalOriginal.interruptionEvidence added only',
        'v1PlanValidatorReexecuted': False, 'v2NativeQualificationClaimed': False,
        'currentWorkflowExpectedCases': 167, 'conditionalProposedCases': 170,
        'newCITriggers': 0, 'nativeCasesExecutedByThisAudit': 0,
        'schedulerCancellationCause': 'UNKNOWN_NOT_INDEPENDENTLY_OBSERVED',
    }
    (HERE / 'ROOT_READBACK_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
