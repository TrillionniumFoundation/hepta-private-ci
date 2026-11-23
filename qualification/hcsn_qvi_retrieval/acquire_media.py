"""Fetch only prespecified AV speech recordings from the fixed RAVDESS release."""
import argparse
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import struct
import time
import urllib.error
import urllib.request
import zipfile
import zlib


MANIFEST = Path(__file__).with_name("data_manifest.json")


def response_range(url, span):
    request = urllib.request.Request(url + "&hcsn_range=" + span,
                                     headers={"Range": "bytes=" + span,
                                              "User-Agent": "HCSN-RAVDESS-academic/1.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                if response.status != 206:
                    raise ValueError(f"server did not honor byte range {span}")
                interval, total = response.headers["Content-Range"].split(" ")[1].split("/")
                lo, hi = map(int, interval.split("-"))
                size = int(total)
                expected = (max(0,size-int(span[1:])),size-1) if span.startswith("-") else tuple(map(int,span.split("-")))
                if (lo,hi) != expected:
                    raise ValueError("server returned a different range")
                payload = response.read(hi-lo+2)
                if len(payload) != hi-lo+1:
                    raise ValueError("incomplete range")
                return payload, lo
        except (OSError, ValueError) as error:
            if attempt == 4:
                raise
            wait = min(15, 2**attempt)
            if isinstance(error, urllib.error.HTTPError) and error.code == 429:
                wait = max(wait, int(error.headers.get("Retry-After", "15")))
            time.sleep(wait)


def file_names(actor, manifest):
    return [f"01-01-{emo:02d}-01-{statement:02d}-{rep:02d}-{actor:02d}.mp4"
            for emo in manifest["emotion_ids"] for statement in manifest["statement_ids"]
            for rep in manifest["repetition_ids"]]


def local_member(cache, actor, name, url, info, shift, offsets):
    destination = cache / name
    if destination.exists():
        raw = destination.read_bytes()
        if len(raw) == info.file_size and zlib.crc32(raw) == info.CRC:
            return raw
    start = info.header_offset + shift
    end = min(value for value in offsets if value > start) - 1
    data, _ = response_range(url, f"{start}-{end}")
    if data[:4] != b"PK\x03\x04":
        raise ValueError("invalid ZIP local header")
    name_length, extra_length = struct.unpack_from("<HH", data, 26)
    prefix = 30+name_length+extra_length
    if data[30:30+name_length].decode() != info.filename:
        raise ValueError("ZIP local/central names differ")
    packed = data[prefix:prefix + info.compress_size]
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ValueError("unsupported ZIP member compression")
    raw = packed if info.compress_type == zipfile.ZIP_STORED else zlib.decompress(packed, -15)
    if len(raw) != info.file_size or zlib.crc32(raw) != info.CRC:
        raise ValueError("ZIP member CRC or size mismatch")
    temporary = destination.with_suffix(".part")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return raw


def obtain_actor(actor, manifest, cache):
    url = f"https://zenodo.org/records/1188976/files/Video_Speech_Actor_{actor:02d}.zip?download=1"
    tail, shift = response_range(url, "-65536")
    with zipfile.ZipFile(io.BytesIO(tail)) as archive:
        infos = archive.infolist()
        offsets = [item.header_offset+shift for item in infos] + [archive.start_dir+shift]
        by_name = {Path(item.filename).name: item for item in infos if "__MACOSX" not in item.filename}
        rows = []
        for name in file_names(actor, manifest):
            info = by_name[name]
            raw = local_member(cache, actor, name, url, info, shift, offsets)
            rows.append({"recording":name, "actor":actor, "member":info.filename,
                         "zenodo_zip":url,"bytes":len(raw),"crc32":f"{info.CRC:08x}",
                         "sha256":hashlib.sha256(raw).hexdigest()})
    print(f"actor {actor:02d}: {len(rows)} recordings, CRC verified", flush=True)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--workers",type=int,default=3)
    args=parser.parse_args()
    args.cache.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(MANIFEST.read_text())
    actors=sorted(a for group in manifest["splits"].values() for a in group)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(lambda actor: obtain_actor(actor, manifest, args.cache),actors))
    rows=[item for group in results for item in group]
    assert len({r["sha256"] for r in rows})==192
    (args.cache/"recordings.json").write_text(json.dumps(rows,indent=2)+"\n")


if __name__ == "__main__":
    main()
