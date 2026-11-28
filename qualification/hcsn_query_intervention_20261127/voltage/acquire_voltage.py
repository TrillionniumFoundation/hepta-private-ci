"""Download a new ranked Allen cohort with pre-anchor membrane-voltage samples."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

import h5py
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'allen'))
from acquire import API, data_query, dump, key, roster, segment


def extract(specimen, rows, work, out):
    receipt=out/f'{specimen}.json'
    if receipt.exists():return json.loads(receipt.read_text())
    record={'specimen':specimen,'order_sha':key(specimen)}
    raw=work/f'{specimen}.nwb.part'
    try:
        q=f'model::Specimen,rma::criteria,[id$eq{specimen}],rma::include,ephys_result(well_known_files(well_known_file_type))'
        item=data_query(q,work/f'specimen-{specimen}.json')['msg'][0]['ephys_result']
        matches=[x for x in item['well_known_files'] if x['well_known_file_type']['name']=='NWBDownload']
        if len(matches)!=1:raise ValueError('NWBDownload multiplicity')
        source=matches[0];url='https://api.brain-map.org'+source['download_link'];start=time.monotonic()
        for attempt in range(3):
            try:
                h=hashlib.sha256()
                with urllib.request.urlopen(url,timeout=150) as stream,raw.open('wb') as target:
                    while chunk:=stream.read(1<<20):h.update(chunk);target.write(chunk)
                break
            except (OSError,urllib.error.URLError):
                if attempt==2:raise
        record.update(nwb_url=url,nwb_id=source['id'],nwb_sha256=h.hexdigest(),nwb_bytes=raw.stat().st_size,transfer_s=time.monotonic()-start)
        arrays={};info=[];skipped=[]
        with h5py.File(raw) as f:
            for name in ('Noise 1','Noise 2'):
                kept=0
                for row in sorted(rows[name],key=lambda r:r['sweep_number']):
                    try:
                        x,y,rec=segment(f,row)
                        data=f['acquisition/timeseries/Sweep_'+str(row['sweep_number'])+'/data']
                        hz=rec['file_sampling_hz'];j=round(hz*row['stimulus_start_time']);step=round(hz*.002)
                        # The preceding source sample is strictly earlier than the anchor, including at t=0.
                        past=data[j-1:j-1+len(x)*step:step].astype(float)*1000
                        if rec['applied_file_conversion']:past*=rec['reported_voltage_conversion']
                        if len(past)!=len(x) or not np.isfinite(past).all():raise ValueError('missing preanchor')
                        k=name[-1]+'_'+str(kept);arrays['x'+k]=x;arrays['v'+k]=past.astype(np.float32);arrays['y'+k]=y
                        rec.update(key=k,voltage_preanchor_lag_seconds=1./hz,voltage_units='mV',voltage_extrema_mv=[float(past.min()),float(past.max())])
                        info.append(rec);kept+=1
                        if kept==2:break
                    except (ValueError,KeyError,IndexError) as err:skipped.append([row['id'],str(err)])
                if kept<2:raise ValueError('insufficient qualifying sweeps '+name)
        packed=out/f'{specimen}.npz';np.savez_compressed(packed,**arrays)
        record.update(admitted=True,sweeps=info,skipped_sweeps=skipped,npz_sha256=hashlib.sha256(packed.read_bytes()).hexdigest())
    except (ValueError,KeyError,IndexError,OSError,urllib.error.URLError,RuntimeError) as err:
        record.update(admitted=False,error=str(err))
    finally:
        if raw.exists():raw.unlink()
    dump(receipt,record)
    return record


if __name__=='__main__':
    cli=argparse.ArgumentParser()
    for flag in ('metadata','work','out'):cli.add_argument('--'+flag,type=Path,required=True)
    a=cli.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.out.mkdir(parents=True,exist_ok=True)
    rows,order,pages=roster(a.metadata);prior=set(json.loads((HERE/'first_cohort.json').read_text()))
    order=[s for s in order if s not in prior];dump(a.out/'metadata_pages.json',pages)
    attempts=[];eligible=[];pos=0
    with ThreadPoolExecutor(max_workers=3) as pool:
        while len(eligible)<24 and pos<120:
            batch=order[pos:pos+min(3,24-len(eligible))];pos+=len(batch)
            jobs=[pool.submit(extract,s,rows[s],a.work,a.out) for s in batch]
            for sid,job in zip(batch,jobs):
                r=job.result();attempts.append(r)
                if r['admitted']:eligible.append(sid)
                print(len(eligible),sid,r.get('nwb_bytes'),r.get('error',''),flush=True)
                dump(a.out/'roster.json',{'candidate_count':len(order),'attempts':attempts,'cells':eligible})
    if len(eligible)!=24:raise RuntimeError('fewer than 24 cells')
