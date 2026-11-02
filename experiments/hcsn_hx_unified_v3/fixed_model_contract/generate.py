"""Explicit research CLI: validate a registered bundle before any output write."""
import argparse,json
from contract import emit,verify_runtime
parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args()
emit(args.directory);print(json.dumps(verify_runtime(args.directory),indent=2))
