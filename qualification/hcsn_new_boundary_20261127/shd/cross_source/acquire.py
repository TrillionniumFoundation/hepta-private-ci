"""Optional original-PCM replay. Fetch the official releases into the local data directory."""
from pathlib import Path
import argparse,hashlib,io,json,tarfile,urllib.request,zipfile
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def get(url,destination,expected):
    if not destination.exists():
        import shutil
        tmp=destination.with_suffix(destination.suffix+'.part')
        with urllib.request.urlopen(url,timeout=120) as stream,tmp.open('wb') as out:shutil.copyfileobj(stream,out,1024*1024)
        assert sha(tmp)==expected;tmp.replace(destination)
    assert sha(destination)==expected
def main(root):
    meta=json.loads((root/'dataset.json').read_text());cm=json.loads((root/'command/dataset.json').read_text())
    get('https://codeload.github.com/Jakobovski/free-spoken-digit-dataset/zip/'+meta['fsdd_commit'],root/'fsdd.zip',meta['data_files']['fsdd.zip'])
    get(meta['arabic_source'],root/'arabic.zip',meta['data_files']['arabic.zip'])
    orig=root/'command/speech_commands_v0.02.tar.gz';get(cm['archive'],orig,cm['sha256'])
    keys=json.loads((root/'command/retained-source.json').read_text())['byte_checks']
    dest=root/'command/selected-originals.zip'
    if not dest.exists():
        temp=dest.with_suffix('.zip.part');included=set()
        with tarfile.open(orig,'r|gz') as tar,zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            for f in tar:
                name=f.name.removeprefix('./')
                if name in keys:
                    b=tar.extractfile(f).read();assert hashlib.sha256(b).hexdigest()==keys[name]
                    z.writestr(name,b);included.add(name)
        assert included==set(keys);temp.replace(dest)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('data',type=Path);main(ap.parse_args().data)
