"""Construct prespecified temporal splits and independently defined debit events from UCI 235/374."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

CONTRACTS = np.array([[2.5, 0], [2.5, 1.25], [5, 0], [5, 1.25]], np.float32)


def meter(path, site):
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as file:
        if site == 'fr':
            x = pd.read_csv(file, sep=';', usecols=['Date','Time','Global_active_power'], na_values=['?'])
            times = pd.to_datetime(x.Date+' '+x.Time, format='%d/%m/%Y %H:%M:%S')
            val = x.Global_active_power / 60
            spacing = 1
        else:
            x = pd.read_csv(file, usecols=['date','Appliances','lights'])
            times = pd.to_datetime(x.date, format='%Y-%m-%d %H:%M:%S')
            val = (x.Appliances+x.lights)/1000
            spacing = 10
    assert ((times.dt.minute % spacing == 0) & (times.dt.second == 0)).all()
    data = pd.Series(val.to_numpy(), index=times)
    data = data[~data.index.duplicated(keep=False)].sort_index()
    step = data.resample('30min')
    return step.sum().where(step.count() == 30//spacing)


def split(data, name):
    tick = data.index
    anchor, past, future, tariff, seq = [], [], [], [], []
    val = data.to_numpy()
    for i in range(96, len(data)-5):
        dt = tick[i]
        if dt.minute or dt.hour % 2:
            continue
        block = val[i-96:i+6]
        if not np.isfinite(block).all() or block[:96].mean() <= 0:
            continue
        normalized = block / block[:96].mean()
        history = normalized[72:96]
        hour = tick[i-24:i].hour.to_numpy()+tick[i-24:i].minute.to_numpy()/60
        angle = 2*np.pi*hour/24
        seq.append(np.stack([np.log1p(history),np.sin(angle),np.cos(angle)],-1))
        price = np.where((tick[i:i+6].hour>=17) & (tick[i:i+6].hour<21),1.55,1.)
        anchor.append(dt.to_datetime64().astype('datetime64[m]').astype(np.int64))
        past.append(history);future.append(normalized[-6:]);tariff.append(price)
    past = np.asarray(past,np.float32); future = np.asarray(future,np.float32)
    tariff = np.asarray(tariff,np.float32)
    spend = np.cumsum(future*tariff,-1)[:,None,:] + CONTRACTS[None,:,1,None]*(np.arange(6)>=2)
    y = (spend[:,:,[1,3,5]]>=CONTRACTS[None,:,0,None]).astype(np.float32)
    assert np.all(np.diff(y,axis=2)>=0) and np.all(y[:,1]>=y[:,0]) and np.all(y[:,3]>=y[:,2])
    assert np.all(y[:,2:]<=y[:,:2]) and np.all(y[:,0,0]==y[:,1,0])
    return dict(when=np.array(anchor),past=past,seq=np.asarray(seq,np.float32),future=future,tariff=tariff,y=y)


def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);args=p.parse_args()
    d=args.directory; f=meter(d/'household.zip','fr'); b=meter(d/'appliances.zip','be')
    periods={'train':f.loc[:'2009-06-30'],'dev':f.loc['2009-07-01':'2009-12-31'],'fr':f.loc['2010':'2010'],'be':b}
    report={}
    for name,subset in periods.items():
        result=split(subset,name);np.savez_compressed(d/(name+'.npz'),**result)
        report[name]={'anchors':len(result['when']),'first_minute':int(result['when'][0]),'last_minute':int(result['when'][-1]),'complete_intervals':int(subset.notna().sum())}
    report['sha256']={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted([*d.glob('*.npz'),*d.glob('*.zip')])}
    (d/'split.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
