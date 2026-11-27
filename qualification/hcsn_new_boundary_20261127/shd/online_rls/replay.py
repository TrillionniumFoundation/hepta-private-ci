"""Run the same sealed sources in the repository's published sibling-directory layout."""
import argparse,sys
from pathlib import Path
root=Path(__file__).resolve().parent;cross=root.parent/'cross_source'
if not cross.exists():cross=root.parent/'multilingual'
sys.path.insert(0,str(cross))
import online
online.CROSS=cross
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['score','diagnose','gradient','fit']);p.add_argument('--seed',type=int);p.add_argument('--arm');a=p.parse_args()
 if a.mode=='score':
  import score_online;score_online.main()
 elif a.mode=='gradient':
  import gradient_check;gradient_check.main()
 elif a.mode=='diagnose':
  import diagnostics;diagnostics.main()
 else:online.main(a.seed,a.arm)
