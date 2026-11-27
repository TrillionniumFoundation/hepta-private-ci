"""Freeze nested 8/32/64 contiguous histories at common anchors, independent of labels."""
import argparse,base64,csv,datetime,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
from collections import defaultdict

OFFICE={"datatest.txt":"1b92c7c1b2838963464fa891a610cf3c5db4becb7189189b29b330107a584c7f","datatraining.txt":"b2c4d0ce2b9e4e453c476f7125ef31aeec2d1f5c7f5572d0e80de3df6521ab56","datatest2.txt":"d026d1bd5aeccd4aff4f3b3710d48e40613bd5fc370db7e61bbdcaa50d985095"}
BJSHA="b04da438b2f331ac0ffd45aebdfec0d20d2367feb5f6948c4b1f7ce1191e33c4"
SITES=[["Aotizhongxin","Changping","Dingling","Dongsi","Guanyuan","Gucheng"],["Huairou","Nongzhanguan"],["Shunyi","Tiantan","Wanliu","Wanshouxigong"]]
DATES=[("2013-03-01","2015-03-01"),("2015-03-01","2016-03-01"),("2016-03-01","2017-03-01")]
FEATURES=("PM2.5","PM10","NO2","TEMP","DEWP","WSPM")
def sha(b):return hashlib.sha256(b).hexdigest()
def select(rows,limit):
    if not rows:raise ValueError("empty source group")
    indices=np.linspace(0,len(rows)-1,min(len(rows),limit),dtype=int)
    return [rows[i] for i in indices]
def office(folder,split):
    groups=defaultdict(list)
    for file,digest in OFFICE.items():
        content=(folder/file).read_bytes();assert sha(content)==digest
        days=defaultdict(list)
        for row in list(csv.reader(io.StringIO(content.decode())))[1:]:
            dt=datetime.datetime.fromisoformat(row[1]);day=dt.date().isoformat()
            flag=0 if day<="2015-02-08" else 1 if day<="2015-02-11" else 2
            if flag==split:days[day].append((dt,[float(x) for x in row[2:7]],int(row[7])))
        for day,rows in days.items():
            for i in range(63,len(rows),64):
                window=rows[i-63:i+1];dts=[60]+[(b[0]-a[0]).total_seconds() for a,b in zip(window,window[1:])]
                if min(dts)<58 or max(dts)>62:continue
                x=[row[1]+[dt-60] for row,dt in zip(window,dts)]
                groups[day].append((window[-1][0].isoformat(),day,x,window[-1][2]))
    return [r for g,rows in sorted(groups.items()) for r in select(rows,12)]
def beijing(folder,split):
    b=(folder/"beijing.zip").read_bytes();assert sha(b)==BJSHA
    with zipfile.ZipFile(io.BytesIO(b)) as outer:inner=outer.read("PRSA2017_Data_20130301-20170228.zip")
    out=[]
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        for site in SITES[split]:
            path=f"PRSA_Data_20130301-20170228/PRSA_Data_{site}_20130301-20170228.csv"
            rows={}
            for r in csv.DictReader(io.TextIOWrapper(z.open(path),"utf-8")):
                day=f"{int(r['year']):04}-{int(r['month']):02}-{int(r['day']):02}"
                if not DATES[split][0]<=day<DATES[split][1]:continue
                dt=datetime.datetime.fromisoformat(day)+datetime.timedelta(hours=int(r['hour']))
                rows[dt]=[float(r[f]) if r[f]!="NA" else np.nan for f in FEATURES]
            per_month=defaultdict(list)
            for anchor in sorted(t for t in rows if t.hour==7):
                seq=[rows.get(anchor-datetime.timedelta(hours=t)) for t in reversed(range(64))]
                label=rows.get(anchor+datetime.timedelta(hours=6))
                if any(q is None for q in seq) or label is None or not np.isfinite(seq).all() or not np.isfinite(label[0]):continue
                per_month[anchor.strftime('%Y-%m')].append((site+'/'+anchor.isoformat(),site,seq,int(label[0]>75)))
            for month,rows in sorted(per_month.items()):out+=select(rows,3)
    return out
def balanced_limit(data,budget):
    groups=defaultdict(list)
    for row in data:groups[row[1]].append(row)
    targets=dict.fromkeys(sorted(groups),0);count=0
    while count<min(len(data),budget):
        for g in targets:
            if targets[g]<len(groups[g]) and count<budget:targets[g]+=1;count+=1
    return [q for g,size in targets.items() for q in select(groups[g],size)]
def build(args):
    report={}
    for ds,func,folder in [("office",office,args.office),("beijing",beijing,args.beijing)]:
        splits=[balanced_limit(func(folder,i),n) for i,n in enumerate([96,32,48])]
        for t in (8,32,64):
            base=np.asarray([q[2][-t:] for q in splits[0]],dtype=np.float64)
            mean=base.mean((0,1));std=base.std((0,1)).clip(1e-6)
            for sect,items in zip(("train","dev","test"),splits):
                raw=np.asarray([q[2][-t:] for q in items],dtype=np.float64)
                xx=((raw-mean)/std).clip(-6,6).astype("float32").transpose(1,0,2)
                file=args.out/f"{ds}-{t}-{sect}.npz"
                np.savez_compressed(file,x=xx,y=np.asarray([q[3] for q in items],dtype=np.int64),ids=np.asarray([q[0] for q in items]),groups=np.asarray([q[1] for q in items]))
                report[file.name]={"sha256":sha(file.read_bytes()),"n":len(items),"groups":sorted({q[1] for q in items})}
    (args.out/"manifest.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    for k in ("office","beijing","out"):ap.add_argument(k,type=Path)
    args=ap.parse_args();args.out.mkdir(exist_ok=True,parents=True);build(args)
