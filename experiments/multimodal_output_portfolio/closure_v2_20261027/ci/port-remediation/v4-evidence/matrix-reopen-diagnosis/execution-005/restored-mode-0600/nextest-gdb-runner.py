#!/usr/bin/python3
import os, sys
if "--list" in sys.argv[1:]:
    os.execv(sys.argv[1], sys.argv[1:])
os.execv("/usr/bin/gdb", ["gdb", "--readnever", "-q", "-nx", "-batch", "-x", '/workspace/scratch/95988d8d3ab1/ndu-matrix-reopen-diagnosis-v4-001/execution-005/restored-mode-0600/observe-error-branch.gdb', "--args", *sys.argv[1:]])
