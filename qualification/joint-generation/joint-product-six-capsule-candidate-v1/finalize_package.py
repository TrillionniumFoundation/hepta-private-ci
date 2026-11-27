"""Static capacity accounting and source freeze. Never executes consumer/tests."""
import ast
import hashlib
import json
from pathlib import Path
import resource
import time

ROOT=Path(__file__).absolute().parent
H=lambda b:hashlib.sha256(b).hexdigest()
def enc(x):return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('ascii')

def main():
    start=time.monotonic();cpu=time.process_time()
    if (ROOT/'FREEZE.json').exists():raise FileExistsError('already frozen; preserve old identity')
    manifest=json.loads((ROOT/'capsule-manifest.json').read_bytes());capsules=manifest['capsules']
    pins={e['path']:[e['bytes'],e['sha256']] for e in manifest['files']}
    receipts={}
    for name,c in capsules.items():
        value={'schema':'joint-capsule-materialization-v1','status':'MATERIALIZED_BYTES_VERIFIED_NOT_QUALIFIED','capsule':name,'manifest_sha256':H((ROOT/'capsule-manifest.json').read_bytes()),'files':{p:{'bytes':pins[p][0],'sha256':pins[p][1]} for p in sorted(c['source_files']+c['input_files'])},'runner_executed':False,'shared_lock_created':False}
        receipts[name]=len(enc(value))
    names=[]
    for p in sorted(ROOT.glob('*.py')):
        tree=ast.parse(p.read_bytes(),filename=str(p))
        if p.name=='test_materialize.py':
            for node in tree.body:
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NEGATIVE_CASES' for t in node.targets):names=ast.literal_eval(node.value)
    assert len(names)==46 and len(set(names))==46
    selected='joint-policy-delivery-candidate-v2';one=capsules[selected]
    first=sorted(one['source_files']+one['input_files'])[0]
    six_bytes=sum(c['expanded_bytes'] for c in capsules.values());six_files=sum(c['expanded_files'] for c in capsules.values())
    fixture_bytes=manifest['storage_bytes']+(ROOT/'capsule-manifest.json').stat().st_size
    fixture_files=manifest['storage_files']+1
    # Successful schedule retains six successes, one validated-cache success,
    # all-byte drift failure, one-file injected failure, a 4-byte prior marker,
    # and one restored-to-original package fixture. All symlinks are removed.
    fixed_bytes=six_bytes+sum(receipts.values())+fixture_bytes+2*one['expanded_bytes']+receipts[selected]+pins[first][0]+4
    fixed_files=six_files+6+fixture_files+2*one['expanded_files']+1+1+1
    cap={'schema':'joint-six-capsule-capacity-v1','remote_blob_max_bytes':511999,
         'manifest_exact_max_bytes':(ROOT/'capsule-manifest.json').stat().st_size,
         'manifest_sha256':H((ROOT/'capsule-manifest.json').read_bytes()),
         'logical_original_files':len(manifest['files']),'stored_blob_files':manifest['storage_files'],'unique_stored_blob_bytes':manifest['storage_bytes'],
         'stored_zip_records':79,'max_stored_zip_record_bytes':401600,'terminal_zip_record_bytes':4960,
         'original_frozen_entries':173,'original_target_FREEZE_files':6,'runtime_input_union_files':13,'runtime_input_union_bytes':1772664,
         'six_expanded_data_files':six_files,'six_expanded_data_bytes':six_bytes,
         'six_completion_receipts_bytes':sum(receipts.values()),'six_expanded_complete_files':six_files+6,'six_expanded_complete_bytes':six_bytes+sum(receipts.values()),
         'workspace_max_original_file_bytes':1560407,
         'workspaces':{n:dict(c,completion_receipt_bytes=receipts[n],complete_files=c['expanded_files']+1,complete_bytes=c['expanded_bytes']+receipts[n]) for n,c in capsules.items()},
         'positive_cases':7,'negative_cases':46,'negative_case_names':names,
         'retained_fixture_and_workspace_files':fixed_files,'retained_fixture_and_workspace_bytes':fixed_bytes,
         'fixture_package_files':fixture_files,'fixture_package_bytes':fixture_bytes,
         'injected_failure_retained_path':first,'injected_failure_retained_bytes':pins[first][0],
         'tests_log_max_bytes':65536,'test_report_max_bytes':32768,'outer_receipt_max_bytes':262144,
         'retained_output_max_files':fixed_files+3,'retained_output_max_bytes':fixed_bytes+65536+32768+262144,
         'per_file_RLIMIT_FSIZE_bytes':8*2**20,
         'total_bound_timing':'Exact fixed successful fixture/workspace inventory checked in child before report; final full inventory and report/log/receipt bounds checked in outer before terminal success. No disk quota or guarantee after arbitrary OS failures/unexpected writes.',
         'temporary_fixture_peak_note':'Schema mutation manifests are compact except exact max+1 oversize refusal; a part may grow by one byte. Both are restored before retained-cache output; final full schedule is larger than those earlier peaks. Symlink backups move existing bytes and all symlinks are removed.',
         'all_package_files_including_FREEZE':0,'all_package_bytes_including_FREEZE':0,'max_package_blob_bytes':0}
    # Prefix before later accounting/hash/write work, never an all-lifetime claim.
    (ROOT/'FINALIZATION_COST.json').write_bytes(enc({'scope':'Static AST parse and capacity-generation measured prefix only; no imports of consumer or test, no qualification, model or remote operation','CPU_prefix_seconds':time.process_time()-cpu,'wall_prefix_seconds':time.monotonic()-start,'self_rusage_prefix':list(resource.getrusage(resource.RUSAGE_SELF)),'remaining_hash_write_and_outer_tail':'unknown_not_zero','earlier_manual_review_and_authoring':'additional unmeasured, not zero'}))
    def inventory():return {str(p.relative_to(ROOT)):p for p in sorted(ROOT.rglob('*')) if p.is_file() and p != ROOT/'FREEZE.json'}
    # Only size/count fixed point, no self hash. FREEZE hashes CAPACITY after it settles.
    for _ in range(20):
        (ROOT/'CAPACITY.json').write_bytes(enc(cap))
        files=inventory();fake_freeze=enc({p:'0'*64 for p in files})
        count=len(files)+1;size=sum(p.stat().st_size for p in files.values())+len(fake_freeze)
        max_size=max([len(fake_freeze)]+[p.stat().st_size for p in files.values()])
        if (cap['all_package_files_including_FREEZE'],cap['all_package_bytes_including_FREEZE'],cap['max_package_blob_bytes'])==(count,size,max_size):break
        cap.update(all_package_files_including_FREEZE=count,all_package_bytes_including_FREEZE=size,max_package_blob_bytes=max_size)
    else:raise AssertionError('capacity size fixed point')
    files=inventory();freeze={p:H(f.read_bytes()) for p,f in files.items()}
    (ROOT/'FREEZE.json').write_bytes(enc(freeze))
    assert all(p.stat().st_size<=511999 for p in ROOT.rglob('*') if p.is_file())
    assert sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())==cap['all_package_bytes_including_FREEZE']
    print(json.dumps({'freeze_sha256':H((ROOT/'FREEZE.json').read_bytes()),'package_files':cap['all_package_files_including_FREEZE'],'package_bytes':cap['all_package_bytes_including_FREEZE'],'max_blob_bytes':cap['max_package_blob_bytes'],'expected_retained_fixture_files':fixed_files,'expected_retained_fixture_bytes':fixed_bytes,'maximum_success_retained_bytes':cap['retained_output_max_bytes'],'negative_cases':46,'positive_cases':7},sort_keys=True))

if __name__=='__main__':main()
