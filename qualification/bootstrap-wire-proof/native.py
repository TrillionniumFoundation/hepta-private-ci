import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

arm, binary = sys.argv[1], Path(sys.argv[2]).resolve()
evidence = Path(os.environ['RUNNER_TEMP']) / 'wire-evidence'
listed = subprocess.check_output([binary, '--list'], text=True)
names = set(re.findall(r'^(.+): test$', listed, re.M))
wanted = ['versioned_record_rejects_hybrid_unknown_fields_and_invalid_live_binding',
          'successor_deployment_requires_every_original_pin_and_bounded_context',
          'root_broker_late_enrolls_publishes_and_recovers_original_current']
selection = {}
for short in wanted:
    matches = [n for n in names if n.rsplit('::', 1)[-1] == short]
    assert len(matches) == 1, (short, matches)
    selection[short] = matches[0]
assert os.getuid() == os.geteuid() != 0
variables = ['HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE',
             'HEPTA_CHECKPOINT_TEST_ROOT','HEPTA_Q24_FACTORY_WITNESS_BIND','HEPTA_Q24_FACTORY_WITNESS_SOURCE']
prefix = ['sudo','-n','env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin',*[f'{k}={os.environ[k]}' for k in variables],
          'python3','-c',"import os,sys; assert os.getuid()==os.geteuid()==0; print('actual UID0',flush=True); os.execv(sys.argv[1],sys.argv[1:])"]
regular = [selection[w] for w in wanted[:-1]]
root = selection[wanted[-1]]
out = {'TEST-only observer': True, 'selection': selection, 'ELF_SHA256': hashlib.sha256(binary.read_bytes()).hexdigest()}
ok = True
for group, args, expected in [
        ('ordinary', [binary,'--exact','--test-threads=1',*regular], regular),
        ('uid0', [*prefix,binary,'--exact','--ignored','--show-output','--test-threads=1',root], [root])]:
    log = evidence / f'{arm}-{group}.log'
    with log.open('wb') as fp:
        p = subprocess.run(args, stdout=fp, stderr=subprocess.STDOUT)
    text = log.read_text()
    rows = re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)$', text, re.M)
    count = text.count('QUALIFIED_WIRE_OBJECT v1-positive=1 v2-positive=1 encoder-negative=2 decoder-negative=16 reencode-bytes=2')
    status = p.returncode == 0 and sorted(rows) == sorted((n,'ok') for n in expected)
    if group == 'uid0':
        status = status and count > 0 and 'actual UID0' in text and all(
            f'ROOT_PUBLICATION_ORIGINAL lifecycle=passed terminal={s}' in text for s in ['StalePrepare','Revoked'])
    ok &= status
    out[group] = {'exit': p.returncode, 'matched': rows, 'codec_observations': count,
                  'pass': status, 'summary': re.findall(r'^test result:.+', text, re.M),
                  'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    print(arm,group,out[group],flush=True)
    if p.returncode:
        print('\n'.join(text.splitlines()[-35:]))
(evidence/f'native-{arm}.json').write_text(json.dumps(out,indent=2)+'\n')
sys.exit(0 if ok else 1)
