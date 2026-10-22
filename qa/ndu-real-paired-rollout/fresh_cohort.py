"""Build a NEW official COCO cohort excluding both historical and frozen v1 sources.

Consumes real original-image provenance, not the v1 generated predictions or its
held-out outcomes. No image / entity / pretraining independence beyond COCO ID,
exact RGB and dHash distance checks is claimed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
V1 = Path(__file__).resolve().parent.parent / 'ndu-grounded-generation'
if V1.is_dir():
    sys.path.insert(0, str(V1))


EXPECTED_HISTORICAL_SHA256 = '4c2b88f85c9ef5fea08790775a652798a72e9281bed1534561f14c681e7bba9d'
EXPECTED_V1_COHORT_SHA256 = '71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d'


def combine_exclusions(historical, prior_v1_manifest, output, *, require_pinned=True):
    historical, prior_v1_manifest, output = map(Path,(historical,prior_v1_manifest,output))
    old_sha=hashlib.sha256(historical.read_bytes()).hexdigest()
    frozen_sha=hashlib.sha256(prior_v1_manifest.read_bytes()).hexdigest()
    if require_pinned and (old_sha != EXPECTED_HISTORICAL_SHA256 or
                           frozen_sha != EXPECTED_V1_COHORT_SHA256):
        raise ValueError('prior historical and P1 source manifests must match their frozen byte digests')
    old=json.loads(historical.read_text())['source_sample']['images']
    previous=json.loads(prior_v1_manifest.read_text())
    if previous.get('schema')!='hepta.grounded-cohort.v1' or \
       set(previous.get('splits',{}))!={'train','dev','calibration','test'}:
        raise ValueError('v1 historical original-image manifest is required')
    if len(old)<384 or sum(previous['splits'][s]['count'] for s in previous['splits'])<256:
        raise ValueError('incomplete historical/v1 exclusions')
    images=list(old)
    seen={int(row['image_id']) for row in images}
    for split in ('train','dev','calibration','test'):
        for row in previous['splits'][split]['sources']:
            if int(row['image_id']) in seen:
                raise ValueError('historical duplicate image ID cannot be relabeled')
            if any(k not in row for k in ('image_sha256','decoded_rgb_sha256','dhash64')):
                raise ValueError('missing prior source fingerprint')
            seen.add(int(row['image_id']))
            images.append({k:row[k] for k in ('image_id','image_sha256','decoded_rgb_sha256','dhash64')})
    if len(images)<640:
        raise ValueError('combined source exclusion below 640 original images')
    if output.exists():
        raise FileExistsError('frozen exclusions must never be overwritten')
    manifest={'schema':'hepta.ndu.p3-combined-exclusions.v1',
              'source_sample':{'images':images},
              'historical_file_sha256':old_sha,
              'frozen_v1_manifest_sha256':frozen_sha,
              'claim':'COCO source ID and fingerprint exclusion only; not independent entity/pretraining claim'}
    output.parent.mkdir(parents=True,exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if os.name == 'posix':
        flags |= os.O_NOFOLLOW
    fd = os.open(output, flags, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(manifest, sort_keys=True, allow_nan=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == 'posix':
        parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official-annotations',required=True)
    parser.add_argument('--historical-exclusions',required=True)
    parser.add_argument('--v1-cohort-manifest',required=True)
    parser.add_argument('--output-cohort',required=True)
    parser.add_argument('--image-cache',required=True)
    parser.add_argument('--download-images',action='store_true')
    args=parser.parse_args()
    from cohort import build_cohort,validate_splits
    output=Path(args.output_cohort)
    exclusions=output.parent/(output.name+'.prior-exclusions.json')
    combine_exclusions(args.historical_exclusions,args.v1_cohort_manifest,exclusions)
    build_cohort(args.official_annotations,output,sizes=(128,32,32,64),
                 exclusion_manifest=str(exclusions),image_cache=args.image_cache,
                 download_images=args.download_images,seed='hepta-ndu-terminal-real-v2-20261022')
    print(json.dumps(validate_splits(output),sort_keys=True))


if __name__=='__main__':
    main()
