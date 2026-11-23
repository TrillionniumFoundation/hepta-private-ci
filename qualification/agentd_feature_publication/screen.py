"""Recheck the 35 exact compiler rows and the twelve fully private donor declarations."""
from pathlib import Path
from hashlib import sha1
from collections import Counter
import json,re,sys
p=Path(__file__).resolve().parent
base,donor=map(Path,sys.argv[1:])
known={'VersionedBootstrap':'separately_qualified','Publication':'qualified_here','Decision':'missing_original_predecessor_citation','AutomationEffectHostFile':'donor_only_v2_full_entry_positive_unverified','ResidentStagesV3':'same_donor_declaration'}
counts=Counter();rows=[]
def blob(b):return sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def decl(text,name):
    m=re.search(r'(?m)^enum '+name+r'\s*\{',text)
    return text[m.start():text.index('\n}',m.end())+2]
for r in json.loads((p/'source.json').read_bytes())['diagnostics']:
    path=Path(r['path']);typ=r['type'];v=r['visibility'];raw=(base/path).read_bytes();lines=raw.decode().splitlines()
    attrs=lines[max(0,r['line']-5):r['line']-1]
    row={'path':r['path'],'line':r['line'],'type':typ,'visibility':v,'source_blob':blob(raw)}
    if v=='private':
        b=(donor/path).read_bytes()
        changed=decl(raw.decode(),typ)!=decl(b.decode(),typ)
        assert changed==(typ!='ResidentStagesV3')
        row.update(donor_blob=blob(b),donor_declaration_changed=changed)
        category=known.get(typ,'boxed_donor_no_individual_qualification')
    elif v=='pub':category='public_declaration_scope_review_required'
    elif any('serde(tag = ' in a for a in attrs) and any('Deserialize' in a and 'Serialize' in a for a in attrs):
        category='scoped_tagged_wire_and_constructor_review_required'
    else:category='scoped_representation_and_consumer_review_required'
    row['category']=category;counts[category]+=1;rows.append(row)
assert len(rows)==35 and sum(counts.values())==35
print(json.dumps({'donor':'24abd04c825cb0d5d0ce27b52ac5008eda13dde4','category_counts':counts,'rows':rows},indent=2,sort_keys=True))
