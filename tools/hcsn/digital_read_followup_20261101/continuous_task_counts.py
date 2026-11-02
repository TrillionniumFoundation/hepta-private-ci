"""Post-run receipt counts; no world/model generation or quality inference."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import sys


def extract(path):
    r=json.loads(gzip.decompress(path.read_bytes()))
    orig=[d for e in r['episodes'] for d in e['episode']['rows']]
    replay=[d for e in r['episodes'] for rr in e['resumes'] for d in rr['replay']['rows']]
    def counts(rows):
        return dict(attempts=sum(x['receipt']['source_opened'] is not None for x in rows),
          successes=sum(x['receipt']['completion'] is not None and not x['receipt']['completion'].get('failure',False) for x in rows),
          failures=sum(x['receipt']['completion'] is not None and x['receipt']['completion'].get('failure',False) for x in rows),
          actions=dict(collections.Counter(x['action'] for x in rows)))
    release=0
    for row in orig:
        if row['action'] in (0,4,5):continue
        dt=row['receipt']['after']['elapsed']-row['receipt']['before']['elapsed']
        release+=(row['cell_before']['mode']!=0 and row['cell_before']['refractory_remaining']<=dt)
        release+=sum(ev['release_time']<=dt for ev in row['events'])
    return dict(original=counts(orig),replays=counts(replay),actual_releases=release,
      multi_event_intervals=sum(len(x['events'])>=2 for x in orig),
      source_opens_total=counts(orig)['attempts']+counts(replay)['attempts'],
      successful_reads_total=counts(orig)['successes']+counts(replay)['successes'],
      wall_seconds=r['wall_seconds'],cpu_seconds=r['cpu_seconds'],content_setup=r['content_setup'],
      raw_bytes=path.stat().st_size,raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


if __name__=='__main__':
    path=Path(sys.argv[1]);value=extract(path)
    # JSON round-trip normalizes integer action-count keys for exact comparison.
    value=json.loads(json.dumps(value));counts_path=path.with_name('COUNTS.json')
    if counts_path.exists():assert json.loads(counts_path.read_text())==value
    else:
        with counts_path.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(value,indent=2,sort_keys=True))
