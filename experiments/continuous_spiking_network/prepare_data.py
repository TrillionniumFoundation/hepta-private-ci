"""Fetch pinned public research sources into an external cache, never the repo."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import urllib.request
import zipfile

from .data import DEFAULT_CACHE, FSDD_COMMIT, prepare_audio_features, sha256


MNIST_MD5 = {
    "train-images-idx3-ubyte.gz": "f68b3c2dcbeaaa9fbdd348bbdeb94873",
    "train-labels-idx1-ubyte.gz": "d53e105ee54ea40749a09fcbcd1e9432",
    "t10k-images-idx3-ubyte.gz": "9fb629c4189551a2d022fa330f9573f3",
    "t10k-labels-idx1-ubyte.gz": "ec29112dd5afa0611ce80d1b7f02629c",
}
FSDD_ARCHIVE_SHA256 = "beaca4fb849cad13103b2cffba913b3d7fdb5f15222da4ddd07187b3c38a757a"


def _download(url, target, expected_md5=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(
            url, headers={"User-Agent": "Hepta-research-dataset-preparation/1.0"}
        )
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        if (
            expected_md5
            and hashlib.md5(temporary.read_bytes()).hexdigest() != expected_md5
        ):
            temporary.unlink()
            raise ValueError(f"Source checksum mismatch for {target.name}.")
        temporary.replace(target)
    if expected_md5 and hashlib.md5(target.read_bytes()).hexdigest() != expected_md5:
        raise ValueError(f"Existing cache checksum mismatch for {target.name}.")
    return {
        "url": url,
        "filename": target.name,
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
        "upstream_md5": expected_md5,
    }


def prepare_sources(cache_dir=DEFAULT_CACHE):
    cache_dir = Path(cache_dir).resolve()
    repository = Path(__file__).resolve().parents[2]
    if cache_dir == repository or repository in cache_dir.parents:
        raise ValueError("Dataset cache must be outside the git repository.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "hcsn-public-sources-v1",
        "mnist": {
            "name": "MNIST",
            "authors": "Yann LeCun, Corinna Cortes, Christopher J.C. Burges",
            "homepage": "http://yann.lecun.com/exdb/mnist/",
            "license": "CC-BY-SA-3.0",
            "license_source": "https://keras.io/api/datasets/mnist/",
            "files": [],
        },
        "fsdd": {
            "name": "Free Spoken Digit Dataset",
            "authors": "Zohar Jackson and FSDD contributors",
            "homepage": "https://github.com/Jakobovski/free-spoken-digit-dataset",
            "commit": FSDD_COMMIT,
            "license": "CC-BY-SA-4.0",
            "license_source": f"https://github.com/Jakobovski/free-spoken-digit-dataset/blob/{FSDD_COMMIT}/README.md#license",
        },
    }
    for filename, digest in MNIST_MD5.items():
        url = f"https://ossci-datasets.s3.amazonaws.com/mnist/{filename}"
        manifest["mnist"]["files"].append(
            _download(url, cache_dir / "mnist" / filename, digest)
        )
    url = f"https://codeload.github.com/Jakobovski/free-spoken-digit-dataset/zip/{FSDD_COMMIT}"
    archive = cache_dir / f"fsdd-{FSDD_COMMIT}.zip"
    manifest["fsdd"]["archive"] = _download(url, archive)
    if manifest["fsdd"]["archive"]["sha256"] != FSDD_ARCHIVE_SHA256:
        raise ValueError(
            "Pinned FSDD archive SHA-256 mismatch; inspect the source before proceeding."
        )
    recordings = cache_dir / "fsdd" / "recordings"
    recordings.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(archive) as handle:
        for name in handle.namelist():
            basename = Path(name).name
            if "/recordings/" in name and re.fullmatch(
                r"[0-9]_(george|jackson|lucas|nicolas|theo|yweweler)_[0-9]+\.wav",
                basename,
            ):
                content = handle.read(name)
                path = recordings / basename
                if not path.exists() or path.read_bytes() != content:
                    path.write_bytes(content)
                hashes[basename] = hashlib.sha256(content).hexdigest()
            elif name.endswith("/README.md") and name.count("/") == 1:
                (cache_dir / "fsdd" / "UPSTREAM_README.md").write_bytes(
                    handle.read(name)
                )
    if len(hashes) != 3000:
        raise ValueError(f"Expected 3000 pinned FSDD recordings; got {len(hashes)}.")
    manifest["fsdd"]["recordings"] = len(hashes)
    manifest["fsdd"]["recording_hashes"] = hashes
    features = prepare_audio_features(cache_dir)
    manifest["fsdd"]["features"] = {
        "filename": features.name,
        "sha256": sha256(features),
        "transform": "fixed 20-band log-mel, 28 frames, no fitted statistics",
    }
    output = cache_dir / "sources_manifest.json"
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    path = prepare_sources(args.cache_dir)
    manifest = json.loads(path.read_text())
    print(
        json.dumps(
            {
                "manifest": str(path),
                "mnist_files": len(manifest["mnist"]["files"]),
                "fsdd_recordings": manifest["fsdd"]["recordings"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
