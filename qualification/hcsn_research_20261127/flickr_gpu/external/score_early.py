"""Evaluate sealed, early Flickr8k captioners on independently sourced paired COCO captions."""
from pathlib import Path
import os, json, time, hashlib, sys, resource, fcntl
os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'prepare_packages'))
import numpy as np
import torch
from PIL import Image,ImageOps
from model import Captioner
from panel import score,Samples
from prepare import words
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
OUT=ROOT/'caption_external20'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,obj):
    t=p.with_suffix(p.suffix+'.part')
    t.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False))
    t.replace(p)
def difference_hash(image):
    a=np.asarray(image.convert('L').resize((9,8),Image.Resampling.BILINEAR),dtype=np.uint8)
    return np.packbits((a[:,1:]>a[:,:-1]).ravel())
def main():
    lock=(OUT/'eval.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    end=time.monotonic()+7000
    while not (ROOT/'coco_restored/verification.json').exists() or not (OUT/'seal.json').exists():
        if time.monotonic()>end:raise RuntimeError('Source or checkpoint seal unavailable within two hours')
        time.sleep(10)
    start=time.monotonic()
    if (OUT/'summary.json').exists():
        raise RuntimeError('Completed results already exist')
    seal=json.loads((OUT/'seal.json').read_text());assert len(seal['states'])==15
    assert sha(OUT/'PROTOCOL.txt')==seal['protocol'] and sha(ROOT/'data/manifest.json')==seal['flickr_manifest']
    src=json.loads((ROOT/'coco_source_receipt.json').read_text())
    identity={name:h for name,h,_ in src['jpeg']}
    roster=json.loads((ROOT/'coco_restored/selected.json').read_text())['test']
    assert len(roster)==384
    assert hashlib.sha256('\n'.join(z['file'] for z in roster).encode()).hexdigest()==src['ordered_splits']['test']
    m=json.loads((ROOT/'data/manifest.json').read_text())
    vocab={w:i for i,w in enumerate(m['vocab'])};assert len(vocab)==3490
    known={};dh=[];nearids=[]
    for split,rec in m['splits'].items():
        for key in ('pixels','ids'):
            filename=split+'_'+key+'.npy';assert sha(ROOT/'data'/filename)==rec['files'][filename]
        px=np.load(ROOT/'data'/(split+'_pixels.npy'),mmap_mode='r')
        ids=np.load(ROOT/'data'/(split+'_ids.npy'),mmap_mode='r')
        for image_no,img in enumerate(px):
            image_id=bytes(ids[image_no]).decode()
            known[image_id]=split
            dh.append(difference_hash(Image.fromarray(img)));nearids.append((split,image_id))
    assert len(known)==7999
    dh=np.stack(dh);bits=np.unpackbits(np.arange(256,dtype=np.uint8)[:,None],axis=1).sum(1).astype(np.uint8)
    pics=[];tokens=[];included=[];excluded=[];all_lex=all_unk=all_trunc=0
    for row in roster:
        file=row['file'];p=ROOT/'coco_restored/images'/file;h=sha(p);assert h==identity[file]
        with Image.open(p) as image:
            img=ImageOps.fit(image.convert('RGB'),(64,64),method=Image.Resampling.BILINEAR)
            pixels=np.asarray(img,dtype=np.uint8).copy()
            d=bits[np.bitwise_xor(dh,difference_hash(img))].sum(1)
        closest=int(d.argmin());dist=int(d[closest])
        if h in known or dist<=2:
            excluded.append(dict(file=file,sha256=h,exact_split=known.get(h),minimum_hamming=dist,nearest_flickr_split=nearids[closest][0],nearest_flickr_sha256=nearids[closest][1]));continue
        assert len(row['captions'])==5
        enc=np.zeros((5,32),dtype=np.int16)
        for j,caption in enumerate(row['captions']):
            w=words(caption);all_trunc+=int(len(w)>30)
            ids=[vocab.get(x,3) for x in w[:30]]
            all_lex+=len(ids);all_unk+=ids.count(3)
            seq=[1]+ids+[2];enc[j,:len(seq)]=seq
        pics.append(pixels);tokens.append(enc);included.append(dict(file=file,sha256=h,minimum_hamming=dist))
    data=Samples.__new__(Samples);data.pix=np.stack(pics);data.cap=np.stack(tokens)
    subset=np.arange(len(pics));device=torch.device('cpu')
    write(OUT/'cohort.json',dict(included=included,excluded=excluded,known_flickr_images=len(known),unknown=all_unk,lexical_targets=all_lex,truncated=all_trunc,source=sha(ROOT/'coco_source_receipt.json'),manifest=seal['flickr_manifest'],token_rows_sha256=hashlib.sha256(data.cap.tobytes()).hexdigest(),pixel_rows_sha256=hashlib.sha256(data.pix.tobytes()).hexdigest()))
    totals={};shifts={};costs={};c0=None
    for key,entry in sorted(seal['states'].items()):
        arm,seed=key.rsplit('-',1);p=OUT/key/'selected.pt';assert sha(p)==entry['selected'];assert sha(OUT/key/'fit.json')==entry['fit']
        tic=time.monotonic();model=Captioner(arm,len(vocab))
        model.load_state_dict(torch.load(p,map_location='cpu',weights_only=True))
        l,c=score(model,data,subset,device);s,c2=score(model,data,subset,device,swap=True)
        assert np.array_equal(c,c2) and (c0 is None or np.array_equal(c,c0))
        c0=c;costs[key]=time.monotonic()-tic
        np.savez_compressed(OUT/key/'external_coco.npz',paired=l,shifted=s,tokens=c)
        totals.setdefault(arm,[]).append(l);shifts.setdefault(arm,[]).append(s)
        print(key,float(l.sum()/c.sum()),float((s-l).sum()/c.sum()),flush=True)
    assert int(c0.sum())==all_lex+5*len(pics)
    arms=['hcsn','smooth','lif','mean','dense'];rng=np.random.default_rng(230501)
    sample=rng.integers(len(pics),size=(4000,len(pics)));denom=c0[sample].sum(1)
    p={arm:np.stack(totals[arm]).mean(0) for arm in arms}
    sv={arm:np.stack(shifts[arm]).mean(0) for arm in arms}
    report={}
    for arm in arms:
        gap=sv[arm]-p[arm];compar=p['hcsn']-p[arm]
        def interval(d):return np.quantile(d[sample].sum(1)/denom,[.025,.975]).tolist()
        report[arm]=dict(ood_nll=float(p[arm].sum()/c0.sum()),paired_nll_95=interval(p[arm]),shift_penalty=float(gap.sum()/c0.sum()),shift_penalty_95=interval(gap),hcsn_minus_comparator_nll=float(compar.sum()/c0.sum()),hcsn_minus_comparator_nll_95=interval(compar),per_seed_nll=[float(a.sum()/c0.sum()) for a in totals[arm]],per_seed_shift_penalty=[float((a-b).sum()/c0.sum()) for a,b in zip(shifts[arm],totals[arm])])
    write(OUT/'summary.json',dict(arms=report,images=len(pics),captions=5*len(pics),scored_tokens=int(c0.sum()),excluded=excluded,unknown_fraction_lexical=all_unk/all_lex,unknown_fraction_all_targets=all_unk/int(c0.sum()),truncated_captions=all_trunc,bootstrap='4000 fixed gallery paired image clusters, seed means first, conditional on 3 fixed model seeds',cost_seconds_evaluation=costs,whole_wall_seconds=time.monotonic()-start,process_cpu_seconds=time.process_time(),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,device='ai395 single CPU thread',torch=str(torch.__version__),model_source={k:sha(ROOT/k) for k in ['model.py','parent_cell.py','prepare.py','panel.py']},eval_source=sha(Path(__file__)),checkpoint_seal=sha(OUT/'seal.json'),cohort=sha(OUT/'cohort.json'),raw={key:sha(OUT/key/'external_coco.npz') for key in seal['states']}))
if __name__=='__main__':main()
