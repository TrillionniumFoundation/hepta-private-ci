"""Collect compact current commands and measured first-spike labels from Allen NWB."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import h5py
import numpy as np

API='https://api.brain-map.org/api/v2/'
def key(s):return hashlib.sha256(('hcsn-allen-8559-v1:'+str(s)).encode()).hexdigest()
def dump(path,obj):path.write_text(json.dumps(obj,indent=1,allow_nan=False)+'\n')
def data_query(query,cache):
    if not cache.exists():
        url=API+'data/query.json?criteria='+urllib.parse.quote(query)
        with urllib.request.urlopen(url,timeout=45) as r:raw=r.read()
        data=json.loads(raw)
        if not data['success']:raise RuntimeError(data['msg'])
        cache.write_bytes(raw)
    return json.loads(cache.read_bytes())
def roster(work):
    pages=[];rows=[]
    for typ in ('Noise 1','Noise 2'):
        skip=0;total=1;batch=1500
        while skip<total:
            q=("model::EphysSweep,rma::criteria,[stimulus_name$eq'%s'],rma::options[only$eq'id,specimen_id,sweep_number,stimulus_duration,stimulus_start_time,stimulus_name,stimulus_absolute_amplitude'][order$eq'ephys_sweeps.specimen_id,ephys_sweeps.sweep_number,ephys_sweeps.id'][num_rows$eq%d][start_row$eq%d]"%(typ,batch,skip))
            p=work/f'{typ[-1]}-{skip}.json';js=data_query(q,p);total=int(js['total_rows'])
            pages.append(dict(query=q,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),records=len(js['msg'])))
            rows.extend(js['msg']);skip+=batch
    excluded=set(json.loads(Path(__file__).with_name('previous_specimens.json').read_text()))
    grouped=collections.defaultdict(lambda:collections.defaultdict(list))
    for row in rows:
        sid=row['specimen_id']
        if sid in excluded or row['stimulus_duration'] is None or row['stimulus_start_time'] is None:continue
        grouped[sid][row['stimulus_name']].append(row)
    order=sorted((sid for sid,v in grouped.items() if all(len(v[t])>=2 for t in ('Noise 1','Noise 2'))),key=key)
    return grouped,order,pages

def unit(s):return s.decode().lower() if isinstance(s,bytes) else str(s).lower()
def segment(f,row):
    name='Sweep_'+str(row['sweep_number']);v=f['acquisition/timeseries/'+name];i=f['stimulus/presentation/'+name]
    rate=float(v['starting_time'].attrs['rate']);hz=float(i['starting_time'].attrs['rate'])
    if hz!=rate or hz<10000 or abs(i['starting_time'][()]-v['starting_time'][()])>1e-7:raise ValueError('time basis')
    vunit=unit(v['data'].attrs['unit']);iunit=unit(i['data'].attrs['unit'])
    if vunit not in ('volt','volts','v') or iunit not in ('amp','amps','ampere','amperes','a'):raise ValueError('units')
    name_attr=unit(v['aibs_stimulus_name'][()])
    if name_attr.replace(' ','')!=row['stimulus_name'].lower().replace(' ',''):raise ValueError('stimulus identity '+name_attr)
    start=int(round(row['stimulus_start_time']*hz));n=int(np.floor(row['stimulus_duration']*hz+1e-4))
    if start<1 or start+n>min(len(v['data']),len(i['data'])):raise ValueError('documented epoch exceeds data')
    voltage=v['data'][start-1:start+n].astype(float)*float(v['data'].attrs['conversion'])
    current=i['data'][start:start+n].astype(float)*float(i['data'].attrs['conversion'])*1e12
    if not (np.isfinite(voltage).all() and np.isfinite(current).all() and np.ptp(current)>0):raise ValueError('missing or constant current')
    count=round(.002*hz)
    if abs(count-.002*hz)>1e-6:raise ValueError('unsupported sample rate')
    nbin=n//count;used=nbin*count
    spikes=(voltage[:-1]<=0)&(voltage[1:]>0)
    x=current[:used].reshape(nbin,count).mean(1).astype(np.float32);y=spikes[:used].reshape(nbin,count).any(1)
    info=dict(row=row,file_sampling_hz=hz,sweep_start_absolute_s=float(v['starting_time'][()]),
              units={'current':'pA','voltage':'V','output_bin_seconds':.002},
              bin_count=nbin,crossings=int(spikes[:used].sum()),positive_bins=int(y.sum()),file_stimulus_name=name_attr)
    return x,y,info

def acquire(work,target,limit):
    work.mkdir(exist_ok=True,parents=True);target.mkdir(exist_ok=True,parents=True)
    grouped,order,pages=roster(work);dump(target/'metadata_pages.json',pages)
    attempts=[];admitted=[];seen=set()
    for sid in order:
        final=target/f'{sid}.json'
        if final.exists():
            outcome=json.loads(final.read_text());attempts.append(outcome);admitted.append(sid)
        else:
            q=f"model::Specimen,rma::criteria,[id$eq{sid}],rma::include,ephys_result(well_known_files(well_known_file_type))"
            raw=work/(str(sid)+'.nwb.part');outcome={'specimen':sid,'order_sha':key(sid)}
            try:
                sr=data_query(q,work/f'specimen-{sid}.json')['msg'][0]
                candidates=[z for z in sr['ephys_result']['well_known_files'] if z['well_known_file_type']['name']=='NWBDownload']
                if len(candidates)!=1:raise ValueError('NWBDownload multiplicity')
                obj=candidates[0];url='https://api.brain-map.org'+obj['download_link'];outcome['nwb_url']=url;outcome['nwb_id']=obj['id']
                h=hashlib.sha256();t=time.monotonic()
                with urllib.request.urlopen(url,timeout=150) as res,open(raw,'wb') as dst:
                    while chunk:=res.read(1<<20):h.update(chunk);dst.write(chunk)
                outcome.update(nwb_bytes=raw.stat().st_size,nwb_sha256=h.hexdigest(),transfer_s=time.monotonic()-t)
                arrays={};sweeps=[];skips=[]
                with h5py.File(raw) as f:
                    for typ in ['Noise 1','Noise 2']:
                        k=0
                        for row in sorted(grouped[sid][typ],key=lambda z:z['sweep_number']):
                            try:x,y,info=segment(f,row)
                            except (ValueError,KeyError,IndexError) as err:
                                skips.append([row['id'],str(err)]);continue
                            label=typ[-1]+'_'+str(k);arrays['x'+label]=x;arrays['y'+label]=y
                            info['key']=label;sweeps.append(info);k+=1
                            if k==2:break
                        if k<2:raise ValueError('fewer than two qualifying cycles '+typ+' '+str(skips))
                packed=target/f'{sid}.npz';np.savez_compressed(packed,**arrays)
                outcome.update(admitted=True,sweeps=sweeps,skipped_sweeps=skips,npz_sha256=hashlib.sha256(packed.read_bytes()).hexdigest())
                dump(final,outcome);admitted.append(sid)
            except (ValueError,IndexError,KeyError,urllib.error.URLError,OSError,RuntimeError) as err:
                outcome.update(admitted=False,error=str(err))
            finally:
                if raw.exists():raw.unlink()
            attempts.append(outcome)
        dump(target/'roster.json',{'all_candidate_count':len(order),'attempts':attempts,'cells':admitted})
        print(len(admitted),sid,attempts[-1].get('nwb_bytes'),attempts[-1].get('error',''),flush=True)
        if len(admitted)>=limit:break
        if len(attempts)>=120:break
    if len(admitted)<limit:raise RuntimeError('eligible specimen shortage; inspect retained data and acquisition diagnostics')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path,required=True);ap.add_argument('--target',type=Path,required=True);ap.add_argument('--limit',type=int,default=24)
    args=ap.parse_args();acquire(args.work,args.target,args.limit)
