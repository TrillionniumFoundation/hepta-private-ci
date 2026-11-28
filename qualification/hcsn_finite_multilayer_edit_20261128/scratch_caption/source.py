"""Prepare actual RGBs and grouped human caption targets from the author Flickr release and COCO 2017."""
import argparse
import hashlib
import io
import json
import re
import time
import urllib.request
import zipfile
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from PIL import Image


FLICKR='https://github.com/jbrownlee/Datasets/releases/download/Flickr8k/'
COCO='https://s3.amazonaws.com/images.cocodataset.org/'
SOURCES={
    'flickr_text':(FLICKR+'Flickr8k_text.zip',2340801),
    'flickr_photos':(FLICKR+'Flickr8k_Dataset.zip',1115419746),
    'coco_annotations':(COCO+'annotations/annotations_trainval2017.zip',None),
    'coco_photos':(COCO+'zips/val2017.zip',None),
}
STOP={'a','an','the','of','on','in','for','and','with','at','to','is'}


def digest(data):return hashlib.sha256(data).hexdigest()


def filehash(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def retrieve(url,start,end):
    sep='&' if '?' in url else '?'
    req=urllib.request.Request(url+sep+f'hepta_caption_range={start}-{end}',headers={'Range':f'bytes={start}-{end}'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req,timeout=90) as rsp:
                rng=rsp.headers['Content-Range'];assert rsp.status==206 and rng.startswith(f'bytes {start}-{end}/')
                block=rsp.read();assert len(block)==end-start+1
                return block,int(rng.rsplit('/',1)[-1])
        except Exception:
            if attempt==4:raise
            time.sleep(2**attempt)


def acquire(root):
    files={};receipts={}
    for key,(url,size) in SOURCES.items():
        tick=time.perf_counter();p=root/(key+'.zip');part=p.with_suffix('.partial')
        if size is None:size=retrieve(url,0,0)[1]
        if not p.exists():
            offset=part.stat().st_size if part.exists() else 0
            assert offset<=size
            with part.open('ab') as w:
                while offset<size:
                    add,total=retrieve(url,offset,min(size,offset+16*1024*1024)-1)
                    assert total==size;w.write(add);offset+=len(add)
            part.replace(p)
        assert p.stat().st_size==size;files[key]=p
        receipts[key]={'url':url,'bytes':size,'sha':filehash(p),'wall':time.perf_counter()-tick}
        print('verified',key,size,flush=True)
    return files,receipts


def normalize(s):return ' '.join(re.findall('[a-z0-9]+',s.lower()))


def resize(source,name,seen_full,seen_small):
    blob=source.read(name);im=Image.open(io.BytesIO(blob)).convert('RGB')
    full=digest(im.width.to_bytes(4,'little')+im.height.to_bytes(4,'little')+im.tobytes())
    pix=np.array(im.resize((32,32),Image.Resampling.BILINEAR))
    small=digest(pix.tobytes())
    if full in seen_full or small in seen_small:return None
    seen_full.add(full);seen_small.add(small)
    return pix,(full,small,digest(blob),source.getinfo(name).CRC)


def main(out):
    out.mkdir(parents=True,exist_ok=True)
    if (out/'data.json').exists():return
    tick=time.perf_counter();clock=time.process_time();archives,receipts=acquire(out)
    seen=set();seen32=set();collected={};duplicates=[]
    with zipfile.ZipFile(archives['flickr_text']) as notes,zipfile.ZipFile(archives['flickr_photos']) as photos:
        caps=defaultdict(list)
        for row in notes.read('Flickr8k.token.txt').decode('utf8').splitlines():
            tok,cap=row.split('\t',1);name,number=tok.rsplit('#',1)
            caps[name].append([int(number),normalize(cap)])
        for split,part in [('train','train'),('dev','dev'),('test','test')]:
            names=sorted(notes.read(f'Flickr_8k.{part}Images.txt').decode().split(),key=lambda n:digest(n.encode()))
            data=[]
            for name in names:
                v=resize(photos,'Flicker8k_Dataset/'+name,seen,seen32)
                if v is None:duplicates.append((split,name));continue
                sentences=sorted(caps[name])[:5]
                assert len(sentences)==5
                data.append((name,v[0],v[1],[c for idx,c in sentences]))
            collected[split]=data
    with zipfile.ZipFile(archives['coco_annotations']) as annotations,zipfile.ZipFile(archives['coco_photos']) as photos:
        records=json.loads(annotations.read('annotations/captions_val2017.json'))
        annotation=json.loads(annotations.read('annotations/instances_val2017.json'))
        category=sorted({word for c in annotation['categories'] for word in normalize(c['name']).split() if word not in STOP})
        caps=defaultdict(list)
        for cap in records['annotations']:caps[cap['image_id']].append([cap['id'],normalize(cap['caption'])])
        images=sorted(records['images'],key=lambda im:digest(str(im['id']).encode()))
        data=[]
        for desc in images:
            name=desc['file_name'];answers=sorted(caps[desc['id']])[:5]
            if len(answers)<5:continue
            v=resize(photos,'val2017/'+name,seen,seen32)
            if v is None:duplicates.append(('coco',name));continue
            data.append((name,v[0],v[1],[c for id,c in answers]))
            if len(data)==768:break
        assert len(data)==768;collected['coco']=data
    freq=Counter(w for _,_,_,caps in collected['train'] for c in caps for w in c.split())
    vocab={w:i+4 for i,(w,n) in enumerate(sorted(freq.items(),key=lambda p:(-p[1],p[0]))[:4092])}
    desc={};manifest=[];V=len(vocab)+4
    for split,data in collected.items():
        pix=np.stack([r[1] for r in data]);names=np.array([r[0] for r in data])
        x=np.zeros((len(data),5,17),'int16');y=np.zeros_like(x)
        for i,(name,_,cert,caps) in enumerate(data):
            manifest.append(dict(split=split,name=name,native_rgb=cert[0],resized=cert[1],jpeg=cert[2],crc=cert[3],captions=caps))
            for j,c in enumerate(caps):
                words=c.split();tokens=[vocab.get(w,1) for w in words[:16]]
                target=tokens+([3] if len(words)<=16 else [])
                prefix=([2]+tokens)[:len(target)];x[i,j,:len(prefix)]=prefix;y[i,j,:len(target)]=target
        px=out/(split+'_pixels.npy');tx=out/(split+'_text.npz');np.save(px,pix);np.savez_compressed(tx,x=x,y=y,names=names)
        desc[split]=dict(images=len(pix),captions=len(pix)*5,nonzero=int(np.count_nonzero(y)),lexical_known=int((y>=4).sum()),
                         oov=int((y==1).sum()),pixels=filehash(px),text=filehash(tx))
    ident=out/'identities.json';ident.write_text(json.dumps(manifest,ensure_ascii=True)+'\n')
    vp=out/'vocabulary.json';vp.write_text(json.dumps(vocab,ensure_ascii=True,sort_keys=True)+'\n')
    info={'archives':receipts,'panels':desc,'duplicate':duplicates,'words':V,'vocab':filehash(vp),'identities':filehash(ident),
          'category_tokens':category,'category_ids':[vocab[w] for w in category if w in vocab],
          'total_wall':time.perf_counter()-tick,'total_cpu':time.process_time()-clock}
    (out/'data.json').write_text(json.dumps(info,indent=1)+'\n')
    print('prepared',V,{k:d['images'] for k,d in desc.items()},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);main(p.parse_args().out)
