"""Acquire public measured metadata. Missing spike counts stay missing."""
import concurrent.futures,hashlib,json,time,urllib.parse,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent;cache=root/'cache';cache.mkdir(exist_ok=True)
size=1500
stem="model::EphysSweep,rma::criteria,[stimulus_name$eq'Long Square'],rma::options[order$eq'ephys_sweeps.specimen_id,ephys_sweeps.sweep_number,ephys_sweeps.id'][only$eq'id,specimen_id,sweep_number,stimulus_absolute_amplitude,stimulus_duration,num_spikes,stimulus_units'][num_rows$eq%d][start_row$eq%d]"
def page(pos):
 p=cache/f'sweeps-{pos}.json'
 if p.exists():return
 url='https://api.brain-map.org/api/v2/data/query.json?'+urllib.parse.urlencode({'criteria':stem%(size,pos)})
 for i in range(4):
    try:
      b=urllib.request.urlopen(url,timeout=40).read();v=json.loads(b)
      if not v.get('success') or v['start_row']!=pos:raise ValueError(str(v)[:220])
      tmp=p.with_suffix('.tmp');tmp.write_bytes(b);tmp.replace(p);return
    except Exception:
      if i>=3:raise
      time.sleep(2**i)
page(0);total=json.loads((cache/'sweeps-0.json').read_bytes())['total_rows']
with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(page,range(size,total,size)))
allrows={};sources={}
for idx in range(0,total,size):
 p=cache/f'sweeps-{idx}.json';b=p.read_bytes();sources[p.name]=hashlib.sha256(b).hexdigest()
 for r in json.loads(b)['msg']:
    if r['id'] in allrows:raise ValueError('page nonunique')
    allrows[r['id']]=r
assert len(allrows)==total
meta={'total':total,'query_template':stem,'page_size':size,'page_sha256':sources,'collected_epoch':time.time()}
(root/'source.json').write_text(json.dumps(meta,sort_keys=True,indent=1)+'\n')
print('published sweep rows',len(allrows),'cells',len({r['specimen_id'] for r in allrows.values()}),'nonmissing explicit zeros',sum(r['num_spikes']==0 for r in allrows.values()),flush=True)
