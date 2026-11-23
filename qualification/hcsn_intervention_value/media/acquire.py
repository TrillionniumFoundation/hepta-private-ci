"""Acquire Wikimedia Commons originals serially and verify pinned original byte digests."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import time
from urllib import error, request

HERE=Path(__file__).resolve().parent


def utc():
    return datetime.now(timezone.utc).isoformat()


def wait_seconds(value):
    if value is None:return 60
    try: return max(1,int(value))
    except ValueError: return max(1,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())


def digests(path):
    hashes=[hashlib.sha1(),hashlib.sha256()]
    with path.open('rb') as fh:
        while data:=fh.read(1<<20):
            for h in hashes:h.update(data)
    return [h.hexdigest() for h in hashes]


def log(path, **data):
    with path.open('a') as fh:
        print(json.dumps(dict(utc=utc(),**data)),file=fh,flush=True)


def acquire(row,root,ledger):
    out=root/'media-cache'/(str(row['pageid'])+Path(row['title']).suffix)
    if out.exists():
        sha1,sha256=digests(out)
        if sha1!=row['sha1'] or out.stat().st_size!=row['size']:
            raise ValueError(f'cached bytes disagree with pinned revision {out}')
        log(ledger,pageid=row['pageid'],action='verified_cache',sha1=sha1,sha256=sha256,size=out.stat().st_size)
        return
    url=row['url']; part=out.with_suffix('.part')
    for attempt in range(1,6):
        t=time.perf_counter()
        try:
            req=request.Request(url,headers={'User-Agent':'HeptaResearch/1.0 (https://github.com/TrillionniumFoundation/hepta-private-ci; research reproducibility)'})
            with request.urlopen(req,timeout=120) as resp, part.open('wb') as fh:
                while data:=resp.read(1<<20):fh.write(data)
            sha1,sha256=digests(part)
            if part.stat().st_size!=row['size'] or sha1!=row['sha1']:
                raise ValueError(f'publisher size or SHA-1 mismatch for {url}')
            part.replace(out)
            log(ledger,pageid=row['pageid'],action='acquired',sha1=sha1,sha256=sha256,
                size=out.stat().st_size,seconds=time.perf_counter()-t,url=url)
            print('acquired',row['pageid'],row['split'],out.stat().st_size,flush=True)
            # Keep the single-stream publisher media fetch lightly paced.
            time.sleep(4)
            return
        except error.HTTPError as ex:
            retry=wait_seconds(ex.headers.get('Retry-After'))
            log(ledger,pageid=row['pageid'],action='http_error',status=ex.code,attempt=attempt,
                retry_after_seconds=retry,seconds=time.perf_counter()-t)
            if attempt==5 or ex.code not in (408,429,500,502,503,504):raise
            print('publisher wait',row['pageid'],ex.code,retry,flush=True)
            time.sleep(retry+1)
        except (TimeoutError,error.URLError) as ex:
            log(ledger,pageid=row['pageid'],action='transport_error',attempt=attempt,detail=str(ex))
            if attempt==5:raise
            time.sleep(15*attempt)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root',type=Path,required=True)
    cli.add_argument('--not-before',help='UTC ISO timestamp from a previous Retry-After')
    ns=cli.parse_args();root=ns.root.resolve()
    (root/'media-cache').mkdir(parents=True,exist_ok=True);ledger=root/'acquisition.jsonl'
    manifest=HERE/'sources.json'
    log(ledger,action='begin',sources_sha256=digests(manifest)[1],not_before=ns.not_before)
    if ns.not_before:
        until=datetime.fromisoformat(ns.not_before).timestamp()
        time.sleep(max(0,until-time.time()))
    for row in json.loads(manifest.read_text()):acquire(row,root,ledger)
    log(ledger,action='done')
if __name__=='__main__':main()
