"""Keep original loss sums and every fitted low-rank/tied recipe in independently verifiable archives."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def pack(w,d,kind):
    d.mkdir(parents=True,exist_ok=True)
    if kind=='recipes':files=sorted((w/'fits').glob('*/*.pt'))
    elif kind=='paired':
        files=list((w/'bp').glob('*'))+[w/'result-joint.json']
    else:
        files=[w/n for n in ('SEAL.json','remote_seal_receipt.json','qualification.json','confirmation_input.npz','fit_only.npz','prepared.json','result-local.json','law4.npz')]
        files+=list((w/'fits').glob('*/*.json'))+list((w/'cold').glob('*'))
    files=[p for p in sorted(files) if p.is_file()];idx={'kind':kind,'files':{},'parts':[]}
    with tempfile.TemporaryDirectory(dir=w) as cache:
        zf=Path(cache)/'payload.zip'
        with zipfile.ZipFile(zf,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as z:
            for f in files:
                name=str(f.relative_to(w));inf=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));inf.compress_type=zipfile.ZIP_DEFLATED
                idx['files'][name]={'bytes':f.stat().st_size,'sha256':digest(f)}
                with f.open('rb') as src,z.open(inf,'w') as dst:
                    for block in iter(lambda:src.read(1024**2),b''):dst.write(block)
        idx['archive_bytes']=zf.stat().st_size;idx['archive_sha256']=digest(zf)
        with zf.open('rb') as src:
            for j,raw in enumerate(iter(lambda:src.read(2*1024**2),b'')):
                name=f'{kind}-{j:03}.bin';(d/name).write_bytes(raw);idx['parts'].append({'file':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    (d/(kind+'_index.json')).write_text(json.dumps(idx,indent=1,sort_keys=True)+'\n')
    print('packed',kind,len(files),idx['archive_bytes'],len(idx['parts']),flush=True)


def restore(d,w,kind):
    idx=json.loads((d/(kind+'_index.json')).read_bytes());w.mkdir(exist_ok=True,parents=True)
    with tempfile.TemporaryDirectory(dir=w) as cache:
        zf=Path(cache)/'received.zip'
        with zf.open('wb') as t:
            for piece in idx['parts']:
                path=d/piece['file'];assert path.stat().st_size==piece['bytes'] and digest(path)==piece['sha256']
                t.write(path.read_bytes())
        assert digest(zf)==idx['archive_sha256'] and zf.stat().st_size==idx['archive_bytes']
        with zipfile.ZipFile(zf) as z:
            assert set(z.namelist())==set(idx['files'])
            for name,record in idx['files'].items():
                f=(w/name).resolve();assert f.is_relative_to(w.resolve());f.parent.mkdir(exist_ok=True,parents=True)
                if not f.exists():
                    with z.open(name) as src,f.open('xb') as dst:
                        for b in iter(lambda:src.read(1024**2),b''):dst.write(b)
                assert f.stat().st_size==record['bytes'] and digest(f)==record['sha256']
    print('decoded',kind,len(idx['files']),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=('pack','restore'));ap.add_argument('source',type=Path);ap.add_argument('destination',type=Path);ap.add_argument('kind',choices=('recipes','evidence','paired'));a=ap.parse_args()
    (pack if a.action=='pack' else restore)(a.source,a.destination,a.kind)
