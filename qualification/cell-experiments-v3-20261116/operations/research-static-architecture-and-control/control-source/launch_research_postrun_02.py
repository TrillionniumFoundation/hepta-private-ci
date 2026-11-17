import argparse,os,shlex
parser=argparse.ArgumentParser();parser.add_argument("--freeze-sha256",required=True);args=parser.parse_args()
assert len(args.freeze_sha256)==64 and all(c in "0123456789abcdef" for c in args.freeze_sha256)
remote="import hashlib,json,os,pathlib,sys\nw=pathlib.Path(\"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a\");p=\"/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python\"\nexpected=sys.argv[1];raw=(w/\"operations/RESEARCH_POSTRUN_LAUNCH_FREEZE_02.json\").read_bytes()\nassert hashlib.sha256(raw).hexdigest()==expected\nf=json.loads(raw);os.environ.update(f[\"environment\"])\nos.execv(p,[p,\"-I\",\"-B\",str(w/\"operations/launch_qwen_research_owned_v1_02.py\"),\"--role\",\"postrun\",\"--freeze-sha256\",expected])\n"
argv=["/usr/bin/ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=15","desktop-ts","/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python -I -B -c "+shlex.quote(remote)+" "+shlex.quote(args.freeze_sha256)]
os.execv(argv[0],argv)
