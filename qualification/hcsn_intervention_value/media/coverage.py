"""Inspect the original decoded PCM timeline and classify physically unobserved intervals."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

if __package__:
    from . import recording_features
else:
    import recording_features

PATTERN=rb'\bn:\s*(\d+)\s+pts:(-?\d+)\s+pts_time:[-+\.\deE]+.*?\brate:(\d+)\s+nb_samples:(\d+)'


def inspect(path):
    stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0',
                      '-show_streams','-of','json',path]))['streams'][0]
    rate=int(stream['sample_rate'])
    # Packet timestamps can be rounded to the stream's published time base.
    tolerance=max(1,int(np.ceil(rate*Fraction(stream['time_base']))))
    args=['ffmpeg','-hide_banner','-nostdin','-v','info','-threads','1','-i',path,'-map','0:a:0',
          '-af','asettb=expr=1/sr,ashowinfo','-f','null','-']
    result=subprocess.run(args,check=True,capture_output=True)
    blocks=[(int(n),int(t),int(sr),int(size)) for n,t,sr,size in re.findall(PATTERN,result.stderr)]
    if not blocks or any(i!=n or sr!=rate or sz<=0 for i,(n,p,sr,sz) in enumerate(blocks)):
        raise ValueError('invalid original decoded sample timeline')
    gaps=[]
    for left,right in zip(blocks,blocks[1:]):
        end=left[1]+left[3];start=right[1]
        if start-end>tolerance:
            gaps.append({'start':end,'end':start,'left_frame':left[0],'left_pts':left[1],
                         'left_count':left[3],'right_frame':right[0],'right_pts':right[1]})
    return {'rate':rate,'rounding_tolerance_samples':tolerance,'time_base':stream['time_base'],
            'frames':len(blocks),'stream_start':blocks[0][1],'stream_end':blocks[-1][1]+blocks[-1][3],
            'decoded_samples':sum(b[3] for b in blocks),'internal_gaps':gaps,
            'timeline_sha256':hashlib.sha256(json.dumps(blocks,separators=(',',':')).encode()).hexdigest()}


def missing_for(record,start):
    rate=record['rate'];lo=round(start*rate);hi=round((start+2.88)*rate)
    intervals=[(lo,record['stream_start']),
               *((g['start'],g['end']) for g in record['internal_gaps']),
               (record['stream_end'],hi)]
    return [[max(lo,a),min(hi,b)] for a,b in intervals if min(hi,b)>max(lo,a)]


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--roster',required=True,type=Path);cli.add_argument('--out',required=True,type=Path)
    ns=cli.parse_args();rows=json.loads(ns.roster.read_text());streams={};queries=[]
    for r in rows:
        key=r['recording']
        if key not in streams:streams[key]=inspect(r['local_media'])
        gaps=missing_for(streams[key],r['start_seconds'])
        queries.append({'query_id':r['query_id'],'recording':key,'start_seconds':r['start_seconds'],
                        'missing_original_samples':sum(b-a for a,b in gaps),'intervals_halfopen':gaps})
    result={'roster_sha256':hashlib.sha256(ns.roster.read_bytes()).hexdigest(),
            'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'streams':streams,'queries':queries}
    ns.out.write_text(json.dumps(result,indent=2)+'\n')
    print('coverage',[(r['query_id'],r['missing_original_samples']) for r in queries if r['missing_original_samples']],flush=True)
if __name__=='__main__':main()
