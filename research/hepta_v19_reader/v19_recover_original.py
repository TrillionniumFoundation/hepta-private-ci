"""Recover only SHA-pinned original data/model from one historical GitHub artifact.

No arbitrary TAR extraction, symlink, mutable filename, corpus substitute or
relaxed checksum. Reference-model predictions and publisher targets stay private.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

ARCHIVE_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
ORIGINAL={
 'memory-inputs/locomo.json':('locomo.json',2805274,'79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'),
 'memory-inputs/reader/model.safetensors':('reader/model.safetensors',269060552,'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'),
 'memory-inputs/reader/tokenizer.json':('reader/tokenizer.json',2104556,'9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'),
 'memory-inputs/reader/config.json':('reader/config.json',861,'8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'),
}


def file_sha(path):
    h=sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def extract(archive,output,mode='source-and-reader'):
    if mode not in ('source-and-reader','source-only'):
        raise ValueError('unsupported source set')
    a=Path(archive);out=Path(output)
    if (not a.is_file() or a.is_symlink() or a.stat().st_size>420_000_000 or
        file_sha(a)!=ARCHIVE_SHA or out.exists() or out.is_symlink()):
        raise ValueError('changed original GitHub artifact or existing output')
    want={k:v for k,v in ORIGINAL.items() if mode=='source-and-reader' or k.endswith('locomo.json')}
    out.mkdir(mode=0o700)
    found=set()
    try:
        with zipfile.ZipFile(a) as z:
            if z.namelist()!=['memory-inputs.tar.gz']:
                raise ValueError('wrong original GitHub outer ZIP shape')
            with z.open('memory-inputs.tar.gz') as stream:
                with tarfile.open(fileobj=stream,mode='r|gz') as t:
                    for member in t:
                        if member.name not in want:continue
                        path,size,checksum=want[member.name]
                        if member.name in found or not member.isfile() or member.size!=size:
                            raise ValueError('unsafe or repeated historical tar file')
                        found.add(member.name)
                        target=out/path
                        target.parent.mkdir(parents=True,exist_ok=True)
                        h=sha256();count=0
                        with t.extractfile(member) as reader,target.open('xb') as dest:
                            while True:
                                data=reader.read(1<<20)
                                if not data:break
                                count+=len(data)
                                if count>size:raise ValueError('unbounded extraction')
                                h.update(data);dest.write(data)
                        if count!=size or h.hexdigest()!=checksum:
                            raise ValueError('original publisher/model exact bytes changed')
        if found!=set(want):raise ValueError('original archive missing required file')
    except BaseException:
        shutil.rmtree(out)
        raise
    return {'original_zip_sha256':ARCHIVE_SHA,'original_corpus_sha256':ORIGINAL['memory-inputs/locomo.json'][2],
            'files':len(want),'original_publisher_data_verified_only':True,
            'reference_reader_executed':False,'production_authorized':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--zip',required=True);p.add_argument('--out',required=True)
    p.add_argument('--mode',default='source-and-reader',choices=('source-and-reader','source-only'))
    args=p.parse_args()
    print(json.dumps(extract(args.zip,args.out,args.mode),sort_keys=True))

if __name__=='__main__':main()
