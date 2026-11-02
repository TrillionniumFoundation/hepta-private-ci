"""Acquire the original72 development FLV bytes only; never decode media."""
from concurrent.futures import ThreadPoolExecutor
import json

from experiments.hcsn_video_raw_r2_20261101 import raw_data


def main():
    cohort=json.loads(raw_data.COHORT.read_text())
    training=json.loads((raw_data.HERE/'inputs/train_IDENTITY.json').read_text())
    if raw_data.sha(raw_data.COHORT)!=training['cohort_sha256']:raise ValueError('Originalcohortidentity')
    rows=sorted([r for r in cohort['records'] if r['split']=='validation'],key=lambda r:r['clip'])
    if len(rows)!=72 or sorted({r['actor'] for r in rows})!=['1006','1017','1026','1054','1055','1056']:raise ValueError('Original72recordingcohort')
    with ThreadPoolExecutor(max_workers=3) as executor:receipts=list(executor.map(raw_data.acquire,rows))
    result=dict(schema='hcsn.crema.development.raw-acquisition.v1',records=receipts,clips=len(rows),actors=sorted({r['actor'] for r in rows}),cohort_sha256=raw_data.sha(raw_data.COHORT),source_sha256=raw_data.sha(__file__),acquire_helper_sha256=raw_data.sha(raw_data.__file__),raw_bytes=sum(r['bytes'] for r in rows),media_decoded=False,model_used=False,scope='Onlyoriginalregistered72historicaldevelopmentrawFLVbytes; unifiedcandidatefreeze/go received; no substitution')
    raw_data.write(raw_data.HERE/'DEVELOPMENT_RAW_ACQUISITION.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},sort_keys=True),flush=True)


if __name__=='__main__':main()
