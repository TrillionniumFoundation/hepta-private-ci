"""Cross-index content-screen hits against every version under a topic-named path."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import sqlite3
import zipfile

def main(index, dbpath, output):
    with zipfile.ZipFile(index) as f:
        path_rows=f.read('hcsn-path-versions.tsv').decode().splitlines()[1:]
        prior={oid for row in path_rows for oid in row.split('\t')[2].split(',')}
    con=sqlite3.connect(dbpath)
    flags=collections.Counter()
    citations=collections.Counter()
    candidates=[]
    all_out=0
    with gzip.open(output/'non_topic_fulltext_hits.tsv.gz','wt') as evidence:
        evidence.write('blob\texample_path\tbytes\tmarker_flags\n')
        for oid,path,n,mask in con.execute('select oid,path,size,flags from files order by oid'):
            if oid in prior:continue
            all_out+=1
            h,fin,bound,hit,neuron,renewal,edit,multi,speed=[bool(mask&(1<<k)) for k in range(9)]
            if h or fin or (bound and edit and neuron):
                evidence.write(f'{oid}\t{path}\t{n}\t{mask}\n')
            for name,qualifies in [('mentions_hcsn',h),('mentions_finance',fin),('both',h and fin)]:
                if qualifies:flags[name]+=1
            if (fin and (h or bound or hit)) or (bound and edit and neuron):
                candidates.append(dict(oid=oid,path=path,bytes=n,marker_flags=mask))
                citations[path.split('/')[0]]+=1
    info=dict(initial_named_path_blobs=len(prior),checked_without_topic_path=all_out,marker_counts=flags,
              prioritized_objects=len(candidates),prioritized_bytes=sum(i['bytes'] for i in candidates),
              by_first_directory=citations,candidates=candidates)
    (output/'offpath.json').write_text(json.dumps(info,indent=2,ensure_ascii=False)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ['index','db','output']:parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();main(args.index,args.db,args.output)
