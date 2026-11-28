"""Stream the official 2.6GB ZIP once, verify its MD5 and crop speaker-labeled natural command words."""
import argparse
import csv
import hashlib
import io
import json
import struct
import sys
import time
import zipfile
import zlib
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.io import wavfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data import features
from third_corpus import NAMES
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'caption'))
from prepare_flickr import get,RemoteZip


URL='https://zenodo.org/api/records/3625687/files/'
BYTES=2607605854
MD5='4b3ac37b1a258f55d1eebe657de491a9'
ALIGNS=20091485


def aligned(archive):
    groups=defaultdict(list);reject=[]
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            p=Path(name)
            if not name.startswith('alignments/') or p.suffix!='.align' or p.name.startswith('.'):continue
            entries=[s.split() for s in z.read(name).decode().splitlines()]
            match=[(int(a),int(b),w) for a,b,w in entries if w in NAMES]
            if len(match)!=1:
                reject.append([name,len(match)]);continue
            start,end,label=match[0]
            groups[(p.parent.name,label)].append((name,start,end,label,int(entries[-1][1])))
    kept=[]
    for items in groups.values():
        kept.extend(sorted(items,key=lambda t:hashlib.sha256(t[0].encode()).digest())[:8])
    return kept,reject


def stream(members,decode):
    md5=hashlib.md5();tail=b'';index=0;block=16*1024*1024
    for start in range(0,BYTES,block):
        end=min(BYTES,start+block)
        blob=get(URL+'audio_25k.zip/content',(start,end-1));md5.update(blob)
        span=tail+blob;base=start-len(tail)
        while index<len(members):
            item,key=members[index];at=item.header_offset-base
            assert at>=0
            if at+30>len(span):break
            assert span[at:at+4]==b'PK\x03\x04'
            namesize,extra=struct.unpack_from('<HH',span,at+26)
            body=at+30+namesize+extra
            if body+item.compress_size>len(span):break
            assert span[at+30:at+30+namesize].decode('utf8')==item.filename
            data=span[body:body+item.compress_size]
            if item.compress_type==zipfile.ZIP_DEFLATED:data=zlib.decompress(data,-15)
            else:assert item.compress_type==zipfile.ZIP_STORED
            assert len(data)==item.file_size and (zlib.crc32(data)&0xffffffff)==item.CRC
            decode(key,item,data);index+=1
        tail=span[members[index][0].header_offset-base:] if index<len(members) and members[index][0].header_offset<end else b''
        if start%(block*10)==0:print('archive',end,'members',index,flush=True)
    assert index==len(members) and md5.hexdigest()==MD5


def main(a):
    a.out.mkdir(exist_ok=True,parents=True);record=a.out/'grid.json'
    if record.exists():return
    start=time.perf_counter();c0=time.process_time()
    annotation=a.out/'alignments.zip'
    if not annotation.exists():
        with annotation.open('wb') as f:
            for at in range(0,ALIGNS,4*1024*1024):
                f.write(get(URL+'alignments.zip/content',(at,min(ALIGNS,at+4*1024*1024)-1)))
    assert hashlib.md5(annotation.read_bytes()).hexdigest()=='df892a5adea6595339b331cc065501f9'
    selected,rejected=aligned(annotation)
    seek=RemoteZip(URL+'audio_25k.zip/content',BYTES,2*1024*1024)
    members=[];missing=[]
    with zipfile.ZipFile(seek) as zipper:
        info={z.filename:z for z in zipper.infolist()}
        for row in selected:
            name=row[0].replace('alignments/','audio_25k/').replace('.align','.wav')
            if name not in info:
                missing.append(name);continue
            members.append((info[name],row))
    assert len(members)>2000,(len(members),missing[:5])
    members.sort(key=lambda p:p[0].header_offset)
    observations=[];bad=[]
    def decode(row,info,contents):
        path,a0,b,label,last=row
        hz,x=wavfile.read(io.BytesIO(contents))
        assert x.ndim==1 and int(hz)==25000
        n=len(x);s=round(a0*hz/25000);e=round(b*hz/25000)
        if abs(n-last*hz/25000)>int(.12*hz) or not (0<=s<e<=n):
            bad.append([path,n,last,s,e]);return
        cut=x[s:e]
        h=hashlib.sha256(str((hz,cut.shape,cut.dtype)).encode()+cut.tobytes()).hexdigest()
        observations.append((features(cut,hz),NAMES.index(label),Path(path).parent.name,path,s,e,n,last,h,
                             hashlib.sha256(contents).hexdigest(),info.CRC))
    stream(members,decode)
    known=set()
    for f in a.known:
        with f.open() as txt:
            rows=csv.reader(txt,delimiter='\t');header=next(rows)
            if 'pcm_sha256' in header:col=header.index('pcm_sha256')
            else:col=-1;known.add(header[-1])
            known.update(x[col] for x in rows)
    kept=[];duplicate=[]
    for o in sorted(observations,key=lambda r:r[3]):
        if o[8] in known:duplicate.append([o[3],o[8]]);continue
        known.add(o[8]);kept.append(o)
    x,y,sp,path,starts,ends,n,last,pcm,wav,crc=map(np.asarray,zip(*kept))
    np.savez_compressed(a.out/'GRID.npz',x=x,y=y,speaker=sp,record=path)
    with (a.out/'segments.tsv').open('w') as f:
        tab=csv.writer(f,delimiter='\t',lineterminator='\n');tab.writerow(['source_aligned_path','label','speaker','start_sample',
            'end_sample','wave_length','terminal_tick','pcm_sha256','full_wav_sha256','wav_zip_crc'])
        tab.writerows(zip(path,y,sp,starts,ends,n,last,pcm,wav,crc))
    info=dict(source_record='10.5281/zenodo.3625687',full_zip_md5=MD5,full_bytes=BYTES,alignment_zip_md5='df892a5adea6595339b331cc065501f9',
         selected=len(selected),no_unique_digit=rejected,missing_wav=missing,timing_rejections=bad,duplicate=duplicate,speakers=sorted(set(sp)),
         clips=len(x),labels=np.bincount(y,minlength=10).tolist(),speaker_counts={s:int((sp==s).sum()) for s in sorted(set(sp))},
         duration_ms_quantiles=np.quantile((ends-starts)/25,[0,.05,.5,.95,1]).tolist(),
         terminal_sample_minus_tick=np.quantile(n-last,[0,.5,1]).tolist(),sha=hashlib.sha256((a.out/'GRID.npz').read_bytes()).hexdigest(),
         wall_s=time.perf_counter()-start,cpu_s=time.process_time()-c0)
    record.write_text(json.dumps(info,indent=1)+'\n')
    print('verified',len(x),len(set(sp)),info['labels'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--known',nargs='+',type=Path,required=True)
    main(p.parse_args())
