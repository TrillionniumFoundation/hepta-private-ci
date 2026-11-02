"""Registered GRID source ranges and physical-prefix AV; no held role shortcuts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import zlib

import numpy as np
from scipy.signal import resample_poly

from experiments.hcsn_grid_frontend_r2_20261101.metadata_range import request_range

HERE=Path(__file__).resolve().parent
RAW=HERE.parents[2]/'grid_raw_r2_media'
PRIOR=HERE.parent/'hcsn_video_raw_r2_20261101/external_grid/PILOT_ACQUISITION.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n'
    if path.exists():
        if path.read_text()!=payload:raise FileExistsError(path)
    else:
        with path.open('x') as stream:stream.write(payload)


def location(row):
    basename=Path(row['name']).name
    legacy=RAW/basename
    return legacy if row['speaker']==1 and legacy.exists() else RAW/f"s{row['speaker']}"/basename


def acquire(row):
    path=location(row);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size:
        data=path.read_bytes()
        if len(data)!=row['bytes'] or (zlib.crc32(data)&0xffffffff)!=int(row['crc32'],16):raise ValueError('Conflictingcacheidentity')
        if row['speaker']==1:
            bound=json.loads((HERE/'SOURCE_FREEZE.json').read_text())['dependencies']
            if sha(PRIOR)!=bound['prior_training_pilot_sha256']:raise ValueError('Priorpilotmanifestidentity')
            prior=json.loads(PRIOR.read_text());wanted=next(r['sha256'] for r in prior['records'] if r['member']==row['name'])
            if hashlib.sha256(data).hexdigest()!=wanted:raise ValueError('PriortrainingcacheSHAidentity')
        return dict(member=row['name'],speaker=row['speaker'],role=row['role'],bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),reused=True)
    offset,total=row['local_header_offset'],row['archive_bytes']
    header,_=request_range(row['url'],offset,offset+29,total)
    signature,version,flags,compression,mtime,mdate,crc,compressed,size,namesize,extrasize=struct.unpack('<4s5H3L2H',header)
    if signature!=b'PK\x03\x04' or flags&1 or compression!=row['compression']:raise ValueError('Localheaderprofile')
    expected=(int(row['crc32'],16),row['compressed_bytes'],row['bytes'])
    if flags&8:
        if any(a not in (0,b) for a,b in zip((crc,compressed,size),expected)):raise ValueError('Streamingheaderidentity')
        crc,compressed,size=expected
    elif (crc,compressed,size)!=expected:raise ValueError('Localheaderidentity')
    if compressed>2*1024**2 or size>2*1024**2:raise ValueError('Membercapacity')
    block,_=request_range(row['url'],offset+30,offset+29+namesize+extrasize+compressed,total)
    if block[:namesize].decode('utf-8' if flags&2048 else 'cp437')!=row['name']:raise ValueError('Localnameidentity')
    packed=block[namesize+extrasize:]
    if compression==8:
        decoder=zlib.decompressobj(-15);data=decoder.decompress(packed,size+1)
        if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:raise ValueError('Deflateboundary')
    elif compression==0:data=packed
    else:raise ValueError('Compressionprofile')
    if len(data)!=size or (zlib.crc32(data)&0xffffffff)!=crc:raise ValueError('Payloadidentity')
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_size:raise ValueError('Unexpectedcachedestination')
        mode='wb'  # Only a zero-byte failed acquisition artifact can be repaired.
    else:mode='xb'
    with path.open(mode) as stream:stream.write(data)
    return dict(member=row['name'],speaker=row['speaker'],role=row['role'],bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),reused=False)


def prefix(row):
    path=location(row);data=path.read_bytes()
    if len(data)!=row['bytes'] or (zlib.crc32(data)&0xffffffff)!=int(row['crc32'],16):raise ValueError('Rawsourceidentity')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_frames','-show_entries',
        'stream=codec_type,start_time,width,height,sample_rate:frame=media_type,best_effort_timestamp_time','-of','json',str(path)]))
    times=np.asarray([float(r['best_effort_timestamp_time']) for r in probe['frames'] if r.get('media_type')=='video'])
    audio=next(r for r in probe['streams'] if r['codec_type']=='audio');video=next(r for r in probe['streams'] if r['codec_type']=='video')
    start=float(audio.get('start_time',0));origin=max(start,float(times[0]));rate=int(audio['sample_rate'])
    if not np.all(np.diff(times)>0) or times[-1]<origin+1:raise ValueError('Incompleteorderedprefix')
    cutoffs=origin+np.arange(1,26)/25;selected=np.searchsorted(times,cutoffs,side='right')-1
    width,height=int(video['width']),int(video['height'])
    if width<96 or height<96:raise ValueError('Nativecropcapacity')
    left=max(0,min(width-96,int(width*.50)-48));top=max(0,min(height-96,int(height*.76)-48))
    command=['ffmpeg','-nostdin','-v','error','-xerror','-threads','1','-i',str(path)]
    raw=subprocess.check_output(command+['-map','0:v:0','-an','-vf',f'crop=96:96:{left}:{top},format=gray','-filter_threads','1','-threads','1','-vsync','0','-f','rawvideo','-'])
    frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,96,96)
    if len(frames)!=len(times) or selected.min()<0:raise ValueError('Frametimestampalignment')
    pixels=frames[selected,4:92,4:92].copy()
    wave=np.frombuffer(subprocess.check_output(command+['-map','0:a:0','-vn','-ac','1','-threads','1','-f','f32le','-']),dtype='<f4')
    lo=int(np.ceil((origin-start)*rate-1e-7));hi=int(np.floor((origin+1-start)*rate+1e-7))
    if lo<0 or hi>len(wave) or not rate-1<=hi-lo<=rate:raise ValueError('Nativeaudioprefix')
    divisor=math.gcd(rate,16000);wave=resample_poly(wave[lo:hi].astype(float),16000//divisor,rate//divisor,padtype='constant')
    if not 15998<=len(wave)<=16000:raise ValueError('Resamplelength')
    wave=np.pad(wave,(0,16000-len(wave))).astype(np.float32)
    return wave,pixels,dict(member=row['name'],speaker=row['speaker'],role=row['role'],raw_sha256=hashlib.sha256(data).hexdigest(),origin=origin,
        accepted_end=origin+1,native_geometry=[width,height],crop=[left,top,96,96],selected_timestamps=times[selected].tolist(),audio_samples=len(wave),target=row['sentence_target'])


def acquire_role(role,out,candidate=None):
    cohort=json.loads((HERE/'COHORT_SELECTION.json').read_text());protocol_sha=sha(HERE/'PROTOCOL.json');cohort_sha=sha(HERE/'COHORT_SELECTION.json')
    if cohort['raw_uncompressed_bytes']>170000000 or cohort['selected_count']!=384:raise ValueError('Cohortcapacity')
    if role=='confirmation':
        if candidate is None:raise ValueError('Confirmationrequirespublishedcandidatefreeze')
        publication=json.loads((HERE/'PUBLICATION_CANDIDATE.json').read_text())
        if publication['candidate_sha256']!=sha(candidate):raise ValueError('Candidatepublicationidentity')
        frozen=json.loads(Path(candidate).read_text())
        if frozen['protocol_sha256']!=protocol_sha or frozen['cohort_sha256']!=cohort_sha:raise ValueError('Candidatesourcecohortidentity')
        for relative,value in frozen['source_files'].items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts or sha(HERE/relative)!=value:raise ValueError('Candidatesourcefileidentity')
        for relative,value in frozen['files'].items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts or sha(Path(candidate).parent/relative)!=value:raise ValueError('Candidateheadidentity')
    rows=[r for r in cohort['entries'] if r['role']==role]
    with ThreadPoolExecutor(max_workers=3) as executor:records=list(executor.map(acquire,rows))
    if protocol_sha!=sha(HERE/'PROTOCOL.json') or cohort_sha!=sha(HERE/'COHORT_SELECTION.json'):raise ValueError('Concurrentcohortchange')
    result=dict(schema='hcsn.grid.acquisition.v1',role=role,records=records,protocol_sha256=protocol_sha,cohort_sha256=cohort_sha,source_sha256=sha(__file__),
                raw_bytes=sum(r['bytes'] for r in records),clips=len(records),speaker_ids=sorted({r['speaker'] for r in rows}),frames_decoded=False,model_used=False)
    write(out,result);print(json.dumps({k:v for k,v in result.items() if k!='records'},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('role',choices=['train','development','confirmation']);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--candidate',type=Path);args=parser.parse_args();acquire_role(args.role,args.out,args.candidate)
