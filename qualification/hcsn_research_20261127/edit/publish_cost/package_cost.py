"""Package six audited searches and score replays under the fixed-cost protocol."""
import json,sys
from pathlib import Path
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent))
from finalize import copy_file,split_zip,sha
def main():
    src=D/'cost-results';dest=D.parent/'publish_cost';dest.mkdir(exist_ok=True)
    doc=json.loads((src/'results.json').read_text())
    for r in doc['rows']:
        assert r['gate'] and sum(r['class_disagreements'].values())==0
    for n in ('cost.py','run_cost.py','COST_PROTOCOL.md','exact.py','package_cost.py'):copy_file(D/n,dest/n)
    for n in ('results.json','seal.json'):copy_file(src/n,dest/n)
    chunks=split_zip(src,[p for p in src.rglob('*') if p.is_file() and p.name not in ('results.json','seal.json')],dest)
    (dest/'evidence.json').write_text(json.dumps(dict(archives=chunks,sha256=sha(dest/'results.json')),indent=2)+'\n')
    print(sha(dest/'results.json'),len(chunks))
if __name__=='__main__':main()
