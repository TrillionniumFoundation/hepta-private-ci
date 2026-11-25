"""Bounded public-data acquisition; never reads model outcomes or fits a model.

Linux preparation receipts include subprocess CPU. Originals and failed attempts
are retained. Official LFS identities are registered before media downloading.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
import traceback
import urllib.request


UPSTREAM = "1658cd342dff90010aa843eaeebd53610a08b1dc"
BASE_COMMIT = "dca9febc8143c682077fe27d40dbeaa1137bcaa4"
TRANSPORT_PATH = "experiments/hcsn_blocker_closure_v1/av/transport_41156412198"
TRANSPORT_BLOB = "e760433f55b8488e78a0ff5b97bc34b0d74cfffc"
CANDIDATES = ("1006", "1007", "1009", "1013", "1017", "1018", "1021", "1028", "1029", "1030", "1033", "1037", "1042", "1045", "1068", "1070", "1071", "1074", "1075", "1079", "1081", "1088", "1090")
SALT = "hcsn-closure-av-confirm-20261125-v1:"
SENTENCES = ("DFA", "IOM", "ITH", "IWL")
EMOTIONS = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")
CAP = 150000000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit+1)
    if len(data) > limit:
        raise ValueError("download exceeded declared size limit")
    return data


def restore(root):
    directory, parts = root/"base", root/"restoration_parts"
    directory.mkdir()
    parts.mkdir()
    base = f"https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/{BASE_COMMIT}/{TRANSPORT_PATH}/"
    raw = fetch(base+"TRANSPORT.json", 65536)
    blob = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    if blob != TRANSPORT_BLOB:
        raise ValueError("committed base data transport identity changed")
    (root/"BASE_TRANSPORT.json").write_bytes(raw)
    wanted = {"train.npz", "validation.npz", "normalization.npz", "DATASET.json", "COHORT_PLAN.json", "CREMA_D_LICENSE.txt"}
    records = [row for row in json.loads(raw)["files"] if row["path"] in wanted]
    if len(records) != len(wanted):
        raise ValueError("base transport lacks selected complete logical files")
    jobs = [part for row in records for part in row["parts"]]

    def part_job(part):
        value = fetch(base+part["path"], part["bytes"])
        if len(value) != part["bytes"] or digest(value) != part["sha256"]:
            raise ValueError("base transport part changed")
        (parts/part["path"]).write_bytes(value)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(part_job, jobs))
    for row in records:
        value = b"".join(base64.b64decode((parts/p["path"]).read_bytes().strip(), validate=True) for p in row["parts"])
        if len(value) != row["bytes"] or digest(value) != row["sha256"]:
            raise ValueError("restored complete base file changed")
        (directory/row["path"]).write_bytes(value)
    save(root/"RESTORATION.json", {"commit": BASE_COMMIT, "transport_blob_sha1": blob,
        "files": records, "scope": "Only these six files restored; original public test arrays deliberately not restored."})


def register(root):
    actors = sorted(CANDIDATES, key=lambda x: digest((SALT+x).encode()))[:8]
    save(root/"ROSTER.json", {"actors": actors, "candidates": list(CANDIDATES), "selection_salt": SALT,
        "exclusion_scope": "Outside three inspected prior actor manifests, 67 unique actors. No global absence-from-every-historical-branch claim.",
        "excluded_manifest_sha256": ["ac896bfb2643f22234c9917794347e2aa443836122b5950541335fdc002e3874", "180d7a90e0a7f8615dcd97c4bf91e5795cbaab1cf7a0f9bfa2fb64fb9d7c510f", "66613756399a66f2f108c27004f548c18788de304ab39d91c99dc8806c235a01"],
        "upstream_commit": UPSTREAM, "sentences": SENTENCES, "emotions": EMOTIONS,
        "clips": 192, "maximum_new_media_download_bytes_including_failed_bytes": CAP})
    upstream = root/"official"
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    with (root/"GIT_METADATA.log").open("x") as log:
        def git(args, **kw):
            subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, env=env, check=True, timeout=180, **kw)
        git(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
             "https://github.com/CheyneyComputerScience/CREMA-D.git", str(upstream)])
        git(["git", "fetch", "--depth", "1", "origin", UPSTREAM], cwd=upstream)
        listing = subprocess.check_output(["git", "ls-tree", "-r", UPSTREAM, "VideoFlash"], cwd=upstream, text=True)
        entries = {Path(line.split("\t", 1)[1]).stem: line for line in listing.splitlines()}
        clips = [f"{a}_{s}_{e}_XX" for a in actors for s in SENTENCES for e in EMOTIONS]
        if len(clips) != 192 or any(clip not in entries for clip in clips):
            raise ValueError("declared fresh actor cohort unavailable")
        paths = [entries[c].split("\t", 1)[1] for c in clips]+["LICENSE.txt"]
        command = ["git", "-c", "filter.lfs.required=false", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process="]
        git(command+["sparse-checkout", "set", "--no-cone", "--stdin"], input="\n".join("/"+p for p in paths)+"\n", text=True, cwd=upstream)
        git(command+["reset", "--hard", UPSTREAM], cwd=upstream)
    rows = []
    for clip in clips:
        metadata, path = entries[clip].split("\t", 1)
        pointer = (upstream/path).read_bytes()
        blob = hashlib.sha1(b"blob "+str(len(pointer)).encode()+b"\0"+pointer).hexdigest()
        if blob != metadata.split()[2]:
            raise ValueError("official Git pointer blob differs")
        fields = dict(line.split(" ", 1) for line in pointer.decode().splitlines())
        if fields["version"] != "https://git-lfs.github.com/spec/v1":
            raise ValueError("expected an LFS pointer")
        actor, sentence, emotion, _ = clip.split("_")
        rows.append({"clip": clip, "actor": actor, "sentence": sentence, "emotion": emotion,
                     "label": EMOTIONS.index(emotion), "git_path": path, "pointer_blob_sha1": blob,
                     "sha256": fields["oid"].split(":")[1], "bytes": int(fields["size"]),
                     "url": f"https://media.githubusercontent.com/media/CheyneyComputerScience/CREMA-D/{UPSTREAM}/{path}"})
    manifest = {"commit": UPSTREAM, "roster_sha256": digest((root/"ROSTER.json").read_bytes()), "records": rows,
                "expected_bytes": sum(row["bytes"] for row in rows), "limit_bytes": CAP,
                "license_database": "ODbL-1.0", "license_contents": "DbCL-1.0"}
    save(root/"MEDIA_MANIFEST.json", manifest)
    (root/"CREMA_D_LICENSE.txt").write_bytes((upstream/"LICENSE.txt").read_bytes())
    if manifest["expected_bytes"] > CAP:
        raise ValueError("registered media exceeds approved budget; no new media downloaded")


def acquire(root):
    rows = json.loads((root/"MEDIA_MANIFEST.json").read_text())["records"]
    directory = root/"media"
    directory.mkdir()
    lock, counter, reserved, attempts = threading.Lock(), [0], [0], []

    def one(row):
        for attempt in range(1, 4):
            begun, error, allowance, received = time.perf_counter(), None, 0, 0
            partial = directory/(row["clip"]+f".attempt{attempt}.partial")
            try:
                with lock:
                    allowance = row["bytes"]+1
                    if counter[0]+reserved[0]+allowance > CAP:
                        allowance = 0
                        raise RuntimeError("insufficient remaining media download budget")
                    reserved[0] += allowance
                with urllib.request.urlopen(row["url"], timeout=60) as response, partial.open("xb") as output:
                    while received < allowance:
                        block = response.read(min(65536, allowance-received))
                        if not block:
                            break
                        received += len(block)
                        output.write(block)
                        if output.tell() > row["bytes"]:
                            raise ValueError("media response exceeds its registered size")
                value = partial.read_bytes()
                if len(value) != row["bytes"] or digest(value) != row["sha256"]:
                    raise ValueError("official LFS media identity failed")
                partial.rename(directory/(row["clip"]+".flv"))
            except Exception:
                error = traceback.format_exc()
            finally:
                with lock:
                    counter[0] += received
                    reserved[0] -= allowance
            receipt = {"clip": row["clip"], "attempt": attempt, "error": error, "bytes_received": received, "wall_seconds": time.perf_counter()-begun}
            with lock:
                attempts.append(receipt)
                save(root/"attempts"/(row["clip"]+f".{attempt}.json"), receipt)
            if error is None:
                return
            if attempt == 3 or counter[0] > CAP:
                raise RuntimeError("media acquisition failed; attempt files retained")
    (root/"attempts").mkdir()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(one, rows))
    finally:
        save(root/"ACQUISITION.json", {"attempts": attempts, "downloaded_bytes_including_failed_attempts": counter[0],
             "manifest_sha256": digest((root/"MEDIA_MANIFEST.json").read_bytes()), "all_verified": len(attempts) >= len(rows) and len(list(directory.glob("*.flv"))) == len(rows)})


def stage(root, name, function):
    wall, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    error = None
    try:
        function(root)
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt = {"stage": name, "error": error, "wall_seconds": time.perf_counter()-wall,
            "parent_cpu_seconds": time.process_time()-cpu,
            "child_cpu_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            "energy_joules": None, "scope": "stage body, including all failed attempts; nested decoder cost is not added twice"}
        save(root/(name.upper()+"_COST.json"), receipt)
        print(json.dumps(receipt), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("restore", "register", "acquire"))
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    stage(args.root, args.action, {"restore": restore, "register": register, "acquire": acquire}[args.action])


if __name__ == "__main__":
    main()
