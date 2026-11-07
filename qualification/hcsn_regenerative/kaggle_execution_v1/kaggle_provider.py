"""Pinned installed Kaggle transport, with explicit private account configuration.

This module never reads credentials or changes installed adapter code.  A
submit is issued once by the unique owner; resume/status/wait are observations.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

INSTALLED_SHA256 = {
    "entrypoint": "28aa0010cb460d58310b454b5da05fd6909a2f5188c9fc14961a4f5528d7a695",
    "launcher": "0641706878d7d0886e3dd0ad729e707a664c3f3c36fb62e5d2331193838d552c",
    "cli": "eef3c39de191a06196436ae7278352b31a1ec3fe0a09f5719b55420cdc74fe20",
    "jobs": "8dc1f9f5c7b54ed40a20701fdf299359200b13b5472dcce335afa8fc8ecbd304",
    "transport": "bc167f984034c06b207335ffed742c8ce6f00a8662075e7929475aec9ba94313",
}


class ProviderError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ProviderError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"


def parse(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,"Duplicate JSON key")
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=pairs)
    canonical(value)
    return value


def file_bytes(path, maximum=2*1024**2):
    path=Path(path).absolute()
    require(".." not in path.parts and not any(p.is_symlink() for p in (path,*path.parents)),"Unsafe installed path")
    before=path.lstat()
    version=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=maximum,"Unsafe installed file")
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),"rb") as stream:
        require(version(os.fstat(stream.fileno()))==version(before),"Installed file changed before read")
        raw=stream.read(maximum+1)
    require(len(raw)==before.st_size and version(path.lstat())==version(before),"Installed file changed during read")
    return raw


def validate_installed(provider):
    records=provider["installed_sources"]
    require(set(records)==set(INSTALLED_SHA256),"Complete installed transport pins required")
    for label,expected in INSTALLED_SHA256.items():
        row=records[label]
        require(row.get("sha256")==expected and hashlib.sha256(file_bytes(row["path"])).hexdigest()==expected,
                "Installed transport differs: "+label)
    require(records["entrypoint"]["path"]==provider["entrypoint"],"Installed launcher path differs")
    require(re.fullmatch(r"[A-Za-z0-9_-]+",provider["account_selector"]) is not None,"Invalid explicit account selector")
    require(provider["accelerator"]=="cpu" and provider["timeout_seconds"]==3000
            and provider["internet"] is False and provider["is_private"] is True
            and provider["mode"]=="batch","Frozen CPU provider policy differs")


def exclusive(path, raw):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    require(not any(p.is_symlink() for p in (path,*path.parents)),"Unsafe receipt path")
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),"wb") as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())


class Adapter:
    def __init__(self,config,root):
        self.config,self.root=config,Path(root)
        validate_installed(config["provider"])
        self.base=[config["provider"]["entrypoint"],config["provider"]["account_selector"],"batch"]

    def call(self,operation,args,timeout=150):
        require(operation in {"submit","resume","status","wait","logs","artifacts"},"Operation outside fixed owner contract")
        validate_installed(self.config["provider"])
        started=time.time();monotonic=time.monotonic()
        stem=str(time.time_ns())
        directory=self.root/"adapter-calls"
        record=dict(operation=operation,argv=self.base+[operation]+args,started_unix=started,
                    submission_is_replayed=False,credential_source="Original installed explicit-account launcher only")
        try:
            process=subprocess.run(record["argv"],capture_output=True,timeout=timeout)
            stdout,stderr=process.stdout,process.stderr
            exclusive(directory/(stem+".stdout.bin"),stdout)
            exclusive(directory/(stem+".stderr.bin"),stderr)
            value=parse(stdout)
            record.update(finished_unix=time.time(),measured_wall_seconds=time.monotonic()-monotonic,
                returncode=process.returncode,result=value,stdout_bytes=len(stdout),stderr_bytes=len(stderr),
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                stdout_path=str(directory/(stem+".stdout.bin")),stderr_path=str(directory/(stem+".stderr.bin")))
        except BaseException as error:
            record.update(finished_unix=time.time(),measured_wall_seconds=time.monotonic()-monotonic,
                error_type=type(error).__name__,remote_effect_unknown=operation=="submit")
            if isinstance(error,subprocess.TimeoutExpired):
                for suffix,raw in (("stdout",error.stdout),("stderr",error.stderr)):
                    if raw is not None:
                        exclusive(directory/(stem+".partial-"+suffix+".bin"),raw)
                        record["partial_"+suffix+"_sha256"]=hashlib.sha256(raw).hexdigest()
            exclusive(directory/(stem+".json"),canonical(record))
            raise ProviderError("Adapter unresolved; retain effects and never replay") from error
        exclusive(directory/(stem+".json"),canonical(record))
        require(process.returncode==0 and value.get("ok") is True,"Adapter returned an error; no new submission")
        validate_installed(self.config["provider"])
        return value["result"]
