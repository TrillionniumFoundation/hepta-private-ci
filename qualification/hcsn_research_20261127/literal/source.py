"""Rebuild the three frozen input panels, without raw location or time features."""
import csv, ctypes as ct, datetime as dt, hashlib, io, json, math, os, sys, time, zipfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def extract_rar(payload):
    lib=ct.CDLL('libarchive.so.13')
    for name,ret,args in [
        ('archive_read_new',ct.c_void_p,[]),('archive_read_support_filter_all',ct.c_int,[ct.c_void_p]),
        ('archive_read_support_format_all',ct.c_int,[ct.c_void_p]),
        ('archive_read_open_memory',ct.c_int,[ct.c_void_p,ct.c_void_p,ct.c_size_t]),
        ('archive_read_next_header',ct.c_int,[ct.c_void_p,ct.POINTER(ct.c_void_p)]),
        ('archive_entry_pathname',ct.c_char_p,[ct.c_void_p]),
        ('archive_read_data',ct.c_ssize_t,[ct.c_void_p,ct.c_void_p,ct.c_size_t]),
        ('archive_read_free',ct.c_int,[ct.c_void_p])]:
        fn=getattr(lib,name);fn.restype=ret;fn.argtypes=args
    ar=lib.archive_read_new()
    try:
        lib.archive_read_support_filter_all(ar);lib.archive_read_support_format_all(ar)
        ba=ct.create_string_buffer(payload)
        assert lib.archive_read_open_memory(ar,ba,len(payload))==0
        ent=ct.c_void_p()
        while True:
            rc=lib.archive_read_next_header(ar,ct.byref(ent))
            if rc==1:break
            if rc:raise ValueError('RAR header '+str(rc))
            name=lib.archive_entry_pathname(ent).decode()
            if not name.lower().endswith('.csv'):continue
            acc=bytearray();buf=ct.create_string_buffer(65536)
            while True:
                size=lib.archive_read_data(ar,buf,len(buf))
                if size==0:break
                if size<0:raise ValueError('RAR data error')
                acc.extend(buf.raw[:size])
            yield name,bytes(acc)
    finally:
        lib.archive_read_free(ar)

def cities(path):
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='3d1e830a3950fe8c92bd8d034644f91b6185280fe315ee4bc8814b88ef7c303b'
    with zipfile.ZipFile(path) as z: members=dict(extract_rar(z.read('FiveCitiePMData.rar')))
    headers={k:next(csv.reader(io.StringIO(v.decode('utf-8-sig')))) for k,v in members.items()}
    print('headers',headers,flush=True)
    humidity_present=all('HUMI' in v for v in headers.values())
    split={'Guangzhou':('train',None,2014),'Chengdu':('train',None,2014),'Shenyang':('val',2014,2015),'Shanghai':('test',2015,2016)}
    collected={k:[] for k in ('train','val','test')}
    for key,content in members.items():
        city=next((c for c in split if c.lower() in key.lower()),None)
        if city is None:continue
        s,lo,hi=split[city]
        by_day={}
        for row in csv.DictReader(io.StringIO(content.decode('utf-8-sig'))):
            year=int(row['year'])
            if (lo and year<lo) or year>=hi:continue
            hour=int(row['hour'])
            if hour not in (*range(8),13):continue
            d=dt.date(year,int(row['month']),int(row['day'])).isoformat()
            try:
                pm=float(row['PM_US Post'])
                if hour==13:
                    by_day.setdefault(d,{})[hour]=pm
                    continue
                t=float(row['TEMP']);dew=float(row['DEWP'])
                humidity=float(row['HUMI']) if humidity_present else 100*math.exp(17.625*(dew/(243.04+dew)-t/(243.04+t)))
                frame=[pm,t,dew,float(row['PRES']),humidity,float(row['Iws'])]
                if np.isfinite(frame).all():by_day.setdefault(d,{})[hour]=frame
            except (TypeError,ValueError):
                continue
        for d,row in sorted(by_day.items()):
            if all(i in row for i in (*range(8),13)) and np.isfinite(row[13]):
                collected[s].append((f'{city}/{d}',city,[row[h] for h in range(8)],int(row[13]>75)))
    out={}
    tr=np.array([r[2] for r in collected['train']],dtype=np.float64)
    mean,sd=tr.mean((0,1)),tr.std((0,1)).clip(1e-6)
    for s,rows in collected.items():
        x=np.array([r[2] for r in rows],dtype=np.float64)
        assert len(x)>90,(s,len(x))
        out[s]=(((x-mean)/sd).clip(-6,6).astype('float32').transpose(1,0,2),np.array([r[3] for r in rows]),np.array([r[0] for r in rows]),np.array([r[1] for r in rows]))
    return out

def main():
    start=time.perf_counter()
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--office',type=Path,required=True);p.add_argument('--beijing',type=Path,required=True)
    a=p.parse_args()
    sys.path.insert(0,str(ROOT.parent/'feedback'))
    from datasets import load
    sources={}
    for task,path in [('office',a.office),('beijing',a.beijing)]:
        rec={}
        for k,s in [('train','train'),('val','dev'),('test','test')]:
            x,y,i,g=load(task,path,s)
            rec[k]=(x.numpy(),y.numpy(),np.array(i,dtype=str),np.array(g,dtype=str))
        sources[task]=rec
    sources['cities']=cities(ROOT/'cities.zip')
    info={}
    for name,data in sources.items():
        info[name]={}
        for split,records in data.items():
            path=ROOT/f'{name}_{split}.npz'
            np.savez_compressed(path,**dict(zip(['x','y','id','group'],records)))
            info[name][split]={'n':len(records[1]),'positive':int(records[1].sum()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    info['prepare_wall_seconds']=time.perf_counter()-start
    (ROOT/'source_receipt.json').write_text(json.dumps(info,indent=2))
if __name__=='__main__':main()
