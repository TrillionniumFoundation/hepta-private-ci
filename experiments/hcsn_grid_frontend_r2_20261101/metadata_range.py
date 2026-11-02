"""Bounded HTTP206 ZIP metadata inspection; never downloads media members."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import urllib.request


def request_range(url,start,end,total=None):
    headers={'Range':f'bytes={start}-{end}' if start is not None else f'bytes=-{end}'}
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:
        if response.status!=206:raise ValueError('Requires explicit HTTP206; whole archives are refused')
        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
        if match is None:raise ValueError('Missing exact Content-Range')
        lo,hi,size=map(int,match.groups())
        if total is not None and size!=total:raise ValueError('Archive size changed')
        if start is not None and (lo,hi)!=(start,end):raise ValueError('Returned range differs')
        expected=hi-lo+1
        if expected>16*1024**2:raise ValueError('Metadata range capacity')
        data=response.read(expected+1)
        if len(data)!=expected:raise ValueError('Range byte count mismatch')
    return data,(lo,hi,size)


def inspect(url):
    suffix,bounds=request_range(url,None,65536)
    offset=suffix.rfind(b'PK\x05\x06')
    if offset<0 or len(suffix)-offset<22:raise ValueError('No complete EOCD')
    signature,disk,central_disk,disk_count,count,central_size,central_offset,comment=struct.unpack_from('<4s4H2LH',suffix,offset)
    if disk or central_disk or disk_count!=count or count==65535:raise ValueError('Multidisk/ZIP64 profile unsupported')
    if offset+22+comment!=len(suffix):raise ValueError('EOCD trailing layout')
    if central_size>16*1024**2 or central_offset+central_size>bounds[2]:raise ValueError('Central directory capacity')
    central,cbounds=request_range(url,central_offset,central_offset+central_size-1,bounds[2])
    rows=[];cursor=0
    for _ in range(count):
        fields=struct.unpack_from('<4s6H3L5H2L',central,cursor)
        if fields[0]!=b'PK\x01\x02':raise ValueError('Central signature')
        flags,method,crc,compressed,plain=fields[3],fields[4],fields[7],fields[8],fields[9]
        name_size,extra_size,comment_size=fields[10:13]
        name=central[cursor+46:cursor+46+name_size].decode('utf-8' if flags&2048 else 'cp437')
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:raise ValueError('Unsafe member name')
        rows.append(dict(name=name,crc32=f'{crc:08x}',compressed_bytes=compressed,bytes=plain,
                         local_header_offset=fields[16],compression=method,encrypted=bool(flags&1)))
        cursor+=46+name_size+extra_size+comment_size
    if cursor!=len(central):raise ValueError('Central member boundary')
    candidates={label:[r for r in sorted(rows,key=lambda r:r['name']) if PurePosixPath(r['name']).name.startswith(code) and r['name'].endswith('.mpg')][:16]
                for label,code in [('bin','b'),('set','s')]}
    return dict(url=url,archive_bytes=bounds[2],suffix_range=list(bounds),central_range=list(cbounds),
                suffix_sha256=hashlib.sha256(suffix).hexdigest(),central_sha256=hashlib.sha256(central).hexdigest(),
                member_count=count,metadata_bytes_downloaded=len(suffix)+len(central),members=rows,
                registered_train_speaker1_candidates=candidates,media_members_downloaded=0,
                scope='ZIP directory metadata only; no member payload extraction or modality/model qualification')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    result=inspect(args.url)
    with args.out.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['members','registered_train_speaker1_candidates']},sort_keys=True))
