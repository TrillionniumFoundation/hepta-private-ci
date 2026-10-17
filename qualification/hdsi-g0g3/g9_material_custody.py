"""Historical source/model material admission; no model runner receives raw QA gold.

Pinned original GitHub Actions 11586991191 outer ZIP, exact inner files only.
Acquisition uses inherited credential-stripping redirect logic from G5 custody.
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,tarfile,zipfile
from pathlib import Path
from g5_material_custody import ARCHIVE_SHA, download_original
from g9_native_reader import SOURCE_SHA as READER_SHA
from g9_reader_panel import from_original,write_new
from real_minilm_reference import CHECKSUMS

MAX_INNER=300_000_000
MODELS={f'reader/{k}':v for k,v in READER_SHA.items()}
ROOTSHA=CHECKSUMS['locomo.json']


def extract(archive:Path,out:Path,mode:str):
    if mode not in ('source','model','review'):
        raise ValueError('invalid custody mode')
    wanted=({'locomo.json'} | set(MODELS) if mode=='source'
            else {'locomo.json'} if mode=='review' else set(MODELS))
    if out.exists() or out.is_symlink() or archive.is_symlink():
        raise ValueError('refuse overwrite/symlink archive extraction')
    h=hashlib.sha256()
    with archive.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    if h.hexdigest()!=ARCHIVE_SHA:
        raise ValueError('unverified original historical ZIP')
    out.mkdir(parents=True,mode=0o700)
    try:
        with zipfile.ZipFile(archive) as z:
            if z.namelist()!=['memory-inputs.tar.gz']:
                raise ValueError('outer ZIP unregistered layout')
            with z.open('memory-inputs.tar.gz') as reader:
                with tarfile.open(fileobj=reader,mode='r|gz') as tf:
                    seen=set()
                    for mem in tf:
                        if not mem.name.startswith('memory-inputs/'):
                            continue
                        rel=mem.name.removeprefix('memory-inputs/')
                        if rel not in wanted:continue
                        if rel in seen or not mem.isfile() or not 0<mem.size<=MAX_INNER:
                            raise ValueError('unsafe original tar member')
                        seen.add(rel)
                        path=out/rel;path.parent.mkdir(parents=True,exist_ok=True)
                        data=tf.extractfile(mem)
                        if data is None:raise ValueError('unreadable original member')
                        d=hashlib.sha256();total=0
                        with path.open('xb') as dest:
                            for chunk in iter(lambda:data.read(1<<20),b''):
                                total+=len(chunk)
                                if total>mem.size:raise ValueError('archive entry overread')
                                d.update(chunk);dest.write(chunk)
                            dest.flush();os.fsync(dest.fileno())
                        if total!=mem.size or d.hexdigest()!= (ROOTSHA if rel=='locomo.json' else MODELS[rel]):
                            raise ValueError('SHA/length mismatch in original source/weight')
        if seen != wanted:raise ValueError('incomplete original material inventory')
        if mode=='model' and any((out/n).exists() for n in ('locomo.json','gold.json')):
            raise ValueError('model has publisher answer data')
        if mode=='review' and (out/'reader').exists():
            raise ValueError('reviewer has model weights')
    except BaseException:
        shutil.rmtree(out,ignore_errors=True);raise


def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['source','model','review'],required=True)
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--packet',type=Path)
    a=p.parse_args()
    if a.mode=='source' and a.packet is None:
        raise ValueError('source owner needs private packet destination')
    download_original(a.archive);extract(a.archive,a.out,a.mode)
    if a.mode=='source':
        packet=from_original((a.out/'locomo.json').read_bytes())
        write_new(a.packet,packet)
        (a.out/'locomo.json').unlink()
        if (a.out/'locomo.json').exists() or not (a.out/'reader'/'model.safetensors').is_file():
            raise ValueError('unsafe or incomplete model-only stage')
        print(json.dumps({'panel_digest':packet['digest'],'arm_count':64,'gold_answers_exported':False,
                          'disposition':'HOLD_NO_GO'},sort_keys=True))
    else:
        print(json.dumps({'mode':a.mode,'original_outer_sha':ARCHIVE_SHA,'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
