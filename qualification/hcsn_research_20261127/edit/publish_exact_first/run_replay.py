"""Follow both model/prediction seals, then run paired cold verification once."""
import os, subprocess, sys, time
from pathlib import Path
p=Path(__file__).resolve().parent
r=p.parent
for stage,name in [('first','direct'),('second','secant')]:
    for seed in (107,211,431):
        while not (r/stage/str(seed)/name/'test.json').exists():time.sleep(5)
        marker=p/'results'/str(seed)/(stage+'-replay.json')
        if marker.exists():continue
        subprocess.run([sys.executable,str(p/'replay.py'),'--seed',str(seed),'--stage',stage,
             '--input',str(r/'input'),'--command-data',str(r/'input'/'command'),'--parents','/tmp/hcsn-audit-c889/nobp',
             '--prior',str(r/'first'),'--second',str(r/'second'),'--output',str(p/'results')],check=True)
