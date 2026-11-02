"""Post-freeze source inventory using the unchanged qualified decoder; no models."""
import argparse
import json
from pathlib import Path
import subprocess

from experiments.hcsn_grid_frontend_r2_20261101 import data_v2 as data


def inventory(role, out):
    cohort=json.loads((data.HERE/'COHORT_SELECTION.json').read_text())
    candidate=data.HERE/'results/run001/CANDIDATE_FREEZE.json'
    rows=[r for r in cohort['entries'] if r['role']==role]
    records=[]
    for row in rows:
        record=dict(member=row['name'],speaker=row['speaker'],role=role,bytes=row['bytes'])
        try:
            wave,pixels,detail=data.prefix(row,candidate)
            record.update(qualified=True,detail=detail,audio_shape=list(wave.shape),video_shape=list(pixels.shape))
        except Exception as error:
            # The complete registered role remains HOLD; no replacement or valid-subset fit.
            record.update(qualified=False,error_type=type(error).__name__,error=str(error))
            path=data.location(row)
            record['raw_sha256']=data.sha(path)
            if isinstance(error,ValueError) and str(error)=='Incompleteorderedprefix':
                probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_frames','-show_entries','stream=codec_type,start_time:frame=media_type,best_effort_timestamp_time','-of','json',str(path)]))
                record['video_pts']=[float(r['best_effort_timestamp_time']) for r in probe['frames'] if r.get('media_type')=='video']
                record['stream_starts']=[dict(codec_type=r['codec_type'],start_time=r.get('start_time')) for r in probe['streams']]
        records.append(record)
    result=dict(role=role,registered_clips=len(rows),registered_actors=sorted({r['speaker'] for r in rows}),
        raw_bytes=sum(r['bytes'] for r in rows),qualified_source_clips=sum(r['qualified'] for r in records),
        failed_source_clips=sum(not r['qualified'] for r in records),records=records,
        decoder_sha256=data.sha(Path(data.__file__)),candidate_sha256=data.sha(candidate),
        acquisition_sha256=data.sha(data.HERE/'inputs'/f'{role.upper()}_ACQUISITION.json'),
        method_changed=False,models_loaded=False,scores_generated=False,valid_subset_adoption=False,
        status='SOURCE_QUALIFIED' if all(r['qualified'] for r in records) else 'SOURCE_FAILURE_HOLD',
        scope='Post-freeze complete registered role source diagnosis through unchanged decoder; no model inference, source exclusion, padding or replacement')
    data.write(out,result)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('role',choices=['development','confirmation']);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    inventory(args.role,args.out)
