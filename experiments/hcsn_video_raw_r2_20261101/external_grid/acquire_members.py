"""Extract only prospectively registered official ZIP member byte ranges."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import zlib

from experiments.hcsn_video_raw_r2_20261101.external_grid.range_zip import request_range

HERE=Path(__file__).resolve().parent
RAW=HERE.parents[3]/'grid_raw_r2_media'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def acquire(row,protocol):
    url,total=protocol['url'],protocol['archive_bytes'];offset=row['local_header_offset']
    header,bounds=request_range(url,offset,offset+29,total)
    signature,version,flags,compression,mtime,mdate,crc,compressed,size,name_len,extra_len=struct.unpack('<4s5H3L2H',header)
    if signature!=b'PK\x03\x04' or flags&1 or compression!=row['compression']:raise ValueError('Local header profile')
    expected=(int(row['crc32'],16),row['compressed_bytes'],row['bytes'])
    if flags&8:
        if any(value not in (0,wanted) for value,wanted in zip((crc,compressed,size),expected)):raise ValueError('Streaminglocalheaderidentity')
        crc,compressed,size=expected
    elif (crc,compressed,size)!=expected:raise ValueError('Local header identity')
    if compressed>1024**2 or size>2*1024**2:raise ValueError('Membercapacity')
    block,_=request_range(url,offset+30,offset+29+name_len+extra_len+compressed,total)
    name=block[:name_len].decode('utf-8' if flags&2048 else 'cp437')
    if name!=row['name']:raise ValueError('Local member name identity')
    payload=block[name_len+extra_len:]
    if compression==8:
        decoder=zlib.decompressobj(-15);data=decoder.decompress(payload,size+1)
        if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:raise ValueError('Deflateboundary')
    elif compression==0:data=payload
    else:raise ValueError('Unsupportedcompression')
    if len(data)!=size or zlib.crc32(data)&0xffffffff!=crc:raise ValueError('Raw payload identity')
    digest=hashlib.sha256(data).hexdigest();RAW.mkdir(exist_ok=True)
    path=RAW/Path(name).name
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('Conflicting rawcache')
    else:
        with path.open('xb') as stream:stream.write(data)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
    return dict(member=row['name'],sha256=digest,bytes=size,crc32=row['crc32'],compressed_bytes=compressed,
                stream_metadata=probe,model_used=False,role='GRIDspeaker1registeredtraining-sourcepilot')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    protocol=json.loads((HERE/'ACQUISITION_PROTOCOL.json').read_text())
    metadata=HERE/'SPEAKER1_METADATA.json'
    if sha(metadata)!=protocol['metadata_sha256']:raise ValueError('Frozen metadataidentity')
    tick=time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:rows=list(executor.map(lambda row:acquire(row,protocol),protocol['selected_members']))
    result=dict(protocol_sha256=sha(HERE/'ACQUISITION_PROTOCOL.json'),source_sha256=sha(__file__),range_source_sha256=sha(HERE/'range_zip.py'),
                records=rows,raw_bytes=sum(r['bytes'] for r in rows),selected_payload_bytes=sum(r['compressed_bytes'] for r in rows),
                source_archive_bytes=protocol['archive_bytes'],model_training_performed=False,confirmation_accessed=False,
                wall_seconds=time.perf_counter()-tick,scope='Registered32officialspeaker1training MPEG files only; sourcequalification, not newtaskmodel orpopulationconfirmation')
    with args.out.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='records'},sort_keys=True))
