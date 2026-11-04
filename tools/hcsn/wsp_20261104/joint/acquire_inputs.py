"""Recover already-published inputs without copying any live/private model.

Binary-safe git-show from an existing checkout or public HTTPS at an exact
commit. SHA-check every part, the complete archive, all 3550 regular members,
and write only the five original renewal checkpoints and TRAIN/VAL datasets
into a fresh output directory. No pickle/Torch deserialization is used.
"""
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import argparse, gzip, hashlib, io, json, subprocess, tarfile, urllib.request

ROOT=Path(__file__).resolve().parent
REPO='TrillionniumFoundation/hepta-private-ci'
PIN='5b69a046d886cf4c2a73c50e58197360ea15d8f5'
FITS=(11,23,37,53,71)

def sha(b):return hashlib.sha256(b).hexdigest()
def git_blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True)
    ap.add_argument('--repository',help='existing checkout containing the pinned commit')
    ap.add_argument('--archive',help='reuse an existing archive, still fully verified')
    args=ap.parse_args();out=Path(args.output)
    if out.exists():raise FileExistsError('use a new output directory')
    parts=json.loads((ROOT/'PARTS.json').read_text())
    index=json.loads(gzip.decompress((ROOT/'archive_index.json.gz').read_bytes()))
    assert parts['archive_sha256']==index['sha256']
    if args.archive:
        archive=Path(args.archive).read_bytes();mode='existing_verified_archive'
    else:
        def fetch(part):
            if args.repository:
                b=subprocess.check_output(['git','-C',args.repository,'show',PIN+':'+part['path']])
            else:
                url='https://raw.githubusercontent.com/'+REPO+'/'+PIN+'/'+part['path']
                with urllib.request.urlopen(url,timeout=180) as response:b=response.read()
            if len(b)!=part['bytes'] or git_blob(b)!=part['git_blob_sha']:
                raise ValueError('part hash mismatch: '+part['path'])
            return b
        with ThreadPoolExecutor(max_workers=5) as pool:archive=b''.join(pool.map(fetch,parts['parts']))
        mode='git_show' if args.repository else 'public_https'
    if len(archive)!=parts['archive_bytes'] or sha(archive)!=parts['archive_sha256']:
        raise ValueError('archive bytes/hash mismatch')
    expected={m['path']:m for m in index['member_files']}
    selected={f'fit_{fit}/model_renewal/model.json' for fit in FITS}|{f'fit_{fit}/data/fit_{fit}_data.json' for fit in FITS}
    collected={};seen=set()
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        for member in tar:
            if member.isdir():continue
            if not member.isfile():raise ValueError('non-regular member')
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or member.name in seen:
                raise ValueError('unsafe or duplicate archive name')
            if member.name not in expected:raise ValueError('unexpected archive member')
            b=tar.extractfile(member).read();ref=expected[member.name]
            if len(b)!=ref['bytes'] or sha(b)!=ref['sha256']:raise ValueError('member hash mismatch')
            seen.add(member.name)
            if member.name in selected:collected[member.name]=b
    if seen!=set(expected) or set(collected)!=selected:raise ValueError('incomplete archive')
    if len(seen)!=3550:raise ValueError('unexpected manifest count')
    # Verification precedes writing any selected model/data bytes.
    out.mkdir(parents=True,exist_ok=False)
    for name,b in collected.items():
        destination=out.joinpath(*PurePosixPath(name).parts);destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb') as stream:stream.write(b)
    receipt={'schema':'hepta-public-joint-input-acquisition-v1','repository':REPO,'repository_visibility':'public',
             'source_commit':PIN,'acquisition_mode':mode,'archive_sha256':sha(archive),
             'verified_members':len(seen),'published_index_sha256':sha(gzip.decompress((ROOT/'archive_index.json.gz').read_bytes())),
             'selected_files':{name:{'bytes':len(b),'sha256':sha(b)} for name,b in sorted(collected.items())},
             'new_private_heptatrader_data_included':False}
    (out/'INPUT_ACQUISITION_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'verified_members':len(seen),'selected_files':len(collected),'output':str(out)}))

if __name__=='__main__':main()
