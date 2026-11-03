#!/usr/bin/env python3
"""Verify exact source bytes and optional original new-file hunks, never apply them."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if sys.flags.optimize:raise SystemExit('optimized verification refused')
from patch_parser import fp, lf_lines, parse_new_file, require

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--original-patches',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parent
manifest=json.loads((root/'SOURCE_MANIFEST.json').read_bytes())
require(manifest['frozen_candidate_count']==6116 and manifest['formal_verified_count_unchanged']==5887,'frozen count changed')
seen=set();parents={};read_bytes=0;extractions=0;source_bytes=0;notices=0
for row in manifest['objects']+manifest['notices']:
    sha=row['git_blob_sha'];rel=row['relative_path']
    require(re.fullmatch(r'(?:objects|notices)/[0-9a-f]{40}\.[a-z0-9]+',rel) and Path(rel).stem==sha,'unsafe/mismatched object path')
    require(sha not in seen,'duplicate object')
    seen.add(sha);raw=(root/rel).read_bytes()
    require(fp(raw)=={k:row[k] for k in ('git_blob_sha','sha256','bytes')},'object bytes differ')
    if row['role']=='auxiliary original third-party notice':notices+=1
    else:source_bytes+=len(raw)
    if args.original_patches:
        for occurrence in row['occurrences']:
            parent=occurrence['parent_patch'];parent_sha=parent['git_blob_sha']
            require(re.fullmatch(r'[0-9a-f]{40}',parent_sha),'invalid original patch identity')
            if parent_sha not in parents:
                path=args.original_patches/(parent_sha+'.patch');remaining=32*1024*1024-read_bytes
                require(path.stat().st_size<=remaining,'original patch read bound exceeded')
                with path.open('rb') as stream:data=stream.read(remaining+1)
                read_bytes+=len(data)
                require(read_bytes<=32*1024*1024,'original patch read bound exceeded by overflow probe')
                require(fp(data)==parent,'original patch fingerprint mismatch')
                lines=lf_lines(data);starts=[i for i,line in enumerate(lines) if line.startswith(b'diff --git ')]
                require(starts and starts[0]==0,'unsupported patch preamble')
                parents[parent_sha]=(lines,starts)
            lines,starts=parents[parent_sha];index=occurrence['diff_index']
            require(type(index) is int and 0<=index<len(starts),'invalid diff index')
            start=starts[index];end=starts[index+1] if index+1<len(starts) else len(lines)
            require(start+1==occurrence['diff_first_line'] and end==occurrence['diff_last_line'],'diff locator changed')
            item,reason=parse_new_file(lines[start:end]);require(item is not None,'not a complete new-file hunk')
            require(item.pop('raw')==raw,'new-file postimage differs')
            for key in ('original_path','original_mode','index_new_blob_prefix','index_prefix_length','declared_new_lines','no_final_newline'):
                require(item[key]==occurrence[key],'extraction metadata differs')
            extractions+=1
require(len(manifest['objects'])==manifest['additional_source_object_count']==30,'source count changed')
require(notices==manifest['auxiliary_notice_count']==3 and source_bytes==manifest['additional_source_bytes'],'notice/byte count changed')
print(json.dumps({'byte_verified_source_objects':30,'byte_verified_notices':notices,'source_bytes':source_bytes,
                  'original_patch_extractions_checked':extractions,'original_patches_read':len(parents),
                  'original_patch_read_bytes':read_bytes,'preserved_source_executed':False,'patch_applied':False,
                  'new_frozen_candidates_counted':0}))
