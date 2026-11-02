"""Metadata-only GRID cohort selection; no MPEG member payload requests."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
import traceback

from experiments.hcsn_grid_frontend_r2_20261101.metadata_range import inspect

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'hcsn_video_raw_r2_20261101/external_grid/SPEAKER1_METADATA.json'
ROLES = {'train': [1,3,4,5,6,7], 'development': [8,9], 'confirmation': [10,11,12,13]}
PRIOR_SHA = '731cad9691fc6406d777c1946160a4807deb5b08cf514e4b7b760981cb6b812b'
PRIOR_CENTRAL = 'de4b46b9d59b5f4cfcc1bf3d04be79de2932b00949d2b74c2c50298ad99de6c5'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    payload=json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n'
    if path.exists():
        if path.read_text()!=payload:
            raise FileExistsError(path)
    else:
        with path.open('x') as output: output.write(payload)


def selected(metadata):
    result=[]
    for target,prefix in [(0,'b'),(1,'s')]:
        rows=[row for row in metadata['members'] if PurePosixPath(row['name']).name.startswith(prefix)
              and row['name'].endswith('.mpg')]
        rows=sorted(rows,key=lambda row:row['name'])[:16]
        if len(rows)!=16:
            raise ValueError('Insufficient registered class members')
        for row in rows:
            if row['encrypted'] or row['compression'] not in [0,8] or row['bytes']<=0:
                raise ValueError('Selected member profile')
            result.append(row|dict(sentence_target=target,command='bin' if target==0 else 'set'))
    return result


def collect(speaker):
    url=f'https://spandh.dcs.shef.ac.uk/gridcorpus/s{speaker}/video/s{speaker}.mpg_vcd.zip'
    path=HERE/'metadata'/f's{speaker}.json'
    if path.exists():
        metadata=json.loads(path.read_text())
        if metadata['url']!=url or metadata.get('media_members_downloaded')!=0:
            raise ValueError('Existing metadata profile')
        return speaker,metadata,dict(reused=True,source='current metadata-only record',path=str(path.relative_to(HERE)))
    if speaker==1:
        if digest(PRIOR)!=PRIOR_SHA:
            raise ValueError('Existing speaker1 source identity')
        metadata=json.loads(PRIOR.read_text())
        if metadata['url']!=url or metadata['central_sha256']!=PRIOR_CENTRAL:
            raise ValueError('Existing speaker1 central identity')
        reused=dict(reused=True,source=str(PRIOR.relative_to(HERE.parent.parent)),source_sha256=PRIOR_SHA)
    else:
        metadata=inspect(url)
        reused=dict(reused=False,source='exact HTTP206 EOCD and ZIP central directory only')
    # Validate fixed class selection before preserving the metadata.
    selected(metadata)
    write(path,metadata)
    return speaker,metadata,reused


def main():
    protocol=HERE/'PROTOCOL.json'
    if not protocol.is_file():
        raise FileNotFoundError('Parent-owned prospective PROTOCOL.json must exist before metadata requests')
    json.loads(protocol.read_text())
    protocol_sha=digest(protocol)
    source_sha=digest(__file__)
    helper_sha=digest(HERE/'metadata_range.py')
    actors=[speaker for group in ROLES.values() for speaker in group]
    assert len(actors)==12 and len(set(actors))==12 and 2 not in actors
    out=HERE/'metadata';out.mkdir(exist_ok=True)
    snapshot=out/f'PROTOCOL_SNAPSHOT_{protocol_sha}.json'
    payload=protocol.read_bytes()
    if snapshot.exists():
        if snapshot.read_bytes()!=payload:raise ValueError('Protocol snapshot mismatch')
    else:
        with snapshot.open('xb') as output:output.write(payload)
    tick=time.perf_counter();records={};failures=[]
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs={executor.submit(collect,speaker):speaker for speaker in actors}
        for future in as_completed(jobs):
            speaker=jobs[future]
            try:
                result=future.result();records[speaker]=result
                print(json.dumps(dict(metadata_ready=speaker)),flush=True)
            except Exception as error:
                failure=dict(speaker=speaker,error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
                failures.append(failure)
                write(out/f's{speaker}_FAILURE_{time.time_ns()}.json',failure)
    if failures:
        write(HERE/f'METADATA_FAILURES_{time.time_ns()}.json',dict(protocol_sha256=protocol_sha,failures=failures,
              successful_speakers=sorted(records),successful_metadata=[dict(speaker=s,url=m['url'],metadata_bytes=0 if r['reused'] else m['metadata_bytes_downloaded'],metadata_sha256=digest(out/f's{s}.json')) for s,m,r in records.values()],media_payloads_downloaded=0))
        raise RuntimeError(f'{len(failures)} metadata-only speaker requests failed; successful metadata retained')
    if digest(protocol)!=protocol_sha or digest(__file__)!=source_sha or digest(HERE/'metadata_range.py')!=helper_sha:
        raise ValueError('Prospective source/protocol changed during collection')
    entries=[];provenance=[]
    for role,group in ROLES.items():
        for speaker in group:
            _,metadata,reuse=records[speaker]
            path=out/f's{speaker}.json'
            provenance.append(dict(speaker=speaker,role=role,url=metadata['url'],archive_bytes=metadata['archive_bytes'],
                central_sha256=metadata['central_sha256'],suffix_sha256=metadata['suffix_sha256'],
                metadata_sha256=digest(path),metadata_path=str(path.relative_to(HERE)),
                member_count=metadata['member_count'],metadata_bytes_downloaded_this_request=0 if reuse['reused'] else metadata['metadata_bytes_downloaded'],
                provenance=reuse))
            for member in selected(metadata):
                if not member['name'].startswith(f's{speaker}/'):
                    raise ValueError('Selected member speaker namespace')
                entries.append(member|dict(speaker=speaker,speaker_namespace=f'GRID:{speaker}',role=role,
                    url=metadata['url'],archive_bytes=metadata['archive_bytes'],central_sha256=metadata['central_sha256'],
                    metadata_sha256=digest(path)))
    raw_bytes=sum(row['bytes'] for row in entries)
    if len(entries)!=384 or raw_bytes>170000000:
        raise ValueError('Registered384clip/170MB raw capacity')
    if len({(r['speaker'],r['name']) for r in entries})!=384:
        raise ValueError('Duplicate selected source member')
    result=dict(schema='hcsn.grid.frontend.cohort-selection.v1',roles=ROLES,selection='First16bin(b*) and first16set(s*) MPEG members per speaker, sorted lexical source member name',
        entries=entries,speaker_metadata=provenance,selected_count=len(entries),raw_uncompressed_bytes=raw_bytes,
        compressed_payload_bytes=sum(r['compressed_bytes'] for r in entries),
        metadata_bytes_downloaded_this_request=sum(row['metadata_bytes_downloaded_this_request'] for row in provenance),
        protocol_sha256=protocol_sha,source_sha256=source_sha,range_helper_sha256=helper_sha,
        media_payloads_downloaded_by_this_collector=0,frames_decoded_by_this_collector=0,model_training_performed=False,
        exposure='ZIP central-directory member names encode class labels and were accessed for all selected speaker roles before this selection freeze. No new MPEG member payload or frame/outcome access.',
        prior_training_speaker1='The existing32speaker1pilot files were acquired before this separate study; speaker1 remains training-only. Public GRID:2 swwp2s example discovery is excluded by actor2 exclusion.',
        historical_scope='Speaker namespaces are disjoint within this GRID study. No global historical human-identity or newly-recorded-today claim.',
        wall_seconds=time.perf_counter()-tick)
    write(HERE/'COHORT_SELECTION.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['entries','speaker_metadata']},sort_keys=True))


if __name__=='__main__':
    main()
