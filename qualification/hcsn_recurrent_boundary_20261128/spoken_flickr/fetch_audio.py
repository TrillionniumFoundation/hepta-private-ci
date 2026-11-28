"""Resume validated byte ranges of the original MIT archive and check the publisher's MD5."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

URL='https://groups.csail.mit.edu/sls/downloads/flickraudio/downloads/flickr_audio.tar.gz'
TOTAL=4447689760
EXPECTED_MD5='9d078f1f150c26e864aa64d1d733779a'
CHUNK=32*1024*1024


def fetch(home):
    pieces=home/'ranges';pieces.mkdir(exist_ok=True)
    destination=home/'flickr_audio.tar.gz'
    if (home/'source.sha256').exists():return
    upstream=home/'flickr_audio.tar.gz.partial'
    def part(index):
        start=index*CHUNK;stop=min(start+CHUNK,TOTAL);target=pieces/f'{index:03d}.bin'
        if target.exists() and target.stat().st_size==stop-start:return target
        tmp=target.with_suffix('.partial')
        if not tmp.exists() and upstream.exists() and upstream.stat().st_size>start:
            with upstream.open('rb') as src,tmp.open('wb') as dst:
                src.seek(start);dst.write(src.read(stop-start))
        for attempt in range(10):
            have=tmp.stat().st_size if tmp.exists() else 0
            if have==stop-start:
                tmp.replace(target);return target
            if have>stop-start:raise ValueError('invalid staged range size')
            first=start+have
            request=urllib.request.Request(URL,headers={'Range':f'bytes={first}-{stop-1}',
                                                         'Accept-Encoding':'identity'})
            expected=f'bytes {first}-{stop-1}/{TOTAL}'
            try:
                with urllib.request.urlopen(request,timeout=70) as response:
                    if response.status!=206 or response.headers['Content-Range']!=expected:
                        raise ValueError(('range mismatch',response.status,response.headers.get('Content-Range'),expected))
                    with tmp.open('ab') as out:
                        while block:=response.read(2**17):out.write(block)
            except (OSError,TimeoutError) as ex:
                print('range retry',index,attempt,type(ex).__name__,flush=True);time.sleep(min(20,1+attempt))
        if tmp.stat().st_size!=stop-start:raise IOError(('incomplete range',index))
        tmp.replace(target)
        return target

    with ThreadPoolExecutor(6) as pool:
        files=[]
        for path in pool.map(part,range((TOTAL+CHUNK-1)//CHUNK)):
            files.append(path)
            if len(files)%8==0:print('completed ordered ranges',len(files),time.time(),flush=True)
    joined=home/'flickr_audio.joined.partial';source_md5=md5();source_sha=sha256()
    with joined.open('wb') as dst:
        for path in files:
            with path.open('rb') as src:
                while block:=src.read(2**20):source_md5.update(block);source_sha.update(block);dst.write(block)
    if joined.stat().st_size!=TOTAL or source_md5.hexdigest()!=EXPECTED_MD5:
        raise ArithmeticError(('upstream digest',source_md5.hexdigest(),joined.stat().st_size))
    joined.replace(destination)
    (home/'source.sha256').write_text(source_sha.hexdigest()+'  flickr_audio.tar.gz\n')
    (home/'range_download.json').write_text(json.dumps(dict(url=URL,bytes=TOTAL,md5=EXPECTED_MD5,
                   sha256=source_sha.hexdigest(),completed=time.time(),number_of_ranges=len(files)),indent=2)+'\n')
    print('verified source',TOTAL,source_sha.hexdigest(),flush=True)


if __name__=='__main__':
    fetch(Path(sys.argv[1]))
