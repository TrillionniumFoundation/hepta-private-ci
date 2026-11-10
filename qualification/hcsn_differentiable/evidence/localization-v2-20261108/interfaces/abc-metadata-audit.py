import csv, hashlib, io, json
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile
archive=Path('/home/qian-qi/hepta-hcsn-math-closure-20261108-v1/final-native/localization/official-localization.zip')
output=Path('/home/qian-qi/hepta-hcsn-localization-v2-20261108-v1/interface-001-audit/abc-gap-audit.json')
zip_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
assert zip_sha=='6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da'
with ZipFile(archive) as z: raw=z.read('ConfLongDemo_JSI.txt')
data_sha=hashlib.sha256(raw).hexdigest()
assert data_sha=='1fbc965b8d7faf499ea854428b2138132d94e6a26404bc8e4b0c62144f513e8a'
groups=defaultdict(list)
for line,row in enumerate(csv.reader(io.StringIO(raw.decode('utf-8'))),1):
    if row: groups[row[0]].append((int(row[2]),line,row[7]))
assert len(groups)==25 and sum(map(len,groups.values()))==164860
seqs={}
for seq,rows in sorted(groups.items()):
    rows.sort(key=lambda row:(row[0],row[1]))
    pairs=[(b[0]-a[0],a[1],b[1]) for a,b in zip(rows,rows[1:])]
    gap,lo,hi=max(pairs)
    seqs[seq]={'events':len(rows),'max_gap_ticks':gap,'max_gap_seconds':gap/10000000,'source_rows_at_max':[lo,hi]}
abc=max((v['max_gap_ticks'],k) for k,v in seqs.items() if k[0] in 'ABC')
selected={}
for seq,n in [('A01',128),('D01',64)]:
    rows=groups[seq][:n]
    selected[seq]={'events':len(rows),'class_count':len({r[2] for r in rows}),'label_counts':dict(Counter(r[2] for r in rows)),'source_rows':[r[1] for r in rows]}
result={'schema':'localization-v2-postselection-time-domain-audit-v1','archive_sha256':zip_sha,'data_sha256':data_sha,'sequence_gaps':seqs,'abc_max_gap_ticks':abc[0],'abc_max_gap_seconds':abc[0]/10000000,'abc_sequence_at_max':abc[1],'abc_all_gaps_leq_point_two':abc[0]<=2000000,'abc_contains_gap_gt_point_one':abc[0]>1000000,'selected_windows':selected,'history':'Post-selection read-only audit. The actual d=0.2 choice followed full-dataset metadata/clock/global-gap inspection, including E; this finding does not rewrite that choice as ABC-only. E supplied no model fitting, tuning or scoring.'}
with output.open('x') as f: f.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'output':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'abc_max_gap_seconds':result['abc_max_gap_seconds'],'abc_sequence_at_max':abc[1],'selected_labels':{k:v['label_counts'] for k,v in selected.items()}}))
