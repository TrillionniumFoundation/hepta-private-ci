"""Isolated semantic environment; reuse science packages, verify every new wheel.

Run this with the existing science Python and -B.  Only the requested new
directory is written.  Mirror bytes must match PyPI's official release JSON
before offline installation; no source builds, Torch, NumPy or SciPy downloads.
"""
import argparse
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import email
import gzip
import hashlib
import html.parser
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import sysconfig
import time
import urllib.parse
import urllib.error
import urllib.request
import venv
import zipfile

sys.dont_write_bytecode = True
from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
from pip._vendor.packaging.version import InvalidVersion, Version

PINS = {"tokenizers": "0.22.1", "onnxruntime": "1.23.2", "scikit-learn": "1.8.0"}
REUSE = {"numpy": "2.3.5", "scipy": "1.17.0"}
DEFAULT_MIRRORS = ("https://pypi.tuna.tsinghua.edu.cn/simple", "https://mirrors.bfsu.edu.cn/pypi/web/simple")
MAX_WHEEL = 64 * 1024 * 1024
MAX_METADATA = 16 * 1024 * 1024
METADATA_ATTEMPT_SECONDS = (20, 30)
METADATA_CACHE_MANIFEST = "OFFICIAL_PYPI_JSON_MANIFEST.json"


def valid_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def official_url(name, version=None):
    if canonicalize_name(name) != name or not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in name):
        raise ValueError("canonical PyPI project name required")
    if version is not None:
        Version(version)
    return "https://pypi.org/pypi/" + name + "/" + (urllib.parse.quote(version, safe="") + "/" if version else "") + "json"


def require_official_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "pypi.org" or parsed.query or parsed.fragment:
        raise ValueError("official PyPI metadata requires HTTPS pypi.org")
    parts = parsed.path.split("/")
    if len(parts) not in (4, 5) or parts[:2] != ["", "pypi"] or parts[-1] != "json":
        raise ValueError("official PyPI JSON URL path differs")
    version = urllib.parse.unquote(parts[3]) if len(parts) == 5 else None
    if official_url(parts[2], version) != url:
        raise ValueError("canonical official PyPI JSON URL required")


class OfficialMetadataRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        require_official_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


class OfficialMetadataCache:
    """Read a cache obtained through official HTTPS and pinned out of band.

    PyPI JSON has no signed manifest.  The caller explicitly trusts the pinned
    transfer manifest; URL/name checks alone are not proof of its provenance.
    """
    def __init__(self, directory, expected_manifest_sha256):
        if not valid_sha256(expected_manifest_sha256):
            raise ValueError("explicit metadata cache manifest SHA256 required")
        self.root = directory.resolve()
        manifest = self.root / METADATA_CACHE_MANIFEST
        if not manifest.is_file() or manifest.stat().st_size > 1024 * 1024:
            raise ValueError("official metadata cache manifest missing or too large")
        raw = manifest.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
            raise ValueError("official metadata cache manifest SHA256 differs")
        value = json.loads(raw)
        if value.get("schema") != "hepta.memory.official-pypi-json-cache.v1" or not isinstance(value.get("entries"), list) or len(value["entries"]) > 128:
            raise ValueError("official metadata cache manifest schema or bound differs")
        self.manifest_sha256 = expected_manifest_sha256
        self.entries = {}
        paths = set()
        for entry in value["entries"]:
            url, filename = entry["url"], entry["file"]
            require_official_url(url)
            if not isinstance(filename, str) or not filename or Path(filename).name != filename or filename in (".", "..") or "\\" in filename:
                raise ValueError("official metadata cache file must be a local basename")
            if not valid_sha256(entry["sha256"]) or not isinstance(entry["bytes"], int) or not 0 < entry["bytes"] <= MAX_METADATA:
                raise ValueError("official metadata cache entry identity or bound differs")
            if url in self.entries or filename in paths:
                raise ValueError("duplicate official metadata cache entry")
            paths.add(filename); self.entries[url] = entry

    def read(self, url):
        entry = self.entries.get(url)
        if entry is None: return None
        path = (self.root / entry["file"]).resolve()
        if path.parent != self.root or not path.is_file() or path.stat().st_size != entry["bytes"]:
            raise ValueError("official metadata cache file location or byte count differs")
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("official metadata cache JSON SHA256 differs")
        return raw


def sha_file(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for name, value in attrs if name == "href" and value)


class Bootstrap:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.deadline = self.started + args.total_seconds
        self.root = args.environment.resolve()
        self.science_site = Path(sysconfig.get_paths()["purelib"]).resolve()
        if self.root.is_relative_to(Path(sys.prefix).resolve()) or self.science_site.is_relative_to(self.root):
            raise ValueError("new environment must be isolated from the existing science environment")
        self.owned = False
        self.tags = {tag: i for i, tag in enumerate(sys_tags())}
        self.marker_environment = default_environment()
        self.source = {}
        for distribution in importlib.metadata.distributions(path=[str(self.science_site)]):
            name = canonicalize_name(distribution.metadata["Name"])
            self.source[name] = {"version": distribution.version, "requires": distribution.requires or [],
                                 "metadata_sha256": hashlib.sha256((distribution.read_text("METADATA") or "").encode()).hexdigest()}
        for name, expected in REUSE.items():
            if self.source.get(name, {}).get("version") != expected:
                raise ValueError(f"science environment must already contain {name}=={expected}")
        self.metadata_cache = {}
        cache = getattr(args, "metadata_cache", None)
        self.official_cache = OfficialMetadataCache(cache, args.metadata_cache_manifest_sha256) if cache else None
        self.receipt = {"schema": "hepta.memory.semantic-environment.v1", "environment": str(self.root),
                        "science_python": sys.executable, "science_site": str(self.science_site),
                        "python_version": sys.version, "root_pins": PINS, "read_only_reuse": REUSE,
                        "script_sha256": sha_file(Path(__file__)), "downloads": [], "status": "preparing",
                        "metadata_attempt_seconds": METADATA_ATTEMPT_SECONDS, "metadata_attempts": [], "metadata_sources": [],
                        "metadata_offline": getattr(args, "metadata_offline", False),
                        "metadata_cache_manifest_sha256": self.official_cache.manifest_sha256 if self.official_cache else None}

    def remaining(self, maximum=None):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("bounded environment preparation deadline exceeded; rerun with --resume")
        return seconds if maximum is None else min(seconds, maximum)

    def checkpoint(self):
        self.receipt["elapsed_seconds"] = time.monotonic() - self.started
        (self.root / "HEPTA_BOOTSTRAP_RESULT.json").write_bytes(encode(self.receipt))

    def command(self, argv, maximum=90):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=self.remaining(maximum), check=False)
        if result.returncode:
            raise RuntimeError(f"isolated command failed ({result.returncode}): {result.stderr[-8000:]}")
        return result.stdout

    def create(self):
        marker = self.root / "HEPTA_BOOTSTRAP_IDENTITY.json"
        identity = {"schema": "hepta.memory.semantic-environment-identity.v1", "science_site": str(self.science_site),
                    "python_version": list(sys.version_info[:3]), "root_pins": PINS, "read_only_reuse": REUSE}
        if self.root.exists():
            if not self.args.resume or not marker.is_file() or json.loads(marker.read_bytes()) != identity:
                raise FileExistsError("choose a new environment path, or --resume one created by this script")
        else:
            self.root.mkdir(parents=True)
            marker.write_bytes(encode(identity))
        self.owned = True
        python = self.root / "bin/python"
        if not python.exists():
            # venv's bundled pip comes from this same Python; it does not access
            # an index.  No source-site .pth is present during its bootstrap.
            self.command([sys.executable, "-I", "-B", "-m", "venv", str(self.root)], maximum=90)
        self.python = python
        site_path = Path(self.command([str(python), "-I", "-B", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]).strip())
        if not site_path.is_relative_to(self.root):
            raise ValueError("new Python site-packages is outside the isolated environment")
        self.site = site_path
        (site_path / "zz_hepta_read_only_science.pth").write_text(str(self.science_site) + "\n")
        self.wheels = self.root / "verified-wheels"; self.wheels.mkdir(exist_ok=True)
        self.metadata_dir = self.root / "official-metadata"; self.metadata_dir.mkdir(exist_ok=True)
        observed = json.loads(self.command([str(python), "-I", "-B", "-c",
            "import importlib.metadata as m,json,sys; print(json.dumps({'numpy':m.version('numpy'),'scipy':m.version('scipy'),'prefix':sys.prefix,'path':sys.path}))"]))
        if observed["numpy"] != REUSE["numpy"] or observed["scipy"] != REUSE["scipy"] \
                or Path(observed["prefix"]).absolute() != self.root \
                or observed["path"].index(str(site_path)) >= observed["path"].index(str(self.science_site)):
            raise ValueError("isolated prefix or own-site-before-science import ordering differs")
        self.receipt["site_packages"] = str(site_path)
        self.checkpoint()

    def fetch(self, url, limit=MAX_METADATA, *, attempt_seconds=10, official=False):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("HTTPS metadata only")
        if official: require_official_url(url)
        began = time.monotonic()
        attempt_deadline = min(self.deadline, began + (attempt_seconds if official else 30))
        request = urllib.request.Request(url, headers={"User-Agent": "hepta-pinned-wheel-bootstrap/1.0", "Accept-Encoding": "gzip"})
        opener = urllib.request.build_opener(OfficialMetadataRedirect()).open if official else urllib.request.urlopen
        with opener(request, timeout=self.remaining(attempt_seconds)) as response:
            if official: require_official_url(response.geturl())
            chunks, size = [], 0
            while True:
                if time.monotonic() >= attempt_deadline:
                    raise TimeoutError("metadata request deadline")
                self.remaining()
                chunk = response.read(32768)
                if not chunk: break
                size += len(chunk)
                if size > limit: raise ValueError("metadata compressed size bound")
                chunks.append(chunk)
            raw = b"".join(chunks)
            if response.headers.get("Content-Encoding") == "gzip":
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as source:
                    raw = source.read(limit + 1)
            if len(raw) > limit: raise ValueError("metadata expanded size bound")
            return raw

    def fetch_official(self, url):
        require_official_url(url)
        for index, seconds in enumerate(METADATA_ATTEMPT_SECONDS):
            began = time.monotonic()
            record = {"url": url, "attempt": index + 1, "timeout_seconds": min(seconds, self.remaining())}
            self.receipt["metadata_attempts"].append(record)
            try:
                raw = self.fetch(url, attempt_seconds=seconds, official=True)
                record.update(status="received", bytes=len(raw), elapsed_seconds=time.monotonic() - began)
                return raw
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead, http.client.RemoteDisconnected) as error:
                record.update(status="failed", error=str(error)[:600], elapsed_seconds=time.monotonic() - began)
                certificate_failure = isinstance(error, ssl.SSLCertVerificationError) or isinstance(getattr(error, "reason", None), ssl.SSLCertVerificationError)
                permanent_http_failure = isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429, 500, 502, 503, 504)
                local_permission_failure = isinstance(error, PermissionError) or isinstance(getattr(error, "reason", None), PermissionError)
                if certificate_failure or permanent_http_failure or local_permission_failure or index + 1 == len(METADATA_ATTEMPT_SECONDS):
                    raise
                time.sleep(min(0.25, self.remaining()))
        raise AssertionError("bounded metadata attempts exhausted without a result")

    def metadata(self, name, version=None):
        key = (name, version)
        if key not in self.metadata_cache:
            url = official_url(name, version)
            raw = self.official_cache.read(url) if self.official_cache else None
            source = "pinned_official_json_cache" if raw is not None else "official_https"
            if raw is None:
                if getattr(self.args, "metadata_offline", False):
                    raise FileNotFoundError(f"offline official metadata cache has no entry for {url}")
                raw = self.fetch_official(url)
            value = json.loads(raw)
            if canonicalize_name(value["info"]["name"]) != name or (version and Version(value["info"]["version"]) != Version(version)):
                raise ValueError("official release metadata name/version differs")
            record = {"url": url, "source": source, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if source == "pinned_official_json_cache": record["cache_manifest_sha256"] = self.official_cache.manifest_sha256
            self.receipt["metadata_sources"].append(record)
            self.metadata_cache[key] = value
            (self.metadata_dir / f"{name}-{version or 'project'}.json").write_bytes(raw)
        return self.metadata_cache[key]

    def wheel(self, metadata):
        candidates = []
        for item in metadata["urls"]:
            filename = item["filename"]
            if item["packagetype"] != "bdist_wheel" or item.get("yanked") or Path(filename).name != filename \
                    or not 0 < item["size"] <= MAX_WHEEL:
                continue
            _, _, _, tags = parse_wheel_filename(filename)
            rank = min((self.tags[tag] for tag in tags if tag in self.tags), default=None)
            if rank is None or (item.get("requires_python") and not SpecifierSet(item["requires_python"]).contains(self.marker_environment["python_full_version"])):
                continue
            if urllib.parse.urlsplit(item["url"]).hostname != "files.pythonhosted.org" or len(item["digests"]["sha256"]) != 64:
                raise ValueError("official wheel host or SHA256 shape differs")
            candidates.append((rank, filename, item))
        if not candidates: raise ValueError("release has no bounded compatible binary wheel")
        return min(candidates, key=lambda value: value[:2])[2]

    def active(self, text, extras=("",)):
        requirement = Requirement(text)
        if requirement.marker and not any(requirement.marker.evaluate({**self.marker_environment, "extra": extra}) for extra in extras):
            return None
        if requirement.url: raise ValueError("direct URL dependencies are outside this PyPI-only bootstrap")
        return requirement

    def resolve(self, extra_requirements=()):
        constraints, extras, selected = defaultdict(set), defaultdict(set), {}
        pending = deque()
        def add(text, contexts=("",)):
            requirement = self.active(text, contexts)
            if requirement is None: return
            name = canonicalize_name(requirement.name)
            if name == "torch" or name.startswith("nvidia-"):
                raise ValueError("Torch/GPU dependency downloads are forbidden")
            before = (set(constraints[name]), set(extras[name]))
            constraints[name].add(str(requirement.specifier)); extras[name].update(requirement.extras)
            if before != (constraints[name], extras[name]) or name not in selected: pending.append(name)
        for name, version in {**PINS, **REUSE}.items(): add(f"{name}=={version}")
        for requirement in extra_requirements: add(requirement)
        passes = 0
        while pending:
            self.remaining(); passes += 1
            if passes > 256 or len(constraints) > 32: raise ValueError("dependency graph bound")
            name = pending.popleft()
            specification = SpecifierSet(",".join(sorted(value for value in constraints[name] if value)))
            source = self.source.get(name)
            if name not in PINS and source and specification.contains(source["version"]):
                choice = {"name": name, "version": source["version"], "reuse": True, "requires": source["requires"], "metadata_sha256": source["metadata_sha256"]}
            else:
                if name in REUSE: raise ValueError(f"reused {name} cannot satisfy dependencies; refusing a download")
                if name in PINS:
                    versions = [PINS[name]]
                else:
                    project = self.metadata(name)
                    parsed = []
                    for version in project["releases"]:
                        try: value = Version(version)
                        except InvalidVersion: continue
                        if not value.is_prerelease and not value.is_devrelease and specification.contains(value): parsed.append(value)
                    versions = [str(value) for value in sorted(parsed, reverse=True)]
                choice = None
                for version in versions[:12]:
                    if not specification.contains(version): continue
                    metadata = self.metadata(name, version)
                    try: artifact = self.wheel(metadata)
                    except ValueError: continue
                    choice = {"name": name, "version": version, "reuse": False, "requires": metadata["info"].get("requires_dist") or [],
                              "artifact": artifact, "official_metadata_sha256": sha_file(self.metadata_dir / f"{name}-{version}.json")}
                    break
                if choice is None: raise ValueError(f"no compatible pinned wheel satisfies {name}{specification}")
            signature = (choice["version"], sorted(extras[name]))
            if name in selected and selected[name]["signature"] == signature: continue
            choice["signature"] = signature; selected[name] = choice
            for requirement in choice["requires"]: add(requirement, ("", *sorted(extras[name])))
        for name, choice in selected.items():
            if not SpecifierSet(",".join(sorted(value for value in constraints[name] if value))).contains(choice["version"]):
                raise ValueError("dependency constraints changed after selection")
        return selected

    def download(self, choice):
        artifact = choice["artifact"]; filename = artifact["filename"]
        expected, size = artifact["digests"]["sha256"], artifact["size"]
        output = self.wheels / filename; partial = self.wheels / (filename + ".part")
        if output.exists():
            if output.stat().st_size != size or sha_file(output) != expected: raise ValueError("cached wheel identity differs")
            return {"name": choice["name"], "version": choice["version"], "file": str(output), "sha256": expected, "bytes": size, "source": "already verified cache"}
        urls, failures = [], []
        for mirror in self.args.mirror or DEFAULT_MIRRORS:
            index = mirror.rstrip("/") + "/" + choice["name"] + "/"
            try:
                links = Links(); links.feed(self.fetch(index, 8 * 1024 * 1024).decode())
                allowed = {urllib.parse.urlsplit(index).hostname, "mirrors.tuna.tsinghua.edu.cn", "pypi.tuna.tsinghua.edu.cn", "files.pythonhosted.org"}
                for link in links.links:
                    url = urllib.parse.urljoin(index, link).split("#", 1)[0]
                    parsed = urllib.parse.urlsplit(url)
                    if parsed.scheme == "https" and parsed.hostname in allowed and urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1]) == filename:
                        urls.append(url); break
            except Exception as error:
                failures.append({"index": index, "error": str(error)[:400]})
        urls.append(artifact["url"])
        for url in dict.fromkeys(urls):
            try:
                self.remaining()
                offset = partial.stat().st_size if partial.exists() else 0
                if offset > size: partial.unlink(); offset = 0
                if offset == size:
                    if sha_file(partial) == expected: partial.replace(output); break
                    partial.unlink(); offset = 0
                headers = {"User-Agent": "hepta-pinned-wheel-bootstrap/1.0"}
                if offset: headers["Range"] = f"bytes={offset}-"
                began = time.monotonic()
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.remaining(10)) as response:
                    if response.status == 206:
                        if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"): raise ValueError("wheel Range response differs")
                    else: offset = 0
                    with partial.open("ab" if offset else "wb") as target:
                        total = offset
                        while True:
                            self.remaining()
                            if time.monotonic() - began > self.args.wheel_seconds: raise TimeoutError("bounded wheel source timed out")
                            chunk = response.read(32768)
                            if not chunk: break
                            total += len(chunk)
                            if total > size: raise ValueError("wheel exceeds official byte count")
                            target.write(chunk)
                if partial.stat().st_size != size: raise ValueError("wheel length differs from official PyPI JSON")
                if sha_file(partial) != expected:
                    partial.unlink(); raise ValueError("wheel SHA256 differs from official PyPI JSON")
                partial.replace(output)
                return {"name": choice["name"], "version": choice["version"], "file": str(output), "sha256": expected,
                        "bytes": size, "source": url, "official_json": f"https://pypi.org/pypi/{choice['name']}/{choice['version']}/json", "prior_failures": failures}
            except Exception as error:
                failures.append({"url": url, "error": str(error)[:400]})
        if output.exists(): return {"name": choice["name"], "version": choice["version"], "file": str(output), "sha256": expected, "bytes": size, "source": "completed verified Range cache"}
        raise RuntimeError(f"wheel unavailable after bounded verified sources: {filename}: {failures}")

    def run(self):
        self.create()
        additional = []
        for _ in range(3):
            plan = self.resolve(additional)
            downloads = [choice for choice in plan.values() if not choice["reuse"]]
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(self.download, choice): choice for choice in downloads}
                for future in as_completed(futures):
                    record = future.result(); self.receipt["downloads"].append(record); self.checkpoint()
                    print(json.dumps({"verified_wheel": record["name"], "version": record["version"], "bytes": record["bytes"], "sha256": record["sha256"]}), flush=True)
            missing = []
            for choice in downloads:
                path = self.wheels / choice["artifact"]["filename"]
                with zipfile.ZipFile(path) as archive:
                    names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
                    if len(names) != 1 or archive.getinfo(names[0]).file_size > 1024 * 1024: raise ValueError("wheel metadata bound")
                    metadata = email.message_from_bytes(archive.read(names[0]))
                if canonicalize_name(metadata["Name"]) != choice["name"] or Version(metadata["Version"]) != Version(choice["version"]):
                    raise ValueError("verified wheel metadata differs from its release")
                for text in metadata.get_all("Requires-Dist", []):
                    requirement = self.active(text, ("", *choice["signature"][1]))
                    if requirement and (canonicalize_name(requirement.name) not in plan
                            or not requirement.specifier.contains(plan[canonicalize_name(requirement.name)]["version"])
                            or not requirement.extras.issubset(set(plan[canonicalize_name(requirement.name)]["signature"][1]))):
                        requirement.marker = None
                        missing.append(str(requirement))
            if not missing: break
            additional.extend(missing)
        else: raise ValueError("wheel dependencies did not converge within the bounded plan")
        lock = {name: {key: value for key, value in choice.items() if key not in ("requires", "signature")} for name, choice in plan.items()}
        (self.root / "HEPTA_WHEEL_LOCK.json").write_bytes(encode(lock))
        paths = [str(self.wheels / choice["artifact"]["filename"]) for choice in downloads]
        # --ignore-installed overlays the new prefix without uninstalling any
        # visible package in the read-only science site.  No index is reachable.
        log = self.command([str(self.python), "-I", "-B", "-m", "pip", "--isolated", "install", "--prefix", str(self.root), "--no-index", "--no-deps",
                            "--ignore-installed", "--no-compile", "--no-cache-dir", "--disable-pip-version-check", *paths])
        (self.root / "HEPTA_INSTALL.log").write_text(log)
        check = """import importlib,importlib.metadata as m,json,sys
names={'numpy':'numpy','scipy':'scipy','onnxruntime':'onnxruntime','tokenizers':'tokenizers','scikit-learn':'sklearn','threadpoolctl':'threadpoolctl'}
print(json.dumps({'prefix':sys.prefix,'packages':{name:{'version':m.version(name),'file':importlib.import_module(module).__file__} for name,module in names.items()}}))"""
        actual = json.loads(self.command([str(self.python), "-I", "-B", "-c", check]))
        for name, version in {**PINS, **REUSE}.items():
            if actual["packages"][name]["version"] != version: raise ValueError("final imported package version differs")
            expected_root = self.site if name in PINS else self.science_site
            if not Path(actual["packages"][name]["file"]).is_relative_to(expected_root): raise ValueError("final imported package origin differs")
        after = {canonicalize_name(item.metadata["Name"]): item for item in importlib.metadata.distributions(path=[str(self.science_site)])}
        for name, source in self.source.items():
            distribution = after.get(name)
            if distribution is None or distribution.version != source["version"] or hashlib.sha256((distribution.read_text("METADATA") or "").encode()).hexdigest() != source["metadata_sha256"]:
                raise ValueError("original science package metadata changed")
        self.receipt.update(status="ready", imports=actual, lock_sha256=sha_file(self.root / "HEPTA_WHEEL_LOCK.json"),
                            original_science_metadata_unchanged=True, runtime_instruction="Use this Python with -B; encoder worker already supplies -I -u -B.")
        self.checkpoint(); print(json.dumps({"status": "ready", "python": str(self.python), "receipt": str(self.root / "HEPTA_BOOTSTRAP_RESULT.json")}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--mirror", action="append", help="HTTPS simple-index root; repeat to choose mirror order")
    parser.add_argument("--total-seconds", type=int, default=240)
    parser.add_argument("--wheel-seconds", type=int, default=60)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--metadata-cache", type=Path, help="read-only directory containing pinned official PyPI JSON and its transfer manifest")
    parser.add_argument("--metadata-cache-manifest-sha256", help="SHA256 obtained through the trusted official-HTTPS cache transfer")
    parser.add_argument("--metadata-offline", action="store_true", help="require all official JSON in the pinned cache; wheel downloads may still use HTTPS")
    args = parser.parse_args()
    if not 60 <= args.total_seconds <= 1800 or not 10 <= args.wheel_seconds <= 300:
        parser.error("bounded timeout values required")
    if bool(args.metadata_cache) != bool(args.metadata_cache_manifest_sha256) or (args.metadata_offline and not args.metadata_cache):
        parser.error("metadata cache and explicit manifest SHA256 must be supplied together; offline metadata requires both")
    bootstrap = Bootstrap(args)
    try: bootstrap.run()
    except Exception as error:
        if bootstrap.owned:
            bootstrap.receipt.update(status="failed", error=str(error)[:12000]); bootstrap.checkpoint()
        raise


if __name__ == "__main__":
    main()
