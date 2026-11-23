"""Certify unchanged RGB frames when the only timestamp inversion precedes one sealed window."""
from fractions import Fraction
import hashlib
from pathlib import Path
import subprocess
from PIL import Image
import torch
from qualification.hcsn_intervention_value.media import vision

SOURCE='cc910783dc8df286e6424b6c957ebf84bdc50aaa5d8eaaa88f02759eac4f0096'
def hash_bytes(b):return hashlib.sha256(b).hexdigest()

def observed(path,seek,length):
    cmd=['ffmpeg','-hide_banner','-nostdin','-v','info','-threads','1','-copyts']
    if seek is not None:cmd+=['-ss',f'{float(seek):.6f}','-t',f'{float(length):.6f}']
    return cmd+['-i',str(path),'-map','0:v:0','-an','-filter_threads','1']

def find_at_endpoints(cmd,ends,lane):
    raw=subprocess.run(cmd+['-vf','showinfo=checksum=0','-fps_mode','passthrough','-f','null','-'],capture_output=True,check=True).stderr
    bases=set(vision._BASE.findall(raw));assert len(bases)==1
    clock=Fraction(*(int(v) for v in next(iter(bases))))
    rows=[tuple(map(int,m)) for m in vision._FRAME.findall(raw)]
    assert rows and all(i==r[0] and r[2]>0 and r[3]>0 for i,r in enumerate(rows))
    pts=[clock*r[1] for r in rows]
    inversions=[(i,rows[i-1][1],r[1]) for i,r in enumerate(rows) if i and pts[i-1]>pts[i]]
    if lane=='short':
        assert not inversions
        assert vision._info(raw)==(clock,rows)
    else:
        assert [(a,b) for _,a,b in inversions]==[(122,121)] and clock*122<Fraction('5.33958')
        try: vision._info(raw)
        except ValueError as error: assert str(error)=='invalid frame sequence'
        else: raise ValueError('expected original rejection')
    chosen=[]
    for end in ends:
        earlier=[i for i,t in enumerate(pts) if t<end]
        assert earlier and earlier==list(range(len(earlier)))
        # The frozen short-duration canonical probe may end on the winning tick.
        # Require an actual following frame in both the uncut movie and extended short probe.
        if lane in ('full','short'): assert len(earlier)<len(pts)
        top=max(pts[i] for i in earlier)
        assert pts[earlier[-1]]==top and sum(pts[i]==top for i in earlier)==1
        chosen.append(earlier[-1])
    if lane=='short':assert chosen==vision.select_indices(pts,ends)
    assert len(set(chosen))==6
    selector='select='+ '+'.join(f'eq(n\\,{i})' for i in chosen)+',format=rgb24,showinfo=checksum=0'
    ext=subprocess.run(cmd+['-vf',selector,'-fps_mode','passthrough','-c:v','rawvideo','-threads:v','1','-f','rawvideo','-'],capture_output=True,check=True)
    check,kept=vision._info(ext.stderr)
    assert check==clock and [r[1:] for r in kept]==[rows[i][1:] for i in chosen]
    chunks=[];offset=0
    for _,_,w,h in kept:
        size=w*h*3;frame=ext.stdout[offset:offset+size];assert len(frame)==size
        chunks.append(frame);offset+=size
    assert offset==len(ext.stdout)
    return dict(decoded_frames=len(rows),clock=str(clock),inversions=inversions,chosen_ordinals=chosen,
                ticks=[r[1] for r in kept],dimensions=[[r[2],r[3]] for r in kept],
                rgb_sha256_by_prefix=[hash_bytes(b) for b in chunks]),chunks

def recover(row,path,transform):
    assert row['query_id']=='fresh-37320740-w01' and vision.digest(path)==SOURCE
    start=Fraction(str(row['start_seconds']));assert start==Fraction('5.33958')
    origin,_=vision.source_meta(path);assert origin==0
    ends=[origin+start+Fraction(12,25)*k for k in range(1,7)]
    audit={};chosen=None
    for name,seek,length in [('full',None,None),('canonical',start-2,Fraction('4.9')),('short',start-Fraction('.2'),Fraction('3.6'))]:
        record,chunks=find_at_endpoints(observed(path,seek,length),ends,name)
        if chosen is None:chosen=chunks
        else: assert chunks==chosen and record['ticks']==audit['full']['ticks']
        audit[name]=record
    features=[]
    for b,dims in zip(chosen,audit['short']['dimensions']):
        with Image.frombytes('RGB',tuple(dims),b) as frame:features.append(transform(frame))
    proof={'source_sha256':SOURCE,'query_id':row['query_id'],'original_error':'invalid frame sequence',
           'original_cutoff_rule':'last presented frame strictly before each endpoint',
           'absolute_endpoint_seconds':[float(v) for v in ends],'independent_reads':audit}
    return torch.stack(features),{'rgb_sha256':hash_bytes(b''.join(chosen)),'details':proof}
