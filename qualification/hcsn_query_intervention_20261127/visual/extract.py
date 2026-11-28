"""Stream the published NumPy protocol-2 arrays into bounded-memory numeric summaries."""
import argparse
import codecs
import hashlib
import json
from pathlib import Path
import pickle
import struct
import tempfile
from zipfile import ZipFile
import zlib
import numpy as np

class CompressedBytes:
    def __init__(self,folder):
        self.path=Path(tempfile.NamedTemporaryFile(dir=folder,delete=False).name)
    def mapped(self,dtype,shape,order):
        tmp=self.path.with_suffix('.raw')
        if not tmp.exists():
            dec=zlib.decompressobj()
            with self.path.open('rb') as f,tmp.open('wb') as dst:
                while buf:=f.read(131072):dst.write(dec.decompress(buf))
                dst.write(dec.flush())
        expect=int(np.prod(shape,dtype=np.int64))*dtype.itemsize
        if tmp.stat().st_size!=expect:raise ValueError('numeric buffer length mismatch')
        return np.memmap(tmp,dtype=dtype,mode='r',shape=shape,order=order)
class Array:
    def __setstate__(self,state):
        _,self.shape,self.dtype,is_fortran,self.raw=state;self.order='F' if is_fortran else 'C'
    def values(self):
        if self.dtype.hasobject:return np.asarray(self.raw,dtype=object).reshape(self.shape,order=self.order)
        if isinstance(self.raw,CompressedBytes):return self.raw.mapped(self.dtype,self.shape,self.order)
        return np.frombuffer(self.raw,dtype=self.dtype).reshape(self.shape,order=self.order)
def rebuild(*_):return Array()
def latin(value,codec):
    if codec.lower() not in ('latin1','latin-1'):raise ValueError('unexpected string encoding')
    return value if isinstance(value,CompressedBytes) else value.encode('latin1')
def val(x):return x.values() if isinstance(x,Array) else x
class Reader(pickle._Unpickler):
    """Only NumPy numeric array reconstruction and its Latin-1 transport are callable."""
    dispatch=pickle._Unpickler.dispatch.copy()
    def __init__(self,stream,folder):super().__init__(stream);self.folder=folder
    def find_class(self,mod,name):
        allowed={('numpy.core.multiarray','_reconstruct'):rebuild,('numpy','ndarray'):Array,('numpy','dtype'):np.dtype,
             ('_codecs','encode'):latin,('numpy.core.multiarray','scalar'):np._core.multiarray.scalar}
        if (mod,name) not in allowed:raise ValueError('unexpected archived constructor '+mod+'.'+name)
        return allowed[mod,name]
    def unicode_value(self):
        n=struct.unpack('<I',self.read(4))[0]
        if n<524288:self.append(self.read(n).decode('utf8','surrogatepass'));return
        result=CompressedBytes(self.folder);dec=codecs.getincrementaldecoder('utf-8')();comp=zlib.compressobj(1)
        with result.path.open('wb') as out:
            while n:
                b=self.read(min(n,262144));n-=len(b)
                if not b:raise EOFError('truncated archived array')
                out.write(comp.compress(dec.decode(b,final=(n==0)).encode('latin1')))
            out.write(comp.flush())
        self.append(result)
    dispatch[pickle.BINUNICODE[0]]=unicode_value
def string(v):
    arr=np.array(val(v)).ravel()
    if len(arr)!=1:raise ValueError('expected scalar metadata')
    return str(arr[0].decode() if isinstance(arr[0],bytes) else arr[0])
def session(raw,part,index,out):
    key=f'P{part}_S{index:02d}';mouse=string(raw['mouse_name']);date=string(raw['date_exp']);areas=np.array(val(raw['brain_area'])).astype(str).ravel()
    s=val(raw['spks']);cr=np.asarray(val(raw['contrast_right'])).ravel();cl=np.asarray(val(raw['contrast_left'])).ravel();dt=float(np.asarray(val(raw['bin_size'])).ravel()[0])
    meta=dict(key=key,part=part,index=index,mouse=mouse,date=date,n_units=len(areas),n_trials=len(cr),bins=s.shape[-1],dt=dt,areas={n:int((areas==n).sum()) for n in sorted(set(areas))})
    if s.ndim!=3 or s.shape[:2]!=(len(areas),len(cr)) or len(cl)!=len(cr) or abs(dt-.01)>1e-8 or s.shape[-1]<76:raise ValueError(('shape or time basis',meta,s.shape))
    vis=np.flatnonzero(np.char.startswith(areas,'VIS'));sort=lambda i:hashlib.sha256(f'hcsn-visual-8559:{mouse}|{date}|{int(i)}'.encode()).hexdigest()
    vis=sorted(vis,key=sort);th=np.flatnonzero(np.isin(areas,['LP','LGd']));vi=np.flatnonzero(areas=='VISp')
    populations={}
    if len(vis)>=12:populations['cortex']=(vis[::2],vis[1::2])
    if len(th)>=5 and len(vi)>=5:populations['thal']=(th,vi)
    meta['populations']={};anchors=np.arange(50,71,2);h=np.array([2,3,4,6]);stop=77
    for name,(source,destination) in populations.items():
        drive=np.zeros((len(cr),stop),np.uint32);baseline=np.zeros(len(cr),np.uint32)
        positive=np.zeros((len(cr),len(anchors),len(h)),np.uint16)
        for j in range(0,len(source),8):
            z=np.asarray(s[source[j:j+8],:,:stop]);drive+=z.sum(0,dtype=np.uint32)
        for j in range(0,len(destination),8):
            z=np.asarray(s[destination[j:j+8],:,:stop]);baseline+=z[:,:,10:40].sum((0,2),dtype=np.uint32)
            c=np.zeros((*z.shape[:-1],z.shape[-1]+1),dtype=np.int16);c[:,:,1:]=np.cumsum(z>0,axis=-1)
            for k,d in enumerate(h):positive[:,:,k]+=np.sum(c[:,:,anchors+d]>c[:,:,anchors],axis=0,dtype=np.uint16)
        dest=out/f'{key}-{name}.npz';np.savez_compressed(dest,source_count=drive,target_baseline_count=baseline,target_positive=positive,
                   source_unit_ids=np.array(source),target_unit_ids=np.array(destination),left=cl,right=cr,anchors=anchors,horizons=h)
        meta['populations'][name]=dict(source=len(source),target=len(destination),packet=dest.name,sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    (out/f'{key}.json').write_text(json.dumps(meta,indent=1)+'\n')
    for d in raw.values():
        if isinstance(d,Array) and isinstance(d.raw,CompressedBytes):d.raw.path.with_suffix('.raw').unlink(missing_ok=True)
    return meta
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('part',type=int);p.add_argument('out',type=Path);p.add_argument('work',type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);a.work.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.work) as tmp,ZipFile(a.archive) as z,z.open('dat.npy') as stream:
        version=np.lib.format.read_magic(stream)
        if version!=(1,0):raise ValueError('unknown NumPy header')
        shape,order,dtype=np.lib.format.read_array_header_1_0(stream)
        if dtype!=np.dtype(object) or shape!=(13,):raise ValueError('unexpected published outer array')
        data=Reader(stream,tmp).load().values()
        for j,row in enumerate(data):
            m=session(row,a.part,j,a.out);print(m['key'],m['mouse'],m['date'],m['populations'].keys(),flush=True)
