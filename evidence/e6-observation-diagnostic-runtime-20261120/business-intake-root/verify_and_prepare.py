from pathlib import Path, PurePosixPath
import hashlib, json, tarfile

ROOT=Path('/workspace/scratch/e9e051ab0825')
OUT=Path(__file__).resolve().parent
PACK=ROOT/'e6_training_business_archive_1/pack-1'
FINAL=ROOT/'e6_noupdate12_finaluse_attribution_review_1'
REPORT=ROOT/'metrics_integration/execution-readout-intake-diagnostic-4/build2'
def sha(b): return hashlib.sha256(b).hexdigest()
def oid(b): return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def readj(p): return json.loads(p.read_bytes())
def row(path, name):
    b=path.read_bytes()
    return dict(path=name,local_path=str(path),bytes=len(b),sha256=sha(b),git_blob=oid(b),mode='100644')
def check(r):
    p=Path(r['local_path']); assert p.is_file() and not p.is_symlink()
    b=p.read_bytes(); assert len(b)==r['bytes'] and sha(b)==r['sha256'] and oid(b)==r['git_blob']
    assert len(b)<=480000
    return b
def main():
    result=readj(PACK/'RESULT.json'); assert result['successful'] and result['original_whole_parent']=='FAIL'
    plan=readj(PACK/'PLAN.json'); assert sha((PACK/'PLAN.json').read_bytes())=='dc082e3ba4ca8b6635015fc49ab8b997173accecb6993a8772105b3e936c2b35'
    expected={r['member']:r for r in plan['inputs']}; assert len(expected)==69
    arc=(PACK/'training-business-data.tar.xz').read_bytes()
    assert len(arc)==result['archive_bytes']==117228 and sha(arc)==result['archive_sha256']=='43f77c1d8a2f6edc41b391e54e5c21ec8d785667328ff66ff0fa31fc055567ef'
    seen=set(); total=0
    with tarfile.open(PACK/'training-business-data.tar.xz','r:xz') as tar:
        for m in tar:
            n=PurePosixPath(m.name); assert m.isfile() and not n.is_absolute() and '..' not in n.parts and m.name not in seen
            r=expected[m.name]; b=tar.extractfile(m).read(); original=Path(r['source_path']).read_bytes()
            assert b==original and len(b)==r['bytes']==m.size and sha(b)==r['sha256'] and oid(b)==r['git_blob']
            seen.add(m.name);total+=len(b)
    assert seen==set(expected) and total==1536982
    parts=readj(PACK/'archive-parts.json'); assembled=b''
    for r in parts['parts']:
        b=(PACK/r['file']).read_bytes(); assert r['offset']==len(assembled) and len(b)==r['bytes']<=480000 and sha(b)==r['sha256'] and oid(b)==r['git_blob'];assembled+=b
    assert assembled==arc
    pub=readj(PACK/'PUBLICATION_FILES.json'); assert len(pub)==13
    for r in pub:check(r)
    storage=readj(PACK/'PUBLICATION_MAP_STORAGE.json');assert check(storage['map'])==(PACK/'PUBLICATION_FILES.json').read_bytes()
    prefix='evidence/e6-observation-diagnostic-runtime-20261120/training-business-data/'
    pub.extend([storage['map'],row(PACK/'PUBLICATION_MAP_STORAGE.json',prefix+'PUBLICATION_MAP_STORAGE.json')]);assert len(pub)==15
    refs=readj(REPORT/'PUBLICATION_FILES.json');assert len(refs)==33
    for r in refs:check(r)
    pub+=refs
    manifest=readj(FINAL/'MANIFEST.json');assert len(manifest['files'])==16 and sha((FINAL/'MANIFEST.json').read_bytes())=='35a1ff6edfd3fe6e70e3cd333b3da012f706fa809b05dc7378c9a05419480315'
    finalprefix='evidence/e6-observation-diagnostic-runtime-20261120/finaluse-attribution-data/'
    for r in manifest['files']:
        rr=row(Path(r['local_path']),finalprefix+r['path']);assert all(rr[k]==r[k] for k in ('bytes','sha256','git_blob'));check(rr);pub.append(rr)
    for name in ['MANIFEST.json','ROOT_READBACK.json']:pub.append(row(FINAL/name,finalprefix+name))
    assert len(pub)==66
    frozen=readj(ROOT/'metrics_integration/final_evidence_publication_work/FROZEN_409_FILES.json');old={r['path'] for r in frozen};assert len(old)==409
    report=dict(status='ROOT_INDEPENDENT_ALL_MEMBER_AND_PUBLICATION_PASS',training_review_members=68,archive_members=69,archive_input_bytes=total,archive_sha256=sha(arc),training_archive_parts=1,training_archive_publication_files=15,report_immutable_references=33,finaluse_data_files=18,all_archive_members_literal_equal_originals=True,all_publication_bytes_SHA_GitOID_verified=True,old_409_unchanged=True,original_NoUpdate12='FAIL',FinalUse_or_Adopt_or_cold_qualification=False,new_host_native_model_database_or_Git_actions=0,publication_file_count_with_this_readback_and_verifier=68)
    q=OUT/'ROOT_READBACK.json';assert not q.exists();q.write_text(json.dumps(report,indent=2)+'\n')
    rootprefix='evidence/e6-observation-diagnostic-runtime-20261120/business-intake-root/'
    pub.extend([row(q,rootprefix+q.name),row(Path(__file__).resolve(),rootprefix+Path(__file__).name)])
    assert len(pub)==68 and len({r['path'] for r in pub})==68 and not ({r['path'] for r in pub}&old)
    for r in pub:check(r)
    q=OUT/'PUBLICATION_FILES_68.json';assert not q.exists();q.write_text(json.dumps(sorted(pub,key=lambda r:r['path']),indent=2)+'\n')
    print(json.dumps({'status':'PASS','members':69,'publication_files':len(pub),'bytes':sum(r['bytes'] for r in pub),'manifest_sha256':sha(q.read_bytes())}))
if __name__=='__main__':main()
