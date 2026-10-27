"""Fetch bounded exact JPEG members from the official DAVIS archive."""
import argparse
import io
from pathlib import Path
import struct
import time
import urllib.request
import zipfile
import zlib

import numpy as np
from PIL import Image

from .common import read, save, sha


class RangeArchive(io.RawIOBase):
    """Read-only HTTP range source; every request must retain the same ETag."""

    def __init__(self, url, output):
        self.url, self.output, self.position, self.receipts = url, output, 0, []
        output.mkdir(parents=True, exist_ok=False)
        request = urllib.request.Request(url, headers={"Range": "bytes=-131072"})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 206:
                raise ValueError("Server ignored range; full archive download prohibited")
            self.etag = response.headers["ETag"]
            self.length = int(response.headers["Content-Range"].split("/")[1])
            self.tail = response.read(131073)
            if len(self.tail) != 131072:
                raise ValueError("Unexpected archive tail size")
        (output / "TAIL.bin").write_bytes(self.tail)
        self.receipts.append({"range": [self.length - 131072, self.length - 1], "bytes": 131072,
            "sha256": sha(output / "TAIL.bin"), "etag": self.etag, "path": str(output / "TAIL.bin")})

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.length + offset
        if not 0 <= self.position <= self.length:
            raise ValueError("Archive seek outside source")
        return self.position

    def tell(self):
        return self.position

    def read(self, size=-1):
        end = self.length if size < 0 else min(self.length, self.position + size)
        if end - self.position > 4000000:
            raise ValueError("Oversized archive read")
        if self.position >= self.length - len(self.tail):
            result = self.tail[self.position - (self.length - len(self.tail)):end - (self.length - len(self.tail))]
        else:
            request = urllib.request.Request(self.url, headers={"Range": f"bytes={self.position}-{end - 1}", "If-Match": self.etag})
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206 or response.headers.get("ETag") != self.etag:
                    raise ValueError("Archive source identity changed or range ignored")
                expected = f"bytes {self.position}-{end - 1}/{self.length}"
                if response.headers["Content-Range"] != expected:
                    raise ValueError("Unexpected returned range")
                result = response.read(end - self.position + 1)
            if len(result) != end - self.position:
                raise ValueError("Truncated or oversized range response")
            path = self.output / f"range-{self.position}-{end - 1}.bin"
            path.write_bytes(result)
            self.receipts.append({"range": [self.position, end - 1], "bytes": len(result),
                "sha256": sha(path), "etag": self.etag, "path": str(path)})
        self.position = end
        return result


def run(output):
    source = Path(__file__).parent
    protocol = read(source / "VIDEO_PROTOCOL.json")
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    stream = RangeArchive(protocol["archive_url"], output / "range-receipts")
    archive = zipfile.ZipFile(stream)
    entries = [info for info in archive.infolist() if info.filename.startswith("DAVIS/JPEGImages/480p/") and info.filename.endswith(".jpg")]
    directories = sorted({info.filename.split("/")[-2] for info in entries})
    selected, families = [], set()
    for directory in directories:
        family = directory.split("-")[0]
        if family in families:
            continue
        if len([i for i in entries if i.filename.split("/")[-2] == directory]) < 36:
            continue
        selected.append(directory)
        families.add(family)
        if len(selected) == protocol["test_sources"]:
            break
    if len(selected) != protocol["test_sources"]:
        raise ValueError("Insufficient registered independent source families")
    save(output / "SOURCE_SELECTION.json", {"sequences": selected, "all_sequence_names": directories,
        "source_selection_before_frame_decoding": True, "model_output_not_generated": True,
        "archive_bytes": stream.length, "archive_etag": stream.etag, "archive_url": stream.url,
        "whole_archive_sha256_not_obtained": True, "members_pinned_by_crc_and_content_hash": True,
        "protocol_sha256": sha(source / "VIDEO_PROTOCOL.json")})
    files, samples, clips = [], [], []
    for sequence in selected:
        available = sorted([i for i in entries if i.filename.split("/")[-2] == sequence], key=lambda i: i.filename)
        eligible = np.asarray([i for i in range(2, len(available) - 2) if i % 4 in (2, 3)])
        indices = eligible[np.rint(np.linspace(0, len(eligible) - 1, protocol["frames_per_source"])).astype(int)]
        private = set(map(int, indices))
        public = {i + offset for i in private for offset in (-2, 2)}
        if private & public:
            raise ValueError("Cross-example private frame leaks through endpoint")
        paths = {}
        for index in sorted(private | public):
            info = available[index]
            # One bounded range fetch covers header, member name and compressed bytes.
            stream.seek(info.header_offset)
            header = stream.read(30)
            lengths = struct.unpack_from("<HH", header, 26)
            if header[:4] != b"PK\x03\x04":
                raise ValueError("Invalid ZIP member header")
            stream.seek(info.header_offset + 30 + sum(lengths))
            encoded = stream.read(info.compress_size)
            if info.compress_type == zipfile.ZIP_DEFLATED:
                content = zlib.decompress(encoded, -15)
            elif info.compress_type == zipfile.ZIP_STORED:
                content = encoded
            else:
                raise ValueError("Unregistered ZIP compression")
            if len(content) != info.file_size or zlib.crc32(content) != info.CRC:
                raise ValueError("Source member size or CRC mismatch")
            original = output / "original" / sequence / Path(info.filename).name
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(content)
            with Image.open(original) as image:
                image = image.convert("RGB")
                size = (256, round(image.height * 256 / image.width))
                canonical = image.resize(size, Image.Resampling.BOX)
            path = output / "frames" / sequence / f"{index:05d}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            canonical.save(path)
            paths[index] = str(path)
            files.extend([{"path": str(original), "sha256": sha(original), "bytes": original.stat().st_size,
                "zip_member": info.filename, "zip_crc32": info.CRC, "source_index": index, "sequence": sequence},
                {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size,
                "original_sha256": sha(original), "canonical_resize": list(size), "source_index": index,
                "sequence": sequence}])
        for index in indices:
            samples.append({"id": f"{sequence}-{index:05d}", "source": sequence, "role": "test", "target_index": int(index),
                "left": paths[int(index) - 2], "right": paths[int(index) + 2], "private_target": paths[int(index)]})
        clips.append({"source": sequence, "source_family": sequence.split("-")[0],
            "target_indices": sorted(private), "endpoint_indices": sorted(public), "overlap": [],
            "available_source_frames": len(available)})
        save(output / "RANGE_RECEIPTS.json", stream.receipts)
        print({"fetched_sequence": sequence, "canonical_frames": len(paths)}, flush=True)
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.closure-v2.natural.video.assets.v1",
        "protocol_sha256": sha(source / "VIDEO_PROTOCOL.json"), "source_selection": read(output / "SOURCE_SELECTION.json"),
        "files": files, "samples": samples, "clips": clips, "source_preparation_wall_seconds": time.perf_counter() - start,
        "archive_range_download_bytes": sum(r["bytes"] for r in stream.receipts),
        "source_scope": "Original DAVIS natural video frames; independent evaluation clusters are sequence families, not frames"})
    print({"sources": len(clips), "test_samples": len(samples)}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
