"""Use the unchanged WikiText optimizer, exposure clock and official-split scorer."""
import argparse
from pathlib import Path
from curvemodel import CurveLM
import train

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path)
    p.add_argument('kind',choices=('hxcurve','bilinear','smoothwall'));p.add_argument('seed',type=int)
    p.add_argument('--epochs',type=int,default=2);p.add_argument('--threads',type=int,default=1)
    p.add_argument('--device',default='cpu');p.add_argument('--batch',type=int,default=32);p.add_argument('--smoke',type=int)
    args=p.parse_args();root=args.root.resolve();trial=root/'curved';trial.mkdir(exist_ok=True)
    for f in ('data.json','train.npy','valid.npy','test.npy'):
        dest=trial/f
        if not dest.exists():dest.symlink_to(root/f)
    args.root=trial;train.LanguageModel=CurveLM;train.run(args)
