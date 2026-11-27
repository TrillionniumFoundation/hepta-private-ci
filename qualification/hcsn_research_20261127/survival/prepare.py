import datetime, hashlib, io, json, pathlib, time, zipfile
import numpy as np
import pandas as pd
from urllib.request import Request,urlopen
ROOT=pathlib.Path(__file__).resolve().parent
HORIZONS=np.array([1,3,6,12,24])
def raw_power():
    name=ROOT/'power.zip';url='https://archive.ics.uci.edu/static/public/849/power+consumption+of+tetouan+city.zip'
    if not name.is_file():
        with urlopen(Request(url,headers={'User-Agent':'Hepta first crossing research'}),timeout=60) as f:name.write_bytes(f.read())
    with zipfile.ZipFile(name) as z:
        path=next(n for n in z.namelist() if n.lower().endswith('.csv'))
        d=pd.read_csv(z.open(path))
    print('power source',d.shape,d.columns.tolist(),hashlib.sha256(name.read_bytes()).hexdigest(),flush=True)
    d.columns=[' '.join(c.strip().lower().split()) for c in d]
    t=pd.to_datetime(d.iloc[:,0],format='mixed');d.index=t
    src={}
    for split,i,lo,hi in [('train',1,'2017-01-01','2017-07-01'),('val',2,'2017-07-01','2017-10-01'),('test',3,'2017-10-01','2018-01-01')]:
        portion=d[(d.index>=lo)&(d.index<hi)].sort_index()
        assert not portion.index.has_duplicates
        assert np.all(np.diff(portion.index.to_numpy())==np.timedelta64(10,'m'))
        # The CSV order is date, five documented weather/solar features, three demand columns.
        assert len(portion.columns)==9
        values=portion.iloc[:,5+i].to_numpy();weather=portion.iloc[:,1:6].to_numpy()
        rec=[]
        for j,tm in enumerate(portion.index):
            if tm.minute!=0 or tm.hour%6 or j<143 or j+144>=len(values):continue
            lim=1.2*np.mean(values[j-143:j+1]);v=values[j];future=values[j+1:j+145]
            if v>=lim or not np.isfinite(future).all():continue
            hist=values[j-47:j+1].reshape(8,6);met=weather[j-47:j+1].reshape(8,6,5)
            xx=np.column_stack((hist.mean(1)/lim,met.mean(1),1-hist[:,-1]/lim))
            if not np.isfinite(xx).all() or not np.isfinite(lim):continue
            ys=np.array([(future[:h*6]>=lim).any() for h in HORIZONS],dtype=np.float32)
            rec.append((tm.isoformat(),f'zone{i}',xx,(lim-v)/lim,ys))
        src[split]=rec
    return src
def raw_air():
    zfile=ROOT.parent/'feedback/cache/beijing.zip'
    with zipfile.ZipFile(zfile) as outer:sub=outer.read('PRSA2017_Data_20130301-20170228.zip')
    stations={'train':('Aotizhongxin Changping Dingling Dongsi Guanyuan Gucheng','2013-03-01','2015-03-01'),'val':('Huairou Nongzhanguan','2015-03-01','2016-03-01'),'test':('Shunyi Tiantan Wanliu Wanshouxigong','2016-03-01','2017-03-01')}
    src={}
    with zipfile.ZipFile(io.BytesIO(sub)) as z:
        for split,(names,lo,hi) in stations.items():
            src[split]=[]
            for station in names.split():
                member=next(n for n in z.namelist() if n.endswith('.csv') and ('_'+station+'_') in n)
                df=pd.read_csv(z.open(member))
                df.index=pd.to_datetime(df[['year','month','day','hour']]);df=df[(df.index>=lo)&(df.index<hi)].sort_index()
                assert np.all(np.diff(df.index.to_numpy())==np.timedelta64(1,'h'))
                vv=df[['PM2.5','PM10','NO2','TEMP','DEWP','WSPM']].to_numpy()
                for j,tm in enumerate(df.index):
                    if tm.hour%6 or j<7 or j+24>=len(df):continue
                    fr=vv[j-7:j+1];obs=vv[j,0];future=vv[j+1:j+25,0]
                    if not np.isfinite(fr).all() or not np.isfinite(future).all() or obs>=75:continue
                    xx=np.column_stack((fr,1-fr[:,0]/75));yy=np.array([(future[:h]>=75).any() for h in HORIZONS],dtype=np.float32)
                    src[split].append((tm.isoformat(),station,xx,(75-obs)/75,yy))
    return src
def main():
    t=time.perf_counter();meta={}
    for task,source in [('power',raw_power()),('air',raw_air())]:
        meta[task]={}
        train=np.stack([r[2] for r in source['train']])
        mu,sd=train.mean((0,1)),train.std((0,1)).clip(1e-5)
        for s,rows in source.items():
            assert len(rows)>50
            x=np.stack([r[2] for r in rows]);x=np.clip((x-mu)/sd,-6,6).astype('float32')
            y=np.stack([r[4] for r in rows]);dates=[r[0] for r in rows];sites=[r[1] for r in rows]
            week=[name+'/'+str(pd.Timestamp(d).to_period('W-SUN')) for name,d in zip(sites,dates)]
            f=ROOT/f'{task}_{s}.npz';np.savez_compressed(f,x=x,margin=np.array([r[3] for r in rows],np.float32),y=y,time=dates,site=sites,week=week)
            meta[task][s]={'n':len(y),'positives':y.sum(0).astype(int).tolist(),'sites':sorted(set(sites)),'site_weeks':len(set(week)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
    meta['prepare_seconds']=time.perf_counter()-t
    (ROOT/'source.json').write_text(json.dumps(meta,indent=1));print(meta,flush=True)
if __name__=='__main__':main()
