"""Prospective station/year split for UCI Beijing and the original 7149 office window loader."""
import calendar
import csv
import datetime
import hashlib
import io
import zipfile
from pathlib import Path
import numpy as np
import torch
from qualification.hcsn_boundary_transfer_20261126.stream.run import load_data

BEIJING_SHA = "b04da438b2f331ac0ffd45aebdfec0d20d2367feb5f6948c4b1f7ce1191e33c4"
BEIJING_URL = "https://archive.ics.uci.edu/static/public/501/beijing+multi+site+air+quality+data.zip"
FEATURES = ("PM2.5", "PM10", "NO2", "TEMP", "DEWP", "WSPM")
STATIONS = {
  "train": ("Aotizhongxin", "Changping", "Dingling", "Dongsi", "Guanyuan", "Gucheng"),
  "dev": ("Huairou", "Nongzhanguan"),
  "test": ("Shunyi", "Tiantan", "Wanliu", "Wanshouxigong")}
DATES = {"train":("2013-03-01","2015-03-01"),"dev":("2015-03-01","2016-03-01"),
         "test":("2016-03-01","2017-03-01")}

def beijing(root, split):
    path = root/"beijing.zip"
    b = path.read_bytes()
    if hashlib.sha256(b).hexdigest() != BEIJING_SHA:
        raise ValueError("wrong Beijing archive")
    with zipfile.ZipFile(io.BytesIO(b)) as outer:
        inner = outer.read("PRSA2017_Data_20130301-20170228.zip")
    examples = []
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        for station in STATIONS[split]:
            member=f"PRSA_Data_20130301-20170228/PRSA_Data_{station}_20130301-20170228.csv"
            table={}
            date_start,date_end=DATES[split]
            for r in csv.DictReader(io.TextIOWrapper(z.open(member),"utf-8")):
                day=f"{int(r['year']):04}-{int(r['month']):02}-{int(r['day']):02}"
                if not date_start<=day<date_end: continue
                stamp=datetime.datetime.fromisoformat(day)+datetime.timedelta(hours=int(r["hour"]))
                table[stamp]=[float(r[f]) if r[f]!="NA" else np.nan for f in FEATURES]
            # One 8-hour history every calendar day; deterministic independent-of-label thinning.
            months={}
            for start in sorted(t for t in table if t.hour==0):
                h=[table.get(start+datetime.timedelta(hours=k)) for k in range(8)]
                target=table.get(start+datetime.timedelta(hours=13))
                if None in h or target is None or not np.isfinite(h).all() or not np.isfinite(target[0]):
                    continue
                months.setdefault(start.strftime("%Y-%m"),[]).append(
                    (f"{station}/{start.isoformat()}",station,h,int(target[0]>75)))
            for month,group in sorted(months.items()):
                take=np.linspace(0,len(group)-1,min(6,len(group)),dtype=int)
                examples.extend(group[i] for i in take)
    return examples

def load(dataset,root,split):
    if dataset=="office":
        return load_data(root, {"train",split})[split]
    train=beijing(root,"train"); target=train if split=="train" else beijing(root,split)
    fit=np.asarray([r[2] for r in train]); mean=fit.mean(axis=(0,1)); sd=fit.std(axis=(0,1)).clip(1e-6)
    x=((np.asarray([r[2] for r in target])-mean)/sd).clip(-6,6).astype("float32")
    return (torch.from_numpy(x.transpose(1,0,2)),torch.tensor([r[3] for r in target]),
            [r[0] for r in target],[r[1] for r in target])
