"""Train the qualified native literal model with the original CPU panel's normal entry point."""
import argparse
from pathlib import Path
from native import Classifier,enable,library
import train

def native_model(arm):
    return enable(Classifier(arm))
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('data',type=Path);ap.add_argument('runs',type=Path)
    ap.add_argument('--rungs',type=int,nargs='+',default=train.RUNGS);a=ap.parse_args()
    library();train.Classifier=native_model;train.panel(a.data,a.runs,a.rungs,train.SEEDS,('literal',))
