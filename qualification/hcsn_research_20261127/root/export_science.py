"""Export every seed and individual score with cold inference and artifact hashes."""
import argparse,hashlib,json,zipfile
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();src=a.source.resolve();dst=a.out.resolve();dst.mkdir(exist_ok=True,parents=True)
    seal=json.loads((src/'seal.json').read_bytes())
    groups={'scores':[src/'seal.json',src/'report.json'],'weights':[]}
    for slot,weight in sorted(seal['states'].items()):
        loc=src/slot;f=loc/'selected.pt';assert sha(f)==weight
        groups['weights'].append(f)
        groups['scores'].extend([loc/'fit.json',loc/'test.json'])
        pred=next(iter(list(loc.glob('pred.npz'))+list(loc.glob('ranks.npz'))))
        j=json.loads((loc/'test.json').read_bytes())
        assert sha(pred)==j.get('prediction_sha256',j.get('ranks_sha256'))
        groups['scores'].append(pred)
    manifest={'states':len(seal['states']),'report_sha256':sha(src/'report.json'),'parts':{}}
    for mode,files in groups.items():
        # A single physical weight may exceed a repository blob budget; transport whole archive as byte slices.
        f=dst/(mode+'.zip')
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
            for t in files:z.write(t,t.relative_to(src))
        with zipfile.ZipFile(f) as z:assert z.testzip() is None
        raw=f.read_bytes()
        manifest['parts'][mode]={'archive_sha256':sha(f),'items':len(files),'bytes':len(raw),'chunks':{}}
        for i,lo in enumerate(range(0,len(raw),320000)):
            part=dst/f'{mode}-{i:03d}.part'
            part.write_bytes(raw[lo:lo+320000]);manifest['parts'][mode]['chunks'][part.name]=sha(part)
    (dst/'manifest.json').write_text(json.dumps(manifest,indent=1))
    print(json.dumps({mode:(item['bytes'],len(item['chunks'])) for mode,item in manifest['parts'].items()}),flush=True)
if __name__=='__main__':main()
