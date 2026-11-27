"""Fetch only immutable, public source inputs and check SHA-256 before replacing a local file."""
import argparse, concurrent.futures, hashlib, os, tempfile, time, urllib.request
from pathlib import Path

AUTHOR="https://raw.githubusercontent.com/201528014227051/RSICD_optimal/fc33b4555e4baa4d2f05ff0449479c89da2eeac2/"
REPACK="https://huggingface.co/datasets/arampacha/rsicd/resolve/820466c8716e3ccdacde5cb2eb15a2f0f11ccdfe/data/"
FILES={"original.json":(AUTHOR+"dataset_rsicd.json","5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede"),
       "classes.rar":(AUTHOR+"txtclasses_rsicd.rar","0ce6663c67e9e9301511e0719ce93108aa45fb8468dd174c446d5ab733975b99"),
       "train.parquet":(REPACK+"train-00000-of-00001.parquet?download=true","637ce48273746c9a9bc7ea65f84bdcc0173257243f5ab6ae3258e013b58f8310"),
       "valid.parquet":(REPACK+"valid-00000-of-00001.parquet?download=true","06ef6d6a455a0c80667e93e490a0e9603ded172c45106c67bcaa4997fa865b91"),
       "test.parquet":(REPACK+"test-00000-of-00001.parquet?download=true","e707fd90b59fe22a9a222d48b969226715f3eccf78e2b0f382f0a5565a98acda")}
def digest(f):
    with f.open('rb') as h:return hashlib.file_digest(h,'sha256').hexdigest()
def fetch(out,name):
    path=out/name;url,expected=FILES[name]
    if path.is_file() and digest(path)==expected:return name,'verified_existing'
    error=None
    for attempt in range(3):
        tmp=None
        try:
            with tempfile.NamedTemporaryFile(dir=out,delete=False) as f:
                tmp=Path(f.name)
                with urllib.request.urlopen(url,timeout=90) as r:
                    while data:=r.read(1<<20):f.write(data)
            if digest(tmp)!=expected:raise IOError("download checksum does not match "+name)
            tmp.replace(path);return name,'downloaded'
        except (OSError,ValueError) as ex:
            error=ex
            if tmp:tmp.unlink(missing_ok=True)
    raise RuntimeError(f"three unsuccessful attempts to acquire {name}") from error
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);out=p.parse_args().out;out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(lambda n:fetch(out,n),FILES):print(result,flush=True)
    print('acquire_and_verify_seconds',time.monotonic()-start)
