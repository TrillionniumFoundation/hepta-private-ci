"""Profile visual routing and full inference after every model choice and cold result is sealed."""
import hashlib,json,random,time
from pathlib import Path
import numpy as np
import torch
from fit import ARMS,CONFIRM,DATA,ROOT,json_file,run_path,sha,write_json
from grouped_router import build_model
from run import device_snapshot


def main():
    assert (ROOT/'final.json').is_file() and (ROOT/'evaluation_seal.json').is_file()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    manifest=json_file(DATA/'manifest.json');raw=manifest['splits']['train']['files']
    for file,h in raw.items():assert sha(DATA/file)==h
    pixels=torch.from_numpy(np.load(DATA/'train_pixels.npy',mmap_mode='r')[:32].copy()).cuda()
    caps=torch.from_numpy(np.load(DATA/'train_tokens.npy',mmap_mode='r')[:32,0,:-1].astype(np.int64)).cuda()
    tuning=json_file(ROOT/'tuning_seal.json');seal=json_file(ROOT/'evaluation_seal.json');seed=CONFIRM[0]
    models={};marks={};bound={};measurements={a:{'router':[],'pixels_to_decoder_input':[],'full_forward':[]} for a in ARMS}
    def project(model):return model.patch(pixels.permute(0,3,1,2).float()/127.5-1).flatten(2).transpose(1,2)+model.image_pos
    def compute(arm,stage):
        m=models[arm]
        if stage=='router':return m.router(marks[arm])
        if stage=='pixels_to_decoder_input':
            visual=m.router(project(m));text=m.embed(caps)+m.text_pos[:,:caps.size(1)]
            return torch.cat([visual,text],1)
        return m(pixels,caps)
    initial=device_snapshot();tick=time.time()
    with torch.inference_mode():
        for arm in ARMS:
            d=run_path('confirm',arm,seed,tuning['rates'][arm]);selected=seal['assignments'][d.name]['assignment']['best'];p=d/selected['name']
            assert sha(p)==selected['state'];bound[arm]=selected['state'];m=build_model(arm,len(manifest['vocab'])).cuda().eval()
            m.load_state_dict(torch.load(p,map_location='cuda',weights_only=True));models[arm]=m;marks[arm]=project(m)
        pairs=[(a,s) for a in ARMS for s in measurements[a]];rng=random.Random(86753091)
        for round_id in range(35):
            rng.shuffle(pairs)
            for arm,stage in pairs:
                torch.cuda.synchronize();before=torch.cuda.Event(enable_timing=True);after=torch.cuda.Event(enable_timing=True)
                before.record();value=compute(arm,stage);after.record();after.synchronize()
                if round_id>=5:measurements[arm][stage].append(float(before.elapsed_time(after)))
                del value
    summary={a:{s:{'median_ms':float(np.median(ms)),'p10_p90_ms':np.quantile(ms,[.1,.9]).tolist()} for s,ms in table.items()} for a,table in measurements.items()}
    write_json(ROOT/'port_profile.json',{'scope':'inference only, original first 32 training photos and first caption, tensors preloaded on GPU, independent measurement after full cold evaluation','seed':seed,'repeats':30,'warmups':5,'clock':'CUDA event elapsed time per operation, GPU synchronized between operations','selected_states':bound,'frozen_result':sha(ROOT/'final.json'),'source':sha(Path(__file__)),'gpu':torch.cuda.get_device_name(0),'torch':str(torch.__version__),'device_snapshots':[initial,device_snapshot()],'start_epoch':tick,'end_epoch':time.time(),'milliseconds':measurements,'summary':summary})
    print('port profile',summary,flush=True)


if __name__=='__main__':main()
