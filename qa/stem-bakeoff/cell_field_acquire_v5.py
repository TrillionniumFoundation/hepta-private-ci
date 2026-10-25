"""Bounded, byte-pinned author-corpus acquisition, without extracting raw CSVs."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from cell_field_acquire_v4 import PINNED as PRIOR_FILES, download_pinned
from cell_field_data_v5 import DATASETS, sha
from prepare_news_cohorts import _read_bounded, canonical


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action, self.fields, self.inside = None, {}, False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form" and values.get("id") == "download-form":
            self.action, self.inside = values.get("action"), True
        if tag == "input" and self.inside and values.get("type") == "hidden":
            self.fields[values["name"]] = values.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False


def author_archive(path, spec):
    if path.exists() or path.is_symlink():
        payload = _read_bounded(path, spec["bytes"])
    else:
        request = Request(spec["url"], headers={"User-Agent": "hepta-v5-source-research"})
        with urlopen(request, timeout=30) as response:
            prefix = response.read(512)
            if prefix[:2] == b"\x1f\x8b":
                payload = prefix+response.read(spec["bytes"]+1-len(prefix))
            else:
                form_bytes = prefix+response.read(65537-len(prefix))
                if len(form_bytes) > 65536:
                    raise ValueError("unexpected author download form size")
                form = DownloadForm()
                form.feed(form_bytes.decode("utf-8"))
                expected = parse_qs(urlparse(spec["url"]).query)["id"][0]
                target = urlparse(form.action or "")
                if target.scheme != "https" or target.hostname != "drive.usercontent.google.com" or form.fields.get("id") != expected:
                    raise ValueError("unrecognized public download confirmation")
                with urlopen(form.action+"?"+urlencode(form.fields), timeout=30) as confirmed:
                    payload = confirmed.read(spec["bytes"]+1)
        if len(payload) != spec["bytes"] or sha(payload) != spec["sha256"]:
            raise ValueError("author archive differs from its exact pre-outcome pin")
        with path.open("xb") as stream:
            stream.write(payload)
    if len(payload) != spec["bytes"] or sha(payload) != spec["sha256"]:
        raise ValueError("cached author archive identity changed")


def acquire(inputs, prior_inputs):
    inputs, prior_inputs = Path(inputs), Path(prior_inputs)
    for root in (inputs, prior_inputs):
        if any(p.is_symlink() for p in (root.absolute(), *root.absolute().parents)):
            raise ValueError("regular source directories required")
        root.mkdir(parents=True, exist_ok=True)
    for spec in DATASETS.values():
        author_archive(inputs/spec["file"], spec)
    for name in ("uci-news.zip", "20news-bydate.tar.gz"):
        download_pinned(prior_inputs/name, *PRIOR_FILES[name])
    receipt = {"schema": "hepta.cell-field-source-acquisition.v5", "sources": DATASETS,
        "primary_author_repository": "https://github.com/zhangxiangxiao/Crepe",
        "independent_loader_reference": "https://github.com/pytorch/text/blob/v0.8.1/torchtext/datasets/text_classification.py",
        "prior_corpora": {name: {"url": PRIOR_FILES[name][0], "sha256": PRIOR_FILES[name][1], "bytes": PRIOR_FILES[name][2]}
                          for name in ("uci-news.zip", "20news-bydate.tar.gz")},
        "scope": "public corpus bytes and provenance only; no raw CSV extraction or model outcomes",
        "acquirer_sha256": sha(Path(__file__).read_bytes())}
    (inputs/"acquisition.json").write_bytes(canonical(receipt)+b"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--prior-inputs", required=True)
    result = acquire(**vars(parser.parse_args()))
    print(json.dumps({"verified_tasks": list(result["sources"]), "verified_prior_corpora": list(result["prior_corpora"])}))
