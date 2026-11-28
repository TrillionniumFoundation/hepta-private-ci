"""Resume an interrupted owned study and independently verify and publish its terminal evidence."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from archive_followups import prepare


def active(root):
    entry = str(root / "epoch.py").encode()
    for spec in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            words=spec.read_bytes().split(b"\0")
        except (PermissionError,FileNotFoundError,ProcessLookupError):
            continue
        if entry in words:
            return True
    return False


def main(root,source):
    out=root/"run"
    out.mkdir(exist_ok=True,parents=True)
    with (root/"terminal-watcher.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        retries=0
        while not (out/"terminal.json").is_file():
            if active(root):
                time.sleep(45)
                continue
            if retries>=4:
                raise RuntimeError("four failed native recoveries; see original step and host logs")
            retries+=1
            print("recover",retries,flush=True)
            proc=subprocess.run([sys.executable,"-u",str(root/"epoch.py"),str(source),str(out)])
            print("recovery exit",proc.returncode,flush=True)
            time.sleep(5)
        subprocess.run([sys.executable,"-u",str(root/"verify.py"),str(source),str(out)],check=True)
        prepare(out,"billion_epoch",root/"archives/billion_epoch")


if __name__=="__main__":
    main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
