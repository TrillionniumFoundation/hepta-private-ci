#!/usr/bin/env python3
"""Check bytes and optional original notebook extraction, without executing source."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if sys.flags.optimize:
    raise SystemExit('optimized verification refused')

def require(value,message):
    if not value:raise ValueError(message)

def fp(raw):
    return {'git_blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
            'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

def pairs(items):
    result={}
    for key,value in items:
        require(key not in result,'duplicate JSON key')
        result[key]=value
    return result

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--original-notebooks',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parent
manifest=json.loads((root/'SOURCE_MANIFEST.json').read_bytes(),object_pairs_hook=pairs)
seen=set();byte_count=0;extractions=0;parents={}
require(manifest['frozen_candidate_count']==6116 and manifest['formal_verified_count_unchanged']==5887,'frozen count changed')
for row in manifest['objects']:
    sha=row['git_blob_sha'];rel=row['relative_path']
    require(re.fullmatch(r'objects/[0-9a-f]{40}\.py',rel) and rel=='objects/'+sha+'.py','invalid projection path')
    require(sha not in seen,'duplicate object')
    seen.add(sha)
    raw=(root/rel).read_bytes()
    require(fp(raw)=={k:row[k] for k in ('git_blob_sha','sha256','bytes')},'source fingerprint mismatch')
    byte_count+=len(raw)
    if args.original_notebooks:
        for source in row['occurrences']:
            parent=source['parent_notebook'];p_sha=parent['git_blob_sha']
            require(re.fullmatch(r'[0-9a-f]{40}',p_sha),'invalid notebook identity')
            if p_sha not in parents:
                path=args.original_notebooks/(p_sha+'.ipynb')
                require(path.stat().st_size<=2*1024*1024,'notebook bound exceeded')
                original=path.read_bytes()
                require(fp(original)==parent,'parent notebook fingerprint mismatch')
                doc=json.loads(original.decode('utf-8'),object_pairs_hook=pairs)
                require(doc['nbformat']==4 and isinstance(doc['cells'],list),'invalid notebook')
                parents[p_sha]=doc
            cells=parents[p_sha]['cells'];index=source['cell_index']
            require(type(index) is int and 0<=index<len(cells),'invalid code-cell index')
            require(source['json_pointer']==f'/cells/{index}/source','inconsistent JSON pointer')
            cell=cells[index]
            require(cell['cell_type']=='code','not a code cell')
            value=cell['source']
            require(isinstance(value,str) or isinstance(value,list) and all(isinstance(s,str) for s in value),'invalid source type')
            text=value if isinstance(value,str) else ''.join(value)
            require(text.encode('utf-8')==raw,'cell extraction byte mismatch')
            extractions+=1
require(len(seen)==manifest['additional_code_object_count'] and byte_count==manifest['additional_code_bytes'],'manifest count mismatch')
print(json.dumps({'byte_verified_objects':len(seen),'bytes':byte_count,
                  'original_parent_extractions_checked':extractions,
                  'original_parents_read':len(parents),'preserved_source_executed':False,
                  'new_frozen_candidates_counted':0,'notebook_outputs_preserved':False}))
