"""V19 private official-Qwen3 material staging; no model inference or authority.

Publisher Git blob OIDs + LFS object SHA256 are checked before source admission.
No mutable main tag, arbitrary downloaded files, symlinks, or fake weight path.
"""
import argparse
from hashlib import sha1,sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat

REPO = 'Qwen/Qwen3-0.6B'
REVISION = '16706fc57485378d4ffaf54139b29ccc66ae08fa'
SCHEMA = 'hepta.v19.original-locomo-native-qwen3-reference.shadow.v1'

REQUIRED={'config.json','tokenizer_config.json','tokenizer.json','model.safetensors'}
OPTIONAL={'generation_config.json','vocab.json','merges.txt'}
MAX_BYTES=2_500_000_000
HEX40=re.compile(r'[0-9a-f]{40}\Z')
HEX64=re.compile(r'[0-9a-f]{64}\Z')


def digest_file(path):
    h=sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def blob_id(path):
    p=Path(path);s=p.stat().st_size
    h=sha1(b'blob '+str(s).encode()+b'\0')
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def pub_manifest(info):
    if getattr(info,'sha',None)!=REVISION or not isinstance(getattr(info,'siblings',None),(tuple,list)):
        raise ValueError('publisher revision/sibling inventory unavailable')
    entries={}
    for file in info.siblings:
        name=getattr(file,'rfilename',None)
        if name not in REQUIRED|OPTIONAL:continue
        if name in entries or '/' in name or '\\' in name:
            raise ValueError('duplicate or traversing publisher filename')
        size=getattr(file,'size',None);oid=getattr(file,'blob_id',None)
        if (type(size) is not int or not 0<size<=MAX_BYTES or
            type(oid) is not str or not HEX40.fullmatch(oid)):
            raise ValueError('missing immutable publisher size/OID')
        obj=getattr(file,'lfs',None)
        lfs=obj.get('sha256') if type(obj) is dict else getattr(obj,'sha256',None)
        if obj is not None and (type(lfs) is not str or not HEX64.fullmatch(lfs)):
            raise ValueError('publisher LFS SHA missing')
        entries[name]={'bytes':size,'git_blob_oid':oid,'publisher_lfs_sha256':lfs}
    if not REQUIRED.issubset(entries) or entries['model.safetensors']['publisher_lfs_sha256'] is None:
        raise ValueError('required pinned Qwen bytes and publisher weight hash unavailable')
    return entries


def _regular(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
        raise ValueError('untrusted or symlinked source file')
    return p


def safe_cache_path(cache_path, cache_root):
    root=Path(cache_root).resolve(strict=True)
    file=_regular(Path(cache_path).resolve(strict=True))
    if root not in file.parents or file==root:
        raise ValueError('download escaped bounded cache root')
    return file


def copy_verified(src,target,entry):
    src=_regular(src)
    if target.exists() or target.is_symlink():raise FileExistsError('staged publisher file already exists')
    if src.stat().st_size!=entry['bytes']:
        raise ValueError('publisher file byte length mismatch')
    h=sha256()
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):flags|=os.O_NOFOLLOW
    with os.fdopen(os.open(target,flags,0o600),'wb') as out,src.open('rb') as fin:
        n=0
        for block in iter(lambda:fin.read(1024*1024),b''):
            n+=len(block)
            if n>entry['bytes'] or n>MAX_BYTES:raise ValueError('publisher copy size overflow')
            h.update(block);out.write(block)
        out.flush();os.fsync(out.fileno())
    if n!=entry['bytes']:
        raise ValueError('incomplete publisher data')
    sha=h.hexdigest()
    if entry['publisher_lfs_sha256'] is not None:
        if sha!=entry['publisher_lfs_sha256']:raise ValueError('official LFS weight SHA differs')
    elif blob_id(target)!=entry['git_blob_oid']:
        raise ValueError('ordinary Git blob OID differs from official revision')
    return sha


def verify_snapshot(model_dir,spec):
    if (type(spec) is not dict or set(spec)!={'schema','repo','revision','files_sha256','publisher_roster',
             'decoding','authorizes_finaluse','production_authorized'} or
        spec['schema']!=SCHEMA+'.model-source-v1' or spec['repo']!=REPO or
        spec['revision']!=REVISION or spec['decoding']!='native-qwen3-greedy-24-no-thinking' or
        spec['authorizes_finaluse'] is not False or spec['production_authorized'] is not False):
        raise ValueError('model source manifest elevated or unrelated')
    hashes=spec['files_sha256'];roster=spec['publisher_roster']
    if (type(hashes) is not dict or type(roster) is not dict or
        set(hashes)!=set(roster) or not REQUIRED.issubset(hashes) or
        not set(hashes).issubset(REQUIRED|OPTIONAL)):
        raise ValueError('missing/foreign model files')
    root=Path(model_dir)
    if root.is_symlink() or not root.is_dir() or set(p.name for p in root.iterdir())!=set(hashes):
        raise ValueError('model snapshot foreign content or unsupported dir')
    for name,sha in hashes.items():
        if (type(sha) is not str or not HEX64.fullmatch(sha) or type(roster[name]) is not dict or
            set(roster[name])!={'bytes','git_blob_oid','publisher_lfs_sha256'}):
            raise ValueError('invalid source material identity')
        meta=roster[name]
        if (type(meta['bytes']) is not int or not 0<meta['bytes']<=MAX_BYTES or
            type(meta['git_blob_oid']) is not str or not HEX40.fullmatch(meta['git_blob_oid'])):
            raise ValueError('unverified publisher byte/OID')
        path=_regular(root/name)
        if path.stat().st_size!=meta['bytes'] or digest_file(path)!=sha:
            raise ValueError('source bytes not equal to sealed model')
        if meta['publisher_lfs_sha256'] is None:
            if blob_id(path)!=meta['git_blob_oid']:raise ValueError('not publisher Git object')
        elif sha!=meta['publisher_lfs_sha256']:
            raise ValueError('not publisher LFS SHA object')
    import source_first as v17
    return v17.digest(spec)


def stage(info_fn,download_fn,cache_dir,model_dir,spec_file):
    pub=pub_manifest(info_fn())
    cache=Path(cache_dir);out=Path(model_dir);ms=Path(spec_file)
    if (not cache.is_dir() or cache.is_symlink() or out.exists() or out.is_symlink() or
        ms.exists() or ms.is_symlink() or not out.parent.is_dir() or not ms.parent.is_dir()):
        raise ValueError('private stage is not empty / cache invalid')
    out.mkdir(mode=0o700)
    try:
        sha={}
        for name in sorted(pub):
            actual=safe_cache_path(download_fn(name),cache)
            sha[name]=copy_verified(actual,out/name,pub[name])
        spec={'schema':SCHEMA+'.model-source-v1','repo':REPO,'revision':REVISION,
              'files_sha256':sha,'publisher_roster':pub,
              'decoding':'native-qwen3-greedy-24-no-thinking',
              'authorizes_finaluse':False,'production_authorized':False}
        verify_snapshot(out,spec)
        import source_first as v17
        v17.write_once(ms,spec)
        return {'model_material_sha256':v17.digest(spec),'model_files':len(sha),
                'production_authorized':False}
    except BaseException:
        shutil.rmtree(out)
        raise


def main():
    p=argparse.ArgumentParser()
    for a in ('cache','model-dir','manifest'):
        p.add_argument('--'+a,required=True)
    args=p.parse_args()
    from huggingface_hub import HfApi,hf_hub_download
    cache=Path(args.cache);cache.mkdir(parents=True,exist_ok=False,mode=0o700)
    api=HfApi()
    result=stage(lambda:api.model_info(REPO,revision=REVISION,files_metadata=True),
                 lambda name:hf_hub_download(REPO,filename=name,revision=REVISION,
                                             cache_dir=str(cache),token=False),
                 cache,args.model_dir,args.manifest)
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
