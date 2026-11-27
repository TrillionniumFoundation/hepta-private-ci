from pathlib import Path
import time,json,shutil,hashlib,os,fcntl
r=Path('/tmp/hepta-hcsn-flickr8k-c511-9c415'); source=r/'panel_gpu';target=r/'caption_external20';target.mkdir(exist_ok=True)
arms=('hcsn','smooth','lif','mean','dense'); seeds=(17011,24203,39827)
def h(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
q=target/'PROTOCOL.txt'
message="""Freeze every 20-second GPU checkpoint that still has an authentic single 20-second model-selection measurement and single matching file identity. Evaluate these 15 from-random Flickr8k trained captioners on COCO's 384 previously studied test photographs/captions, a different caption objective. Do not query the registered Flickr validation or test outcomes. Work only if all 15 frozen selected states can be recovered. Select no candidates using COCO; evaluate every arm and seed. Exclude COCO photos with JPEG hashes in any Flickr split or luminance 9x8 dHash Hamming distance <=2 from any 64x64 Flickr image. Apply 64x64 bilinear RGB centre crop and the exact Flickr training vocabulary, truncation and BOS/EOS rules. Per-token NLL and the NLL increase when the image shifts by one surviving position; include unknown target and EOS, exclude PAD. Use paired bootstrap of surviving COCO photos, 4000 draws, averaging seeds first and recomputing token denominators. Report all exclusions, overlap caveats, coverage and fixed-gallery interval. This is external early-checkpoint transfer, not the 42-minute primary outcome. Freeze before opening COCO caption scores. Whole CPU evaluation timings are separate from shared GPU training."""
if q.exists():assert q.read_text()==message
else:q.write_text(message)
deadline=time.monotonic()+450
ledger={}
while time.monotonic()<deadline:
 for arm in arms:
  for seed in seeds:
   n=f'{arm}-{seed}'
   if n in ledger:continue
   d=source/n;f=d/'fit.json';w=d/'selected.pt'
   if not f.exists() or not w.exists():continue
   before=f.read_bytes(); z=json.loads(before)
   if len(z['checkpoints'])!=1 or z['checkpoints'][0]['nominal_s']!=20:
    print('missing exact 20s',n,flush=True);raise SystemExit(2)
   sub=target/n;sub.mkdir(exist_ok=True)
   tmp=sub/'selected.tmp';shutil.copyfile(w,tmp)
   if f.read_bytes()!=before or h(w)!=h(tmp):continue
   tmp.replace(sub/'selected.pt');(sub/'fit.json').write_bytes(before)
   ledger[n]={'selected':h(sub/'selected.pt'),'fit':h(sub/'fit.json'),'steps':z['steps'],'dev_nll':z['best_nll']}
 if len(ledger)==15:break
 time.sleep(3)
assert len(ledger)==15,len(ledger)
(target/'seal.json').write_text(json.dumps({'states':ledger,'protocol':h(q),'flickr_manifest':h(r/'data/manifest.json'),'sealed_epoch':time.time()},sort_keys=True))
print('sealed 15 GPU 20-second states',flush=True)
