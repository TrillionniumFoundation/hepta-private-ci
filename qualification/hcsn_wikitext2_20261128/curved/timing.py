import json
from pathlib import Path
from curvemodel import CurveLM,HERE
from benchmark import run
if __name__=='__main__':
    (HERE/'benchmark.json').write_text(json.dumps(run(HERE.parent,8,CurveLM,['hxcurve','bilinear','smoothwall']),indent=2)+'\n')
