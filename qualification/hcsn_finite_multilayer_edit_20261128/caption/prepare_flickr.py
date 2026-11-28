"""Acquire actual Flickr8k source archives and materialize the preregistered, disjoint image/word panels."""
import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import time
import urllib.request
import zipfile
from collections import Counter, OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image


RELEASE = 'https://github.com/jbrownlee/Datasets/releases/download/Flickr8k/'
PHOTO = RELEASE + 'Flickr8k_Dataset.zip'
CAPTIONS = RELEASE + 'Flickr8k_text.zip'


def digest(x):
    return hashlib.sha256(x).hexdigest()


def get(url, bounds=None):
    headers = {} if bounds is None else {'Range': f'bytes={bounds[0]}-{bounds[1]}'}
    for attempt in range(5):
        try:
            # Distinct query strings prevent proxies from reusing a range response for a different offset.
            key = '' if bounds is None else f'?flickr_start={bounds[0]}&end={bounds[1]}'
            with urllib.request.urlopen(urllib.request.Request(url + key, headers=headers), timeout=90) as res:
                data = res.read()
                if bounds:
                    expected = f'bytes {bounds[0]}-{bounds[1]}/'
                    assert res.status == 206 and res.headers['Content-Range'].startswith(expected)
                    assert len(data) == bounds[1]-bounds[0]+1
                return data
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1+attempt)


class RemoteZip(io.RawIOBase):
    """Seek in a remote zip with validated ranges. Cache only the active working set."""
    def __init__(self, url, size, block=8 * 1024 * 1024):
        self.url = url
        self.size = size
        self.block = block
        self.pos = 0
        self.cache = OrderedDict()
        self.receipts = {}
    
    def seek(self, offset, whence=0):
        self.pos = (0, self.pos, self.size)[whence] + offset
        return self.pos
    
    def tell(self):
        return self.pos
    
    def seekable(self):
        return True
    
    def read(self, n=-1):
        end = self.size if n < 0 else min(self.size, self.pos+n)
        if self.pos >= end:
            return b''
        result = []
        while self.pos < end:
            block = self.pos // self.block
            start = block * self.block
            if block not in self.cache:
                stop = min(self.size, start+self.block)-1
                data = get(self.url, (start, stop))
                self.cache[block] = data
                self.receipts[str(block)] = [start,stop,digest(data)]
                if len(self.cache)>4:
                    self.cache.popitem(last=False)
            value = self.cache[block]
            take = min(end-self.pos, len(value) - (self.pos-start))
            result.append(value[self.pos-start:self.pos-start+take])
            self.pos += take
        return b''.join(result)


def main(old, out):
    out.mkdir(parents=True, exist_ok=True)
    if (out/'data.json').exists():
        return
    tick = time.perf_counter()
    source_caption = get(CAPTIONS,(0,2340800))
    text = zipfile.ZipFile(io.BytesIO(source_caption))
    vocab = json.loads((old/'vocabulary.json').read_text())
    captions = {}
    for raw in text.read('Flickr8k.token.txt').decode('utf8').splitlines():
        key, cap = raw.split('\t',1)
        name = key.rsplit('#',1)[0]
        norm = ' '.join(re.findall(r'[a-z0-9]+',cap.lower()))
        captions.setdefault(name, []).append(norm)
    names = {}
    for split, group, cap in (('train','train',1024),('dev','dev',192),('test','test',None)):
        value = text.read(f'Flickr_8k.{group}Images.txt').decode().split()
        names[split] = sorted(value,key=lambda f:digest(f.encode()))[:cap]
    selected = set().union(*(set(x) for x in names.values()))
    assert sum(map(len,names.values())) == len(selected)
    remote = RemoteZip(PHOTO,1115419746)
    source_photo = zipfile.ZipFile(remote)
    entries = {i.filename.rsplit('/',1)[-1]:i for i in source_photo.infolist()
               if i.filename.startswith('Flicker8k_Dataset/') and i.filename.endswith('.jpg')}
    assert len(selected - set(entries)) == 0
    old_meta=json.loads((old/'data.json').read_text())
    old_pixels=np.load(old_meta['pixels'],mmap_mode='r')
    old_hashes={digest(row.tobytes()) for row in old_pixels}
    records={}
    for idx, name in enumerate(sorted(selected,key=lambda x:entries[x].header_offset)):
        item=entries[name]
        jpeg=source_photo.read(item)
        im=Image.open(io.BytesIO(jpeg)).convert('RGB')
        rgb_sig=digest(im.width.to_bytes(4,'little')+im.height.to_bytes(4,'little')+im.tobytes())
        pixels=np.asarray(im.resize((32,32),Image.Resampling.BILINEAR))
        caption=min(captions[name],key=lambda c:digest((name+' '+c).encode()))
        records[name]=(pixels,caption,rgb_sig,digest(jpeg),digest(pixels.tobytes()),item.CRC)
        if idx%250==0: print('decoded',idx,len(selected),flush=True)
    seen=set();seen32=set();removed=[];report={}; identity=[]
    for split, roster in names.items():
        panels=[]; targets=[]; inputs=[]; manifest=[]; freqs=Counter();truncated=0
        for name in roster:
            rgb, sentence, full_sha, jpeg_sha, psha, crc=records[name]
            if full_sha in seen or psha in seen32 or psha in old_hashes:
                removed.append({'split':split,'name':name,'old':psha in old_hashes})
                continue
            seen.add(full_sha);seen32.add(psha)
            ws=sentence.split()
            words=[vocab.get(w,1) for w in ws[:16]]
            labels=words+([3] if len(ws)<=16 else [])
            pre=([2]+words)[:len(labels)]
            panels.append(rgb); inputs.append(pre+[0]*(17-len(pre)));targets.append(labels+[0]*(17-len(labels)))
            truncated+=len(ws)>16;freqs.update(labels)
            manifest.append(dict(name=name,caption=sentence,jpeg_sha=jpeg_sha,rgb_sha=full_sha,pixel_sha=psha,zip_crc=crc))
        identity.extend(dict(split=split,**r) for r in manifest)
        target=np.asarray(targets,dtype=np.int16)
        path=out/(split+'.npz')
        np.savez_compressed(path,pix=np.stack(panels),x=np.array(inputs,dtype=np.int16),y=target,name=np.array([x['name'] for x in manifest]))
        report[split]=dict(images=len(manifest),tokens=int((target>0).sum()),truncated=int(truncated),known=int((target>=4).sum()),
                           unknown=int((target==1).sum()),lexical_oov=float((target==1).sum()/((target==1)|(target>=4)).sum()),
                           sha=digest(path.read_bytes()),counts=dict(freqs))
    (out/'identities.json').write_text(json.dumps(identity,indent=1)+'\n')
    (out/'data.json').write_text(json.dumps(dict(archives=[PHOTO,CAPTIONS],source_lengths=[1115419746,len(source_caption)],photo_verified_ranges=remote.receipts,
       caption_sha=digest(source_caption),source_vocabulary=old_meta['vocabulary_sha'],splits=report,removed=removed,
       identities_sha=digest((out/'identities.json').read_bytes()),acquisition_and_preparation_s=time.perf_counter()-tick),indent=1)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('old',type=Path)
    parser.add_argument('out',type=Path)
    a=parser.parse_args()
    main(a.old,a.out)
