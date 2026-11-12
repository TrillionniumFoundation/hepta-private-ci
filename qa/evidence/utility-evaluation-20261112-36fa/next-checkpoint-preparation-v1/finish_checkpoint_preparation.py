#!/usr/bin/env python3
"""Prepare immutable evidence objects locally; never publish a commit/ref/PR."""
from pathlib import Path
from datetime import datetime, timezone
import base64
import gzip
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-next-evidence-preparation-v1')
ROOT = Path('/tmp/hepta-36fa-after2268-20261112')
ACTUAL = Path('/tmp/hepta-36fa-final-canonical-alignment-launch-v1')

def ident(b):
    return dict(bytes=len(b), sha256=hashlib.sha256(b).hexdigest(),
                git_blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest())

def read(p):
    s=p.stat();b=p.read_bytes();e=p.stat()
    assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)==(e.st_dev,e.st_ino,e.st_size,e.st_mtime_ns),str(p)
    return b

def write(name,b):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==b,name
    else:p.write_bytes(b)
    return p

def jbytes(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def jwrite(name,v):return write(name,jbytes(v))

def main():
    original=json.loads((OUT/'BASE_2268_FILEMAP.json').read_bytes())
    files=json.loads((OUT/'FULL_FILEMAP_WITH_CANONICAL_OBSERVATION_BEFORE_README.json').read_bytes())
    initial=dict(files)
    proof=json.loads((OUT/'PATH_PROVENANCE.json').read_bytes())
    supplied={}
    new_records=[]
    def add(path,b,kind,local=None):
        pin=ident(b)
        if path in files:assert files[path]==pin['git_blob'],path
        else:files[path]=pin['git_blob']
        row={'path':path,**pin,'kind':kind}
        if local:row['local_path']=str(local)
        proof.setdefault(path,[]).append(row)
        supplied.setdefault(pin['git_blob'],{'local_path':str(local),**pin,'paths':[]})['paths'].append(path)
        return row
    # Root's upload ledger is copied, not executed or modified.
    ledger=read(ROOT/'ROOT_UPLOADS.jsonl')
    prior=json.loads((OUT/'INPUT_SNAPSHOT_INDEX.json').read_bytes())
    last=next(x for x in prior if x['source']==str(ROOT/'ROOT_UPLOADS.jsonl'))
    assert ledger.startswith(read(Path(last['snapshot'])))
    ledger_path=write('final-snapshots/ROOT_UPLOADS.original.jsonl',ledger)
    ledger_rows=[json.loads(s) for s in ledger.splitlines() if s]
    for row in ledger_rows:
        assert row['full_readback_equal'] is True
        if row['path'] in files:assert files[row['path']]==row['sha'];continue
        b=read(Path(row['local_path']));assert ident(b)=={'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['sha']}
        snap=write('final-snapshots/'+Path(row['local_path']).name,b)
        add(row['path'],b,'Root original create/full-readback ledger and independently matched bytes',snap)
    # The source publication was done by Root; this script only preserves its existing records.
    for name in ('SOURCE_CANONICAL_REF_PUBLICATION_INTENT.json','SOURCE_CANONICAL_REF_UPDATE.response.json','SOURCE_CANONICAL_REF_READ.response.json'):
        b=read(ROOT/name);p=write('source-publication/'+name,b)
        add('canonical-final/source-publication/'+name,b,'actual Root publication original; new immutable object only',p)
    publication=json.loads((OUT/'source-publication/SOURCE_CANONICAL_REF_READ.response.json').read_bytes())
    observed=json.loads(publication['structuredContent']['content'])
    assert observed['object']['sha']=='246d8cb614770252ee42029a5c014f2a4904176a'
    # All canonical terminal/read originals. Large typed controls are retained via exact gzip/base64 parts.
    reconstruction=[]
    for p in sorted(ACTUAL.iterdir()):
        if not p.is_file():continue
        b=read(p)
        if p.name.endswith('.GITHUB.original.json') and len(b)>400000:continue
        if len(b)<=400000:
            snap=write('canonical-actual/'+p.name,b)
            add('canonical-final/actual/'+p.name,b,'actual native original or exact already-issued control; not a new native execution',snap)
        else:
            assert p.name in ('ACTUAL_PROCESS_INPUT.json','ACTUAL_STDIN.json')
            packed=gzip.compress(b,compresslevel=9,mtime=0)
            parts=[]
            for i,start in enumerate(range(0,len(packed),196608),1):
                raw_part=packed[start:start+196608]
                encoded=base64.b64encode(raw_part)+b'\n'
                name=p.name+'.gz.part'+str(i).zfill(3)+'.b64'
                dest=write('canonical-actual/'+name,encoded)
                row=add('canonical-final/actual/'+name,encoded,'derived lossless transport of exact existing original bytes',dest)
                parts.append({'path':row['path'],**ident(encoded),'decoded_gzip_part':ident(raw_part)})
            reconstruction.append({'original_name':p.name,'original':ident(b),'gzip':ident(packed),'parts':parts,
                'reconstruction':'base64-decode each part (ignore the final LF), concatenate in listed order, then gzip-decompress; check original length/SHA256/Git blob',
                'new_native_read_or_execution':False})
    rpath=jwrite('CANONICAL_ORIGINAL_TRANSPORT_RECONSTRUCTION.json',{'format':'hepta-canonical-original-control-transport-v1','originals':reconstruction})
    add('canonical-final/actual/CONTROL_TRANSPORT_RECONSTRUCTION.json',read(rpath),'derived transport manifest',rpath)
    # Verify every preserved base path before any separately proposed README replacement.
    assert len(original)==2268 and all(files[k]==v for k,v in original.items())
    assert files['checkpoints/README_2268FILES_BEFORE_FINAL_NONRUST.md']==original['README.md']=='3e8b17601e82f5f7be49d172784bc2c4a452a080'
    addendum=json.loads((OUT/'CANONICAL_OBSERVATION_ADDENDUM.json').read_bytes())
    for row in addendum['added']:proof.setdefault(row['path'],[]).append(row)
    queue=[]
    already=set(original.values())
    already.update(x['git_blob'] for x in json.loads((OUT/'NEW_SMALL_OBJECT_UPLOADS.json').read_bytes())['objects'])
    already.update(x['sha'] for x in ledger_rows)
    already.update(('2678be6c23d00696d356e988120887a61f88bfab','879685b4776ef2f9237587ae20cc8916391504de'))
    for sha,row in supplied.items():
        if sha not in already:queue.append(row)
    jwrite('FINAL_NATIVE_AND_PUBLICATION_UPLOAD_QUEUE.json',sorted(queue,key=lambda x:x['git_blob']))
    jwrite('FINAL_NATIVE_AND_PUBLICATION_INDEX.json',sorted(supplied.values(),key=lambda x:x['git_blob']))
    jwrite('FINAL_EVIDENCE_FILEMAP_BEFORE_README.json',files)
    jwrite('FINAL_EVIDENCE_INCREMENTAL_FILEMAP.json',{k:v for k,v in files.items() if k not in original})
    jwrite('FINAL_PATH_PROVENANCE.json',proof)
    jwrite('FINAL_FACTS_AND_LIMITS.json',{
      'format':'hepta-next-evidence-checkpoint-facts-v1',
      'prepared_at_utc':datetime.now(timezone.utc).isoformat(),
      'old_evidence_files':2268,'new_evidence_paths_before_preparation_metadata':len(files)-2268,
      'combined_evidence_files_before_preparation_metadata':len(files),
      'all_2268_paths_same_sha_before_readme':True,'old_readme_archived':True,
      'source_commit':'246d8cb614770252ee42029a5c014f2a4904176a','source_tree':'d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087',
      'source_parents':['9c4a11f61d30e9cc352bf44d56c98909d202a55d'],
      'source_branch':'codex/utility-evidence-closure-20261112-36fa','source_publication_by_Root_actual_ref_readback_equal':True,
      'clean_native_alignment_job':'1a1d1ddc8e4-2564-1c83','native_alignment_status':'normal exit0; all3 audits verified; source bytes/modes unchanged',
      'actual_clean_inventory':{'bytes':5611184,'sha256':'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e','git_blob':'663373f936c2ff130aec96ad34654cc9811773c2','entries':15188},
      'finalfmt_first_attempt':'actual normal exit1 before source edits or formatter because original global guard rejected active rustc',
      'finalfmt_second_attempt':'actual normal exit0;11 applied nonRust paths; original fmt900 exit0; no additional source changes',
      'finalfmt_transport_failures_preserved':3,'canonical_result_read_timeout_preserved':1,
      'v1_scope_gap':'21 of34 scoped functions were not reached by default newQA despite local18PASS',
      'v2_scope_repair':'same18 methods;3line full20path loop; actual234 successful scope observations cover34 scopes; old attacks/assertions retained',
      'complete_source_gates':'not_started_at_latest_bound_approval','native_qualification':'not_started_at_latest_bound_approval',
      'real_qualified_task_chains':0,'merged_or_production_activated':False,
      'this_preparation_created_commit_ref_PR_H_or_source_mutation':False,
      'root_upload_ledger_snapshot':ident(ledger),'root_upload_rows':len(ledger_rows),
      'future_execution_records_must_be_appended_not_inferred':True,
    })
    print(json.dumps({'files':len(files),'increment':len(files)-2268,'new_native_publication_objects_to_upload':len(queue),'bytes':sum(x['bytes'] for x in queue)}))

if __name__=='__main__':main()
