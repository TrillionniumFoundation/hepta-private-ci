"""Independently validate each complete file, including every line and payload hash."""
import argparse
import hashlib
from pathlib import Path
import random
import secrets
import time

import cell
import stream
from worker import net

FORMS = (
    'From {l} through {u}, put all multiples of {d} in the file named "{f}".',
    'Print multiples of {d} starting at {l} strictly below {u} to the file named "{f}".',
    'Write positive integers divisible by {d} from {l} to {u} to the file called "{f}".',
    'List multiples of {d} below {u} beginning at {l} in the text file named "{f}".',
)


def draw(out):
    seed=secrets.randbits(96)
    rng=random.Random(seed)
    rows=[]
    for i in range(24):
        d,l,u=rng.randint(2,19),rng.randint(1,75),rng.randint(80,230)
        if i%6==0:
            l=d
        if i%8==2:
            u=l-1
        f=f"items{i}.txt"
        rows.append(dict(query=FORMS[i%4].format(d=d,l=l,u=u,f=f),
                         d=d,lo=l,last_allowed=u-(i%2),name=f))
    cell.dump_new(out,dict(seed=seed,operator=cell.file_sha(Path(stream.__file__)),
                          checker=cell.file_sha(Path(__file__)),cases=rows))


def verify(path, d, lo, upper, receipt):
    start=time.perf_counter_ns()
    first=((lo+d-1)//d)*d
    total=max(0,upper//d-(lo-1)//d)
    h=hashlib.sha256()
    length=n=0
    with path.open("rb") as f:
        for line in f:
            expected=first+n*d
            if line != (str(expected)+"\n").encode("ascii"):
                raise ValueError(f"Incorrect file content at record {n}")
            h.update(line)
            length+=len(line)
            n+=1
    if (n,length,h.hexdigest())!=(total,receipt["bytes"],receipt["sha256"]):
        raise ValueError("File count, size or checksum mismatch")
    if receipt["name"]!=path.name or receipt["records"]!=n:
        raise ValueError("Worker receipt mismatch")
    return dict(verified=True,checked_records=n,independent_bytes=length,
                independent_sha256=h.hexdigest(),verification_ns=time.perf_counter_ns()-start)


def run(arm, panel, original_prompt, model, work, out):
    net_before=net()
    cases=cell.read(panel)
    assert cases["operator"]==cell.file_sha(Path(stream.__file__))
    assert cases["checker"]==cell.file_sha(Path(__file__))
    external,=cell.read(original_prompt)
    assert cell.file_sha(original_prompt)=="33ce04404a3c9774c6c135af4afe2a74f0b6e440ebf4b2d0ed10592c746948fd"
    known=dict(query=external["query"],d=99,lo=99,last_allowed=999999999,name="Blank.txt")
    work.mkdir(exist_ok=False)
    results=[]
    for i,row in enumerate([known]+cases["cases"]):
        sample=work/str(i)
        sample.mkdir()
        start=time.perf_counter_ns()
        rec=stream.execute(row["query"],model,arm,sample)
        wall=time.perf_counter_ns()-start
        validation=verify(sample/row["name"],row["d"],row["lo"],row["last_allowed"],rec)
        results.append(dict(id="known" if i==0 else f"new-{i-1:02}",execution_ns=wall,
                            receipt=rec,validation=validation))
    controls={}
    for label,q in (
        ("quota",'List multiples of 2 from 1 to 1000000000 in the file named "limit.txt".'),
        ("leaf",'List multiples of 2 from 1 to 99 in the file named "folder/list.txt".'),
        ("occupied",'List multiples of 2 from 1 to 99 in the file named "used.txt".'),
    ):
        child=work/label
        child.mkdir()
        if label=="occupied":
            (child/"used.txt").write_bytes(b"original\n")
        previous={f.name:f.read_bytes() for f in child.iterdir()}
        try:
            stream.execute(q,model,arm,child)
        except (ValueError,FileExistsError) as e:
            controls[label]=type(e).__name__
        else:
            raise ValueError("Unexpected publication")
        assert previous=={f.name:f.read_bytes() for f in child.iterdir()}
    cell.dump_new(out,dict(arm=arm,net_before=net_before,net_after=net(),cases=results,controls=controls))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("mode",choices=("draw","direct","rule"))
    ap.add_argument("paths",nargs="+",type=Path)
    args=ap.parse_args()
    if args.mode=="draw":
        draw(*args.paths)
    else:
        run(args.mode,*args.paths)
