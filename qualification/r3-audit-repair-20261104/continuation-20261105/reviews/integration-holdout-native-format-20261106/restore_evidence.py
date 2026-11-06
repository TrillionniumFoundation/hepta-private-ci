"""Restore retained evidence and replay its independent checker, with no product tools."""
import argparse
import base64
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

def identity(b):
    return {'bytes':len(b),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),
            'sha256':hashlib.sha256(b).hexdigest()}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();root=a.root.resolve();out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    m=json.loads((root/'archive-manifest.json').read_bytes())
    encoded=[]
    for part in m['parts']:
        b=(root/part['path']).read_bytes()
        assert identity(b)=={k:part[k] for k in ['bytes','git_blob','sha256']}
        assert b.endswith(b'\n') and b.count(b'\n')==1
        encoded.append(b[:-1])
    packed=base64.b64decode(b''.join(encoded),validate=True)
    assert identity(packed)==m['archive']
    original=lzma.decompress(packed)
    assert identity(original)==m['tar']
    seen=set()
    with tarfile.open(fileobj=io.BytesIO(original),mode='r:') as archive:
        for member in archive:
            path=PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            assert member.name==str(path) and '\\' not in member.name and member.name not in seen
            seen.add(member.name)
            b=archive.extractfile(member).read()
            assert identity(b)==m['members'][member.name]
            p=out/'restored'/member.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
    assert seen==set(m['members']) and len(seen)==m['member_count']
    result=subprocess.run([sys.executable,str(out/'restored/independent/verify_candidate.py'),str(out/'restored/author/candidate')],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    (out/'independent.stdout.json').write_bytes(result.stdout)
    (out/'independent.stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0 and not result.stderr
    assert result.stdout==(out/'restored/independent/replay-01.stdout.json').read_bytes()
    proof={'schema':'holdout-fmt-evidence-portable-restoration-v1','archive':m['archive'],'members':len(seen),
           'all_member_hashes_and_bytes_equal':True,'independent_replay_exit':result.returncode,
           'independent_stdout':identity(result.stdout),'independent_stderr':identity(result.stderr),
           'independent_stdout_entire_bytes_equal':True,
           'scope':'Read retained bytes and local Git-only independent checker; no Rust/rustfmt/product/native/network/ref operation.'}
    (out/'RESTORATION.json').write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True,indent=2))

if __name__=='__main__':main()
