"""Independent tamper review of the fixed history manifest; no old source executes."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

WORK = Path('/workspace/scratch/b5d58a60397e/memory-cell-work/qualification/memory-cell-v15')
OLD = Path('/workspace/scratch/c7093c761bbc/hepta-memory-v15/qualification/memory-cell-v15')
source = WORK / 'device_qualification/verify_receipts.py'
spec = importlib.util.spec_from_file_location('independent_history_verifier', source)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
original_root = verifier.ROOT
checks_path = Path('evidence/ci_41950367467/checks.json')
checks_raw = (OLD / checks_path).read_bytes()
checks = json.loads(checks_raw)
results = []
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary) / 'v15'
    root.mkdir()
    for name, sha in checks['source_files_sha256'].items():
        raw = (OLD/name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == sha
        (root/name).write_bytes(raw)
    (root/checks_path).parent.mkdir(parents=True)
    (root/checks_path).write_bytes(checks_raw)
    (root/'evidence/checks.json').write_bytes(checks_raw)
    device = root/'device_qualification'
    device.mkdir()
    for name in ('receipts.json','costs.json'):
        shutil.copyfile(WORK/'device_qualification'/name, device/name)
    shutil.copytree(WORK/'device_qualification/history', device/'history')
    verifier.ROOT = device
    baseline = verifier.verify()
    assert baseline['passed']
    results.append({'case':'unmodified historical source and receipts', 'passed':True,
                    'signed_objects':baseline['unique_signed_objects_verified'],
                    'historical_receipt_qualifies_current_device_code':baseline['historical_receipt_qualifies_current_device_code']})
    history_file = device/'history/manifest.json'
    history_raw = history_file.read_bytes()
    archive_file = device/'history/sources.zip'
    archive_raw = archive_file.read_bytes()
    old_manifest = json.loads(history_raw)
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as z:
        members = {n:z.read(n) for n in z.namelist()}
    members['authority.py'] += b'\n# attempted historical source rebinding\n'
    new_manifest = copy.deepcopy(old_manifest)
    raw = members['authority.py']
    new_manifest['files']['authority.py'] = {
        'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest(),
        'git_blob_sha1':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
    with zipfile.ZipFile(archive_file,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for n,raw in sorted(members.items()):z.writestr(n,raw)
    new_manifest['snapshot_sha256'] = hashlib.sha256(archive_file.read_bytes()).hexdigest()
    history_file.write_text(json.dumps(new_manifest,sort_keys=True,indent=2)+'\n')
    try:
        verifier.verify()
    except ValueError as e:
        assert str(e) == 'historical source manifest identity mismatch', str(e)
        results.append({'case':'change historical source and consistently rehash archive/file metadata/manifest',
                        'rejected':True,'reason':str(e),
                        'pinned_manifest_constant_unchanged':verifier.HISTORY_MANIFEST_SHA256})
    else:raise RuntimeError('historical source rebinding accepted')
    verifier.ROOT = original_root
report = {'schema':'hepta.memory.independent-history-review.v1',
          'verifier_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'scope':'Temporary copy only. Archived sources are read as data and never imported or executed. No production or historical originals changed.',
          'checks':results,
          'limit':'The verifier source itself and current local protocol receipts remain trusted. This test does not assert resistance to replacing trusted code or rolling back its entire trust root.'}
Path(__file__).with_name('history-review.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
