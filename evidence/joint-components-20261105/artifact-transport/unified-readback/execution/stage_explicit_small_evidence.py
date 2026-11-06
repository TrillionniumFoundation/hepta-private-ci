"""Copy only the explicit hash-pinned small evidence whitelist; never recurse."""
import hashlib
import json
import os
from pathlib import Path
import stat

ROOT=Path('/workspace/scratch/93bfcfe29fc8')
RUN=ROOT/'w1/unified-archive-readback-execution-01'
FORENSICS=ROOT/'w1/unified-postrun-forensics'
DEST=ROOT/'hepta-joint-evidence/evidence/joint-components-20261105/artifact-transport/unified-readback/execution'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def read_regular(path,cap=1024*1024):
    assert path.parent.resolve(strict=True)==path.parent
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=cap
        raw=f.read(cap+1);after=os.fstat(f.fileno())
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    assert identity(before)==identity(after) and len(raw)==before.st_size
    return raw


def main():
    whitelist_raw=read_regular(FORENSICS/'corrected-small-delivery-manifest.json')
    assert sha(whitelist_raw)=='f646730b4b0ab895eda8161439c9bcdad12824d83d6c4c85b048acfdc6db852f'
    whitelist=json.loads(whitelist_raw);assert len(whitelist['files'])==37 and whitelist['small_file_bytes']==2927539
    plan=[]
    for row in whitelist['files']:
        relative=row['path'];source=RUN/relative
        assert row['bytes']<=1024*1024 and '/elf/' not in relative and '.partial/' not in relative
        assert not relative.endswith(('.elf','.xz'))
        if relative.startswith('output/'):
            target=relative[len('output/'):]
            if '/extracted/' in target:
                phase,leaf=target.split('/extracted/',1)
                target='embedded-metadata/'+phase+'/'+leaf
        else:target=relative
        plan.append((source,target,row['bytes'],row['sha256']))
    additions=[
        (FORENSICS/'first-delivery-original.json','history/first-delivery-manifest.json'),
        (FORENSICS/'unknown-artifacts.json','forensics/unknown-artifacts.json'),
        (FORENSICS/'own-operation-records.json','forensics/own-operation-records.json'),
        (FORENSICS/'exact-naming-source-excerpts.json','forensics/exact-naming-source-excerpts.json'),
        (FORENSICS/'corrected-small-delivery-manifest.json','forensics/corrected-small-delivery-manifest.json'),
        (FORENSICS/'independent-relationships-summary.json','forensics/independent-relationships-summary.json'),
        (ROOT/'model_storage/git-archive-closure-review/five-extra-file-forensics.json','forensics/model-five-extra-file-forensics.json'),
        (ROOT/'model_storage/git-archive-closure-review/expected-H3-H4-only-review.json','forensics/model-expected-H3-H4-only-review.json'),
        (ROOT/'model_storage/git-archive-closure-review/attempt1/returned-output-transcript.txt','forensics/first-physical-directory-review-failure.txt'),
        (ROOT/'model_storage/git-archive-closure-review/attempt1/specific-stat-and-consumer-order.json','forensics/first-specific-stat-and-consumer-order.json'),
        (ROOT/'model_storage/git-archive-closure-review/attempt1/followup-observation.json','forensics/followup-stability-observation.json'),
        (Path(__file__).resolve(),'stage_explicit_small_evidence.py'),
    ]
    for source,target in additions:
        raw=read_regular(source);plan.append((source,target,len(raw),sha(raw)))
    targets=[p[1] for p in plan];assert len(set(targets))==len(targets)
    assert 'completion.json' in targets and 'H4-full-dependent-consumer.json' in targets
    DEST.mkdir(parents=True,exist_ok=True);assert DEST.resolve(strict=True)==DEST
    copies=[]
    for source,relative,size,digest in plan:
        target=DEST/relative
        assert target.is_relative_to(DEST) and '..' not in Path(relative).parts
        raw=read_regular(source);assert len(raw)==size and sha(raw)==digest
        target.parent.mkdir(parents=True,exist_ok=True);assert target.parent.resolve(strict=True)==target.parent
        if target.exists() or target.is_symlink():
            assert read_regular(target)==raw;action='verified-existing-identical-file'
        else:
            with target.open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
            action='copied-explicit-whitelisted-small-file'
        written=read_regular(target);assert written==raw and sha(written)==digest
        copies.append({'source':str(source),'target':str(target),'target_relative':relative,
                       'bytes':size,'source_sha256':digest,'target_sha256':sha(written),'action':action})
    report={'schema':'explicit-small-unified-evidence-copy-manifest-v1','status':'COPIED_VERIFIED_SMALL_EVIDENCE_PHYSICAL_DIRECTORY_CLOSURE_HOLD',
        'whitelist_source':str(FORENSICS/'corrected-small-delivery-manifest.json'),'whitelist_sha256':sha(whitelist_raw),
        'files':copies,'file_count':len(copies),'total_bytes':sum(x['bytes'] for x in copies),
        'compression_used':False,'recursive_copy_used':False,'unknown_large_files_copied':False,
        'unknown_large_originals_deleted_or_modified':False,'root_README_modified':False,
        'original_consumer_exit_code':0,'original_first_delivery_classification_error_preserved':True,
        'unknown_extra_files':5,'unknown_extra_bytes':1562327640,'creator_identified':False,
        'overall_physical_output_closure':'HOLD_UNKNOWN_OUTPUT_PROVENANCE',
        'scope':'Exact whitelist copy of small original records and derived forensic reports. Archive/member bytes passed the recorded consumer, but the independent physical output census failed. No provenance, native, or missing-capture credit is created.'}
    raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();path=DEST/'copy-manifest.json'
    with path.open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
    for directory in {DEST,*[Path(x['target']).parent for x in copies]}:
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    print(json.dumps({'target':str(DEST),'files':len(copies),'bytes':report['total_bytes'],'manifest_bytes':len(raw),
                      'manifest_sha256':sha(raw),'status':report['status']},sort_keys=True))


if __name__=='__main__':main()
