"""Focused path, collision, length and nested-output materializer checks."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def item(name,data,**extra):
    return {'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),**extra}


def run(output):
    if output.exists():
        raise ValueError('Receipt is create-only')
    helper=Path(__file__).with_name('prepare_workspace.py')
    raw=b'finite evidence\n';packed=gzip.compress(raw,mtime=0)
    normal=item('nested/data.json.gz',packed,uncompressed_file='expanded/data.json',
                uncompressed_sha256=hashlib.sha256(raw).hexdigest(),uncompressed_bytes=len(raw))
    variants=[('nested_success',[normal],None),
              ('absolute',[item('/escape',raw)],'Unsafe manifest path'),
              ('parent_traversal',[item('../escape',raw)],'Unsafe manifest path'),
              ('windows_drive',[item('C:/escape',raw)],'Unsafe manifest path'),
              ('duplicate_file',[item('a',raw),item('a',raw)],'Duplicate output'),
              ('duplicate_decoded',[normal,item('expanded/data.json',raw)],'Duplicate output'),
              ('reserved_manifest',[item('BUNDLE_MANIFEST.json',raw)],'manifest is reserved'),
              ('decoded_traversal',[{**normal,'uncompressed_file':'../escape'}],'Unsafe manifest path'),
              ('file_directory_collision',[item('expanded',raw),normal],'File/directory output collision'),
              ('stored_length',[{**normal,'bytes':len(packed)+1}],'Stored artifact length mismatch'),
              ('decoded_length',[{**normal,'uncompressed_bytes':len(raw)+1}],'Uncompressed artifact length mismatch'),
              ('source_symlink',[item('outside-link',raw)],'Source file escapes'),
              ('existing_destination',[normal],'new directory outside'),
              ('inside_source_destination',[normal],'new directory outside')]
    rows=[]
    with tempfile.TemporaryDirectory(prefix='hcsn-r16-materializer-') as temporary:
        base=Path(temporary)
        for index,(name,entries,expected_error) in enumerate(variants):
            case=base/str(index);source=case/'source';source.mkdir(parents=True)
            shutil.copyfile(helper,source/helper.name)
            for filename,data in [('nested/data.json.gz',packed),('expanded/data.json',raw),('a',raw)]:
                target=source/filename;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            if name=='file_directory_collision':
                shutil.rmtree(source/'expanded');(source/'expanded').write_bytes(raw)
            if name=='source_symlink':
                (case/'outside').write_bytes(raw);(source/'outside-link').symlink_to(case/'outside')
            (source/'BUNDLE_MANIFEST.json').write_text(json.dumps({'files':entries}))
            destination=source/'new-output' if name=='inside_source_destination' else case/'output'
            if name=='existing_destination':destination.mkdir()
            process=subprocess.run([sys.executable,'-B',str(source/helper.name),'--destination',str(destination)],
                                   capture_output=True,text=True,check=False)
            if expected_error is None:
                passed=process.returncode==0 and (destination/'expanded/data.json').read_bytes()==raw
            else:
                passed=process.returncode!=0 and expected_error in process.stderr
                if name!='existing_destination':passed=passed and not destination.exists()
            rows.append({'case':name,'passed':passed,'returncode':process.returncode,'expected_error':expected_error})
    receipt={'schema':'hcsn.r16.bundle-materializer-safety.v1','helper_sha256':hashlib.sha256(helper.read_bytes()).hexdigest(),
             'checks':len(rows),'all_passed':all(r['passed'] for r in rows),'rows':rows,
             'scope':'Packaging helper only; financial candidate, protocol and numerical evidence are unchanged.'}
    encoded=json.dumps(receipt,indent=2)+'\n'
    with output.open('x') as handle:handle.write(encoded)
    print(json.dumps({k:v for k,v in receipt.items() if k!='rows'}))
    if not receipt['all_passed']:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
