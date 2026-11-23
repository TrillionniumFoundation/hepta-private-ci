"""Reproduce the stored model, panel, primary actions and complete file outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import zipfile

import numpy as np

import cell
import panel
import score
from source_fetch import Prose

ROOT = Path(__file__).resolve().parent
RESULT = ROOT/"result"


def require(ok, why):
    if not ok:
        raise ValueError(why)


def network_worker(script, *args):
    # Launch a fresh namespace before Python starts. Hosted Linux uses sudo to
    # create a network namespace when unprivileged user namespaces are limited.
    cmd = ["unshare","-Urn"] if os.environ.get("HEPTA_CI_NET")!="sudo" else ["sudo","unshare","--net","--"]
    subprocess.run(cmd+["env","OPENBLAS_NUM_THREADS=1","OMP_NUM_THREADS=1",sys.executable,str(ROOT/script)]+
                   list(map(str,args)),check=True)


def load_prompt(given, output):
    if given:
        data=given.read_bytes()
    else:
        import gzip
        url="https://api.stackexchange.com/2.3/questions/18205390?site=stackoverflow&filter=withbody"
        with urlopen(Request(url,headers={"User-Agent":"Hepta-public-research-readback/1.0"}), timeout=30) as r:
            raw=r.read()
        if raw.startswith(b"\x1f\x8b"):
            raw=gzip.decompress(raw)
        item,=json.loads(raw)["items"]
        info=cell.read(RESULT/"external/selection.json")
        record=next(row for row in info["eligibility"] if row["id"]=="18205390")
        require(hashlib.sha256(item["body"].encode()).hexdigest()==record["body_sha256"],"External edit")
        prose=Prose()
        prose.feed(item["body"])
        query=prose.paragraphs()[info["passage_index"]]
        require(hashlib.sha256(query.encode()).hexdigest()==info["passage_sha256"],"Scored passage changed")
        data=(json.dumps([{"id":"18205390","query":query}],indent=2,sort_keys=True)+"\n").encode()
    output.write_bytes(data)
    require(cell.file_sha(output)==cell.read(RESULT/"external/commitment.json")["prompts"],"Wrong original text")


def main(previous, given, retain):
    lock=cell.read(RESULT/"freeze.json")
    for name,digest in lock["source"].items():
        require(cell.file_sha(ROOT/name)==digest,name)
    require(cell.file_sha(RESULT/"model.json")==lock["model"],"Wrong model bytes")
    require(cell.file_sha(previous/"episode.py")==lock["external_evaluator"],"Wrong original scorer")
    model=cell.read(RESULT/"model.json")
    with tempfile.TemporaryDirectory() as td:
        work=Path(td)
        archive=work/"models.zip"
        if (previous/"models.zip").is_file():
            archive.write_bytes((previous/"models.zip").read_bytes())
        else:
            archive.write_bytes(b"".join((previous/("models.zip.part"+str(i))).read_bytes() for i in (1,2)))
        cell.fit(archive,work/"refit.json",work/"times.json")
        repeated=cell.read(work/"refit.json")
        for key in model:
            if key=="weights":
                for arm, matrix in model[key].items():
                    np.testing.assert_allclose(repeated[key][arm],matrix,atol=1e-8,rtol=0)
            else:
                require(model[key]==repeated[key],key)
        c=cell.read(RESULT/"panel/commitment.json")
        p,g=panel.draw(c["seed"],cell.read(previous/"panel.json"))
        require(p==cell.read(RESULT/"panel/prompts.json") and g==cell.read(RESULT/"panel/gold.json"),"Panel changed")
        for group in ("generated","external"):
            dest=work/group
            dest.mkdir()
            if group=="external":
                source=RESULT/"external"
                pp=dest/"prompts.json"
                load_prompt(given,pp)
                zipped=source/"workers.zip"
            else:
                source=RESULT/"panel"
                pp=source/"prompts.json"
                zipped=RESULT/"workers.zip"
            with zipfile.ZipFile(zipped) as z:
                for arm in cell.ARMS:
                    network_worker("worker.py",arm,RESULT/"model.json",pp,source/"commitment.json",dest/(arm+".json"))
                    cold=cell.read(dest/(arm+".json"))
                    orig=json.loads(z.read(arm+".json"))
                    for k in ("arm","model","prompts","predictions","net_before","net_after"):
                        require(cold[k]==orig[k],f"{group} {arm} {k}")
            if group=="generated":
                require(score.scoring(previous/"episode.py",dest,source)==cell.read(RESULT/"scores.json"),"Primary score")
        # These two comparisons include full file writes and an independent
        # line-by-line scan on all 25 requests, on the original archived weights.
        for arm in ("direct","rule"):
            report=work/("stream-"+arm+".json")
            network_worker("stream_check.py",arm,RESULT/"stream-panel.json",work/"external/prompts.json",
                           RESULT/"model.json",work/("files-"+arm),report)
            expected=cell.read(RESULT/report.name)
            observed=cell.read(report)
            require(observed["controls"]==expected["controls"],"File controls")
            for actual, old in zip(observed["cases"],expected["cases"],strict=True):
                require(actual["receipt"]==old["receipt"] and actual["validation"]["verified"],"File readback")
            if arm=="direct" and retain is not None:
                with (work/"files-direct"/"0"/"Blank.txt").open("rb") as src, retain.open("xb") as dst:
                    shutil.copyfileobj(src,dst)
                require(cell.file_sha(retain)==observed["cases"][0]["receipt"]["sha256"], "Archived payload")
            print(arm, observed["cases"][0]["receipt"],flush=True)
    print("Verified 7 x 132 generated-panel responses, 7 initial public responses, 50 file deliveries and 6 rejection controls.")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("previous",type=Path)
    parser.add_argument("--original-prompts",type=Path)
    parser.add_argument("--retain-known",type=Path)
    args=parser.parse_args()
    main(args.previous.resolve(), args.original_prompts, args.retain_known)
