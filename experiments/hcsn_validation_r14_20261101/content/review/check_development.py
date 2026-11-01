"""Check retained development receipts and actual tensor freeze/update evidence."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
CONTENT = HERE.parent
REPO = CONTENT.parents[2]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tensor_hash(state):
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        array = tensor.detach().cpu().contiguous().numpy()
        digest.update(name.encode());digest.update(str((array.shape,array.dtype.str)).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():raise FileExistsError('Preserve previous development check')
    import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    checks=[]
    def check(name,condition,**detail):
        checks.append(dict(check=name,passed=bool(condition),**detail))
    results=CONTENT/'results'
    failed=read(results/'development_process/FAILED_ATTEMPT.json')
    old_receipts=[read(results/'development_process'/name) for name in ('freeze.json','frozen_backend.json')]
    old_cpu=sum(r['cpu_seconds'] for r in old_receipts)
    check('failed_attempt_receipts',old_receipts[0]['exit_code']==0 and old_receipts[1]['exit_code']==1
          and abs(old_cpu-failed['child_cpu_seconds'])<1e-12 and failed['heldout_opened'] is False)
    check('failed_attempt_retained',not (results/'development_01/fits/recall_s12031_frozen_backend/selected.pt').exists()
          and (results/'development_01/source').is_dir())
    dev=results/'development_02'
    protocol=read(dev/'PROTOCOL.json');freeze=read(dev/'SOURCE_FREEZE.json')
    total=read(results/'development_02_process/TOTAL.json')
    receipts=[read(results/'development_02_process'/name) for name in ('freeze.json','frozen_backend.json','joint_backend.json')]
    check('development02_success_receipts',total['records']==receipts and all(r['exit_code']==0 and r['heldout_opened'] is False for r in receipts))
    cpu=sum(r['cpu_seconds'] for r in receipts)
    check('development02_cost',abs(cpu-total['child_cpu_seconds'])<1e-12)
    check('development02_two_updates_no_heldout',protocol['updates']==2 and total['heldout_opened'] is False and not (dev/'heldout').exists())
    formal=results/'formal_01'
    check('fixed_source_identity',freeze['files']==read(formal/'SOURCE_FREEZE.json')['files'])
    models=[]
    selected_steps={}
    for mode in ('frozen_backend','joint_backend'):
        folder=dev/'fits'/('recall_s12031_'+mode)
        summary=read(folder/'SUMMARY.json')
        selected,final=(torch.load(folder/name,map_location='cpu',weights_only=True) for name in ('selected.pt','final.pt'))
        check(mode+'/checkpoint_bytes',sha(folder/'selected.pt')==summary['selected_checkpoint_sha256']
              and sha(folder/'final.pt')==summary['final_checkpoint_sha256'])
        check(mode+'/steps',final['step']==2 and selected['step']==summary['selected_step'] and selected['step'] in (0,2))
        selected_steps[mode]=selected['step']
        check(mode+'/validation_alignment',all(not any(row.values()) for row in read(folder/'ONLINE_VALIDATION_ALIGNMENT.json').values()))
        check(mode+'/no_failure',not (folder/'FAILED.json').exists() and summary['heldout_opened'] is False)
        for family in protocol['families']:
            entry=protocol['inputs']['recall_s12031_joint_'+family]
            source=REPO/entry['path']
            check(mode+'/'+family+'/inherited_bytes',sha(source)==entry['sha256'])
            initial=torch.load(source,map_location='cpu',weights_only=True)['model_state']
            states=(initial,selected['models'][family]['state'],final['models'][family]['state'])
            hashes=list(map(tensor_hash,states))
            check(mode+'/'+family+'/initial_identity',hashes[0]==summary['initial_hashes'][family]==selected['initial_hashes'][family]==final['initial_hashes'][family])
            components={}
            for group in ('encoder','core','readout'):
                group_hashes=[tensor_hash({k:v for k,v in state.items() if k.startswith(group+'.')}) for state in states]
                nonzero=summary['nonzero_gradient_steps'][family][group]
                components[group]=dict(nonzero_gradient_steps=nonzero,selected_changed=group_hashes[0]!=group_hashes[1],final_changed=group_hashes[0]!=group_hashes[2])
                check(mode+'/'+family+'/'+group,all(h==group_hashes[0] for h in group_hashes) and nonzero==0 if mode=='frozen_backend'
                      else group_hashes[0]!=group_hashes[2] and nonzero==2)
            if mode=='frozen_backend':check(mode+'/'+family+'/whole_backend',hashes[0]==hashes[1]==hashes[2])
            models.append(dict(mode=mode,family=family,initial_sha256=hashes[0],selected_sha256=hashes[1],final_sha256=hashes[2],components=components))
    report=read(formal/'review/INDEPENDENT_RESULTS_AUDIT_01.json')
    check('formal_independent_audit_pass',report['status']=='pass' and not report['failed_checks'])
    frozen=[b for f in report['result']['fits'] if f['mode']=='frozen_backend' for b in f['backends']]
    joint=[b for f in report['result']['fits'] if f['mode']=='joint_backend' for b in f['backends']]
    check('formal_all48_frozen',len(frozen)==48 and all(b['initial_sha256']==b['selected_sha256']==b['final_sha256'] for b in frozen))
    check('formal_all48_joint_selected_and_final_changed',len(joint)==48 and all(b['initial_sha256']!=b['selected_sha256'] and b['initial_sha256']!=b['final_sha256'] for b in joint))
    check('formal_all144_joint_components_updated',all(c['selected_changed'] and c['final_changed'] and c['nonzero_gradient_steps']==256 for b in joint for c in b['components'].values()))
    result=dict(schema='hcsn.r14.content.development-and-weight-followup.v1',audited_at_utc=datetime.now(timezone.utc).isoformat(),
        script_sha256=sha(Path(__file__)),status='pass' if all(r['passed'] for r in checks) else 'fail',checks=checks,
        development01_child_cpu_seconds=old_cpu,development02_child_cpu_seconds=cpu,total_development_child_cpu_seconds=old_cpu+cpu,
        development02_selected_steps=selected_steps,development02_models=models,
        formal_audit_sha256=sha(formal/'review/INDEPENDENT_RESULTS_AUDIT_01.json'),
        formal_joint_selected_steps=[{k:f[k] for k in ('task','seed','selected_step')} for f in report['result']['fits'] if f['mode']=='joint_backend'],
        scope='Direct retained receipt and tensor checks; no training or model forward. Gradient counts are execution logs supported by final tensor changes. Development02 is a two-update, one task/seed smoke run and never opened heldout data.')
    with args.report.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(status=result['status'],checks=len(checks),sha256=sha(args.report),report=str(args.report))))
    return int(result['status']!='pass')


if __name__=='__main__':raise SystemExit(main())
