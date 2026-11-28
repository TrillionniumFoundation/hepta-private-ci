"""Score each prespecified source seal as soon as the external corpus and original fits are complete."""
import fcntl
from pathlib import Path
import subprocess
import sys
import time


def main(root):
    base=root.parent
    source=base/"hcsn-cremad-e0bf-20261127"
    study=base/"hcsn-sustained-1140569"
    analytic=base/"hcsn-analytic-encoder-1140569"
    ready={"full":study/"whole_edit/terminal.json","analytic":analytic/"run/terminal.json","sustained":study/"run/terminal.json"}
    with (root/"score-controller.lock").open("a") as run:
        fcntl.flock(run,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while ready:
            if (root/"prepared.json").is_file():
                for kind,seal in list(ready.items()):
                    if not seal.exists():continue
                    folder=root/("scores-"+kind)
                    subprocess.run([sys.executable,"-u",str(root/"score.py"),str(root),str(source),str(study),str(analytic),kind],check=True)
                    if not (folder/"terminal.json").exists():raise ValueError("missing terminal")
                    del ready[kind]
            if ready:time.sleep(40)

if __name__=="__main__":main(Path(sys.argv[1]).resolve())
