"""One bounded official HTTPS attempt per immutable-revision research asset."""

import argparse
import hashlib
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import FILES, MODEL, REVISION, WEIGHT_SHA, metadata_contract, safe_error, safe_url, write


class OfficialRedirects(HTTPRedirectHandler):
    def __init__(self, records):
        self.records = records

    def redirect_request(self, request, fp, code, message, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.username or target.password:
            raise ValueError("Only credential-free HTTPS redirects are accepted")
        self.records.append({"status": code, "from": safe_url(request.full_url), "to": safe_url(newurl)})
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(name, destination, evidence):
    url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"
    record = {"file": name, "official_url": url, "redirects": [], "attempts": 1, "bytes": 0,
              "http_status": None, "sha256": None, "status": "FAIL"}
    began, h = time.monotonic(), hashlib.sha256()
    limit = 800_000_000 if name == "model.safetensors" else 1_000_000
    try:
        opener = build_opener(OfficialRedirects(record["redirects"]))
        with opener.open(Request(url, headers={"User-Agent": "HCSN-fixed-research-encoder/1"}), timeout=30) as response:
            record.update(http_status=response.status, final_url=safe_url(response.geturl()))
            with destination.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    if time.monotonic() - began > 180 or record["bytes"] + len(chunk) > limit:
                        raise TimeoutError("Declared acquisition time/byte bound exceeded")
                    output.write(chunk); h.update(chunk); record["bytes"] += len(chunk)
        if not record["bytes"]:
            raise ValueError("Empty official asset")
        record["sha256"] = h.hexdigest()
        if name == "model.safetensors" and record["sha256"] != WEIGHT_SHA:
            raise ValueError("Published safetensors SHA256 mismatch")
        record["status"] = "PASS"
    except Exception as error:
        record.update(error_type=type(error).__name__, error=safe_error(error))
        if isinstance(error, HTTPError):
            record["http_status"] = error.code
        record["sha256"] = h.hexdigest() if record["bytes"] else None
    record["wall_seconds"] = time.monotonic() - began
    write(evidence / (name.replace(".", "_") + "_ATTEMPT.json"), record)
    return record


def main(model_dir, evidence):
    model_dir.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=False)
    attempts = [fetch(name, model_dir / name, evidence) for name in FILES[:3]]
    report = {"schema": "hcsn-v13-emotion-official-acquisition.v1", "model": MODEL, "revision": REVISION,
              "status": "FAIL", "attempts": attempts, "retry_count": 0,
              "authentication_used": False, "signed_urls_persisted": False}
    for name in FILES[:3]:
        if (model_dir / name).exists():
            (evidence / name).write_bytes((model_dir / name).read_bytes())
    try:
        if not all(item["status"] == "PASS" for item in attempts):
            raise ValueError("Required immutable metadata download failed")
        report["contracts"] = metadata_contract(model_dir)
        attempts.append(fetch(FILES[3], model_dir / FILES[3], evidence))
        if attempts[-1]["status"] != "PASS":
            raise ValueError("Exact official safetensors download did not qualify")
        seal = {"schema": "hcsn-v13-emotion-asset-seal.v1", "model": MODEL, "revision": REVISION,
                "files": {item["file"]: {"sha256": item["sha256"], "bytes": item["bytes"]} for item in attempts},
                "contracts": report["contracts"], "sealed_before_inference_or_readout": True}
        write(model_dir / "ASSET_SEAL.json", seal)
        write(evidence / "ASSET_SEAL.json", seal)
        report["status"] = "PASS"
    except Exception as error:
        report.update(error_type=type(error).__name__, error=safe_error(error))
    write(evidence / "ACQUISITION.json", report)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.model_dir, args.evidence))
