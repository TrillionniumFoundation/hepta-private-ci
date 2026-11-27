from pathlib import Path
import urllib.request,hashlib,json,os,time
BASE=Path(os.environ.get('HCSN_CATALOG_DATA',Path(__file__).resolve().parents[1]/'paired_catalog'))
OUT=BASE/'clip_assets';OUT.mkdir(exist_ok=True)
PIN='d05afc436d78f1c48dc0dbf8e5980a9d471f35f6';HS='40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af'
def get(name,url,cap,expected=None):
    dest=OUT/name
    if not dest.exists():
        part=dest.with_suffix('.download')
        with urllib.request.urlopen(url,timeout=100) as src,part.open('wb') as dst:
            for block in iter(lambda:src.read(1048576),b''):
                if dst.tell()+len(block)>cap:raise RuntimeError('unexpected asset size')
                dst.write(block)
        digest=hashlib.file_digest(part.open('rb'),'sha256').hexdigest()
        if expected and expected!=digest:raise ValueError('published model checksum mismatch')
        part.replace(dest)
    digest=hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()
    if expected:assert digest==expected
    print(name,dest.stat().st_size,digest,flush=True)
    return {'url':url,'bytes':dest.stat().st_size,'sha256':digest}
def main():
    rec={}
    for name in ['model.py','simple_tokenizer.py','bpe_simple_vocab_16e6.txt.gz']:
        rec[name]=get(name,'https://raw.githubusercontent.com/openai/CLIP/'+PIN+'/clip/'+name,2500000)
    rec['ViT-B-32.pt']=get('ViT-B-32.pt','https://openaipublic.azureedge.net/clip/models/'+HS+'/ViT-B-32.pt',450000000,HS)
    (OUT/'source.json').write_text(json.dumps(rec,indent=1))
if __name__=='__main__':main()
