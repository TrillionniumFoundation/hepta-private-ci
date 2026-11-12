"""Read-only browser screenshots and DOM snapshots after owner admission.

Each observation uses a fresh headless context without a user's cookies or profile.
An operator fixes the URL, origins, selector and browser identity. The actor may
select that registered source but cannot replace its URL or request arbitrary I/O.
Local hashes bind observations; they do not attest the site's truth or independence.
"""

import json
import hashlib
import os
import stat
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from .schema import canonical, digest, exact, integer, require, sha


def _origin(url):
    require(type(url) is str and 0 < len(url) <= 2048, "browser URL bound")
    value = urlsplit(url)
    require(
        value.username is None
        and value.password is None
        and value.hostname is not None
        and not value.fragment,
        "invalid browser URL",
    )
    require(
        value.scheme == "https"
        or (value.scheme == "http" and value.hostname in ("127.0.0.1", "localhost")),
        "browser sources require HTTPS or a local test server",
    )
    return value.scheme + "://" + value.netloc


def validate_browser_config(config):
    exact(
        config,
        "schema url allowed_origins selector viewport timeout_ms executable executable_sha256 source_group ocr",
    )
    require(config["schema"] == "perc1.browser-capture.v1", "unknown browser config")
    origin = _origin(config["url"])
    origins = config["allowed_origins"]
    require(type(origins) is list and 0 < len(origins) <= 16, "browser origin bound")
    require(len(set(origins)) == len(origins), "duplicate browser origin")
    require(
        all(_origin(item) == item for item in origins) and origin in origins,
        "browser URL is outside operator origins",
    )
    require(
        type(config["selector"]) is str and 0 < len(config["selector"]) <= 256,
        "browser selector bound",
    )
    exact(config["viewport"], "width height")
    for dimension in config["viewport"].values():
        require(64 <= integer(dimension, 1) <= 4096, "browser viewport bound")
    require(100 <= integer(config["timeout_ms"], 1) <= 30000, "browser timeout bound")
    require(
        type(config["executable"]) is str and Path(config["executable"]).is_absolute(),
        "absolute browser executable required",
    )
    digest(config["executable_sha256"])
    require(
        type(config["source_group"]) is str and 0 < len(config["source_group"]) <= 256,
        "browser source group bound",
    )
    return json.loads(canonical(config))


def configured_browser_capture(config, request):
    """Capture a registered page; caller must invoke this only after reservation."""
    from playwright.sync_api import sync_playwright

    from .source_capture import configured_capture

    config = validate_browser_config(config)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    # Pin the actual Chromium binary, not a shell launcher whose target can drift.
    descriptor = os.open(config["executable"], os.O_RDONLY | os.O_NOFOLLOW)
    hasher = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 512 * 1024 * 1024,
            "browser binary bound",
        )
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
        after = os.fstat(stream.fileno())
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns)
        and hasher.hexdigest() == config["executable_sha256"],
        "browser executable changed",
    )
    permitted, denied = [], []
    request_counts = {"allowed": 0, "blocked": 0}

    def route_request(route):
        url, method = route.request.url, route.request.method
        try:
            allowed = _origin(url) in config["allowed_origins"] and method in (
                "GET",
                "HEAD",
            )
        except (ValueError, TypeError):
            allowed = False
        target = permitted if allowed else denied
        request_counts["allowed" if allowed else "blocked"] += 1
        if len(target) < 32:
            target.append({"method": method, "url_prefix": url[:256]})
        if allowed:
            route.continue_()
        else:
            route.abort()

    with sync_playwright() as runtime:
        options = {"executable_path": config["executable"], "headless": True}
        inherited_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if inherited_proxy and urlsplit(config["url"]).hostname not in (
            "127.0.0.1",
            "localhost",
        ):
            proxy = urlsplit(inherited_proxy)
            options["proxy"] = {"server": proxy.scheme + "://" + proxy.netloc}
            require(
                proxy.username is None and proxy.password is None,
                "authenticated browser proxy needs a configured credential provider",
            )
        browser = runtime.chromium.launch(**options)
        try:
            version = browser.version
            context = browser.new_context(
                viewport=config["viewport"],
                java_script_enabled=False,
                service_workers="block",
                accept_downloads=False,
            )
            context.route("**/*", route_request)
            page = context.new_page()
            response = page.goto(
                config["url"], wait_until="load", timeout=config["timeout_ms"]
            )
            require(response is not None and response.status < 400, "page load failed")
            require(
                _origin(page.url) in config["allowed_origins"], "redirect outside grant"
            )
            target = page.locator(config["selector"])
            require(target.count() == 1, "browser selector is absent or ambiguous")
            text = target.inner_text(timeout=config["timeout_ms"]).encode("utf-8")
            dom = page.content().encode("utf-8")
            screenshot = target.screenshot(type="png", timeout=config["timeout_ms"])
            require(0 < len(screenshot) <= 4 * 1024 * 1024, "screenshot byte bound")
            require(0 < len(dom) <= 2 * 1024 * 1024, "DOM byte bound")
            require(0 < len(text) <= 2 * 1024 * 1024, "DOM text byte bound")
            receipt = {
                "schema": "perc1.browser-observation.v1",
                "config": config,
                "config_sha256": sha(config),
                "adapter_sha256": sha(Path(__file__).read_bytes()),
                "browser_version": version,
                "final_url": page.url,
                "status": response.status,
                "observed_at_micros": time.time_ns() // 1000,
                "selector": config["selector"],
                "screenshot_sha256": sha(screenshot),
                "dom_sha256": sha(dom),
                "text_sha256": sha(text),
                "allowed_request_sample": permitted,
                "blocked_request_sample": denied,
                "request_counts": request_counts,
                "requests_sample_cap": 32,
                "sample_url_prefix_cap": 256,
                "javascript_enabled": False,
                "fresh_context": True,
                "measurements": {
                    "browser_wall_ns": time.perf_counter_ns() - started,
                    "calling_process_cpu_ns": time.process_time_ns() - cpu,
                    "child_process_cpu_ns": None,
                    "energy_joules": None,
                    "provider_billing": None,
                },
            }
        finally:
            browser.close()
    # Reuse the same exact-evidence collector for file and browser observations.
    # Temporary input paths are not needed by retained replay or cold readback.
    with tempfile.TemporaryDirectory(prefix="perc-browser-") as folder:
        root = Path(folder)
        (root / "capture.png").write_bytes(screenshot)
        (root / "dom.txt").write_bytes(text)
        source = {
            "schema": "perc1.source-capture.v1",
            "kind": "screenshot",
            "image": {"path": str(root / "capture.png"), "sha256": sha(screenshot)},
            "source_uri": receipt["final_url"],
            "source_group": config["source_group"],
            "document": None,
            "text": {"kind": "dom", "path": str(root / "dom.txt"), "sha256": sha(text)},
            "ocr": config["ocr"],
        }
        acquired = configured_capture(source, request)
    acquired["source_evidence"]["artifacts"]["raw_dom"] = dom
    acquired["source_evidence"]["artifacts"]["browser_receipt"] = canonical(receipt)
    return acquired
