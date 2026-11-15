"""Recompute every stored candidate value against independent and old originals."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):
    data=Path(path).read_bytes()
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--original-root',type=Path,required=True)
    parser.add_argument('--independent-rows',type=Path,required=True)
    parser.add_argument('--independent-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    paths=[args.candidate,args.original_root/'SUMMARY.json',args.independent_rows,args.independent_report,Path(__file__)]
    before={str(path):digest(path) for path in paths}
    raw=np.load(args.candidate,allow_pickle=False)['rows']
    independent=np.load(args.independent_rows,allow_pickle=False)
    rows,files=independent['rows'],independent['filenames']
    report=json.loads(args.independent_report.read_bytes())
    if digest(args.independent_rows)!=report['array'] or raw.shape!=(43008,12) or rows.shape!=(43008,5):
        raise ValueError('independent identity or complete raw row count differs')
    if not np.isfinite(raw).all() or not np.isfinite(rows).all():
        raise ValueError('nonfinite raw values')
    lookup={(str(file),int(row[0]),int(row[1])):row for file,row in zip(files,rows)}
    if len(lookup)!=43008:
        raise ValueError('duplicate independent visit/grid identity')
    source=json.loads((args.original_root/'SUMMARY.json').read_bytes())
    filemap,old_rows={},{}
    for index,arm in enumerate(source['arms']):
        filemap[index]=arm['derived_trace_file']
        path=args.original_root/arm['raw_audit_file']
        actual=digest(path)
        if actual['sha256']!=arm['raw_audit_sha256']:
            raise ValueError('old audit identity differs')
        before[str(path)]=actual
        for row in json.loads(path.read_bytes())['visits']:
            old_rows[index,row['index']]=row
    maximum=np.zeros(5)
    seen=set()
    for row in raw:
        arm,index,n=map(int,[row[0],row[1],row[4]])
        key=(filemap[arm],n,index)
        if key in seen:raise ValueError('duplicate candidate visit/grid identity')
        seen.add(key)
        independent_row=lookup[key]
        old=old_rows[arm,index]
        if row[2]!=old['update_index']:
            raise ValueError('old update index differs')
        differences=[abs(row[5]-independent_row[2]),abs(row[6]-independent_row[3]),
                     abs(row[7]-independent_row[4]),abs(row[6]-old['continuum_value'][0]),
                     abs(row[11]-old['maximum_scaled_value_error'])]
        maximum=np.maximum(maximum,differences)
    if set(lookup)!=seen or max(maximum[:3])>1e-11 or max(maximum[3:])!=0:
        raise ValueError('full raw arithmetic or old-reference agreement failed')
    after={str(path):digest(path) for path in map(Path,before)}
    if before!=after:raise ValueError('source/evidence changed')
    result={'schema':'hcsn-independent-fullraw-crosscheck-v2','rows_checked':len(seen),
            'maximum_abs_differences':dict(zip(['candidate','halfline','finite','original80','old_error'],maximum.tolist())),
            'input_identities':before,'inputs_unchanged':True,'scientific_admission':'HOLD_NO_GO'}
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
