"""Losslessly pack the native board trace and check its fit- and milestone-window integrals."""
import argparse,hashlib,io,json,tarfile
from pathlib import Path
import numpy as np

LAYOUT=np.dtype([('us','<u8'),('mw','<u4')])


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def export(root,dest):
    dest.mkdir(parents=True,exist_ok=True);s=root/'board_observations';raw=s/'native_total_power.bin'
    p=np.memmap(raw,mode='r',dtype=LAYOUT);assert len(p)>1 and raw.stat().st_size==p.size*LAYOUT.itemsize
    dt=np.diff(p['us'].astype(np.int64));dp=np.diff(p['mw'].astype(np.int64));assert dt.min()>0
    time_dtype='<u4' if dt.max()<2**32 else '<u8';assert np.abs(dp).max()<2**31
    target=dest/'board_delta.npz';np.savez_compressed(target,first_us=p['us'][0],first_mw=p['mw'][0],delta_us=dt.astype(time_dtype),delta_mw=dp.astype('<i4'))
    aux=dest/'board_auxiliary.tar.gz'
    with tarfile.open(aux,'w:gz',compresslevel=7) as tar:
        for name in ['board.jsonl','observed_checkpoints.jsonl','native_power_metadata.json','native_power_errors.jsonl']:
            source=s/name
            if source.is_file():
                data=source.read_bytes();info=tarfile.TarInfo(name);info.size=len(data);info.mtime=0;tar.addfile(info,io.BytesIO(data))
    record={'native_total_power_bin_sha256':digest(raw),'native_bytes':raw.stat().st_size,'rows':len(p),'layout':'<QI','board_delta_sha256':digest(target),'board_auxiliary_sha256':digest(aux),'scope':'timestamped aggregate GPU board power samples plus separately observed compute-context counts and fit milestones'}
    (dest/'board_index.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n');return record


def restore(folder):
    data=json.loads((folder/'board_index.json').read_text());file=folder/'board_delta.npz';assert digest(file)==data['board_delta_sha256'] and digest(folder/'board_auxiliary.tar.gz')==data['board_auxiliary_sha256']
    with np.load(file,allow_pickle=False) as z:
        ts=np.r_[int(z['first_us']),int(z['first_us'])+np.cumsum(z['delta_us'],dtype=np.int64)]
        v=np.r_[int(z['first_mw']),int(z['first_mw'])+np.cumsum(z['delta_mw'],dtype=np.int64)]
    p=np.empty(len(ts),dtype=LAYOUT);p['us']=ts;p['mw']=v
    assert len(p)==data['rows'] and p.nbytes==data['native_bytes'] and hashlib.sha256(p.tobytes()).hexdigest()==data['native_total_power_bin_sha256']
    return p


def verify(folder,cost_path):
    data=json.loads(cost_path.read_text());p=restore(folder);t=p['us'].astype(np.float64)/1e6;watts=p['mw'].astype(np.float64)/1000
    assert len(t)==data['sensor']['samples'];highest_seconds=highest_joules=0.;fits=thresholds=0;confirmed={}
    def window(start,end,obs):
        nonlocal highest_seconds,highest_joules
        k=np.searchsorted(t,start);l=np.searchsorted(t,end,side='right');dt=np.diff(t[k:l]);valid=dt<=data['sensor']['max_allowed_gap_seconds'];seconds=dt[valid].sum();w=watts[k:l];joules=(dt[valid]*(w[:-1][valid]+w[1:][valid])/2).sum()
        assert obs['samples']==l-k and obs['large_internal_gaps']==int((~valid).sum());highest_seconds=max(highest_seconds,abs(seconds-obs['covered_seconds']));highest_joules=max(highest_joules,abs(joules-obs['board_joules']))
    for r in data['per_fit']:
        assert len(r['attempts'])==len(r['board_window'])
        for a,reading in zip(r['attempts'],r['board_window']):window(a['start'],a['end'],reading);fits+=1
        if r['phase']=='confirm':confirmed[r['arm'],r['seed']]=r
    for r in data['first_observed_crossings']:
        reading=r.get('startup_inclusive_observed_window')
        if reading is None:continue
        attempts=confirmed[r['arm'],r['seed']]['attempts'];assert len(attempts)==1
        window(attempts[0]['start'],r['checkpoint_file_epoch'],reading);thresholds+=1
    # The online accountant subtracts cumulative sums; the independent check sums each selected window directly.
    assert highest_seconds<1e-5 and highest_joules<1e-3
    return {'energy_windows_from_fit_attempts':fits,'first_observation_energy_windows':thresholds,'native_rows':len(t),'max_seconds_disagreement':highest_seconds,'max_joules_disagreement':highest_joules}


if __name__=='__main__':
    c=argparse.ArgumentParser();m=c.add_subparsers(dest='action',required=True)
    a=m.add_parser('export');a.add_argument('root',type=Path);a.add_argument('dest',type=Path)
    a=m.add_parser('verify');a.add_argument('folder',type=Path);a.add_argument('costs',type=Path);a.add_argument('result',type=Path)
    x=c.parse_args()
    if x.action=='export':print(export(x.root,x.dest))
    else:
        out=verify(x.folder,x.costs);x.result.write_text(json.dumps(out,sort_keys=True,indent=2)+'\n');print(out)
