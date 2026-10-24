"""Freeze minimal public dependencies before any prospective benchmark outcome."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from operational_cohort_plan import canonical, decode


COMMON = """pytest==5.4.3 attrs==19.3.0 atomicwrites==1.4.0
more-itertools==8.3.0 packaging==20.4 pluggy==0.13.1 py==1.8.1
pyparsing==2.4.7 six==1.15.0 wcwidth==0.2.4
importlib-metadata==1.6.1 zipp==3.1.0"""
EXTRAS = {
    "ansible": """argcomplete==1.11.1 cffi==1.14.0 cryptography==2.9.2
    Jinja2==3.0.0a1 MarkupSafe==2.0.0a1 pycparser==2.20 PyYAML==5.3.1
    pytest==3.10.1 pytest-mock==1.2 mock==4.0.2""",
    "cookiecutter": """appdirs==1.4.4 arrow==0.15.6 binaryornot==0.4.4
    certifi==2020.4.5.2 chardet==3.0.4 click==7.1.2 idna==2.9
    Jinja2==2.11.2 jinja2-time==0.2.0 MarkupSafe==1.1.1 poyo==0.5.0
    python-dateutil==2.8.1 python-slugify==4.0.0 requests==2.23.0
    text-unidecode==1.3 urllib3==1.25.9 future==0.18.2
    pytest-cov==2.9.0 coverage==5.1 pytest-mock==3.1.0 freezegun==0.3.15""",
    "fastapi": """aiofiles==0.5.0 certifi==2020.4.5.2 chardet==3.0.4
    dnspython==1.16.0 email-validator==1.1.1 idna==2.9 pydantic==1.5.1
    python-multipart==0.0.5 requests==2.23.0 starlette==0.13.2
    typing-extensions==3.7.4.2 urllib3==1.25.9 pytest-cov==2.9.0
    coverage==5.1 ujson==3.0.0""",
    "httpie": """blinker==1.4 brotlipy==0.7.0 certifi==2020.4.5.1
    cffi==1.14.0 chardet==3.0.4 click==7.1.2 colorama==0.4.3
    decorator==4.4.2 Flask==1.1.2 httpbin==0.7.0 idna==2.9
    itsdangerous==1.1.0 Jinja2==2.11.2 MarkupSafe==1.1.1 mock==4.0.2
    pycparser==2.20 Pygments==2.6.1 pytest-httpbin==1.0.0 raven==6.10.0
    requests==2.23.0 urllib3==1.25.9 Werkzeug==1.0.1
    pytest-cov==2.9.0 coverage==5.1 pytest-xdist==1.32.0 execnet==1.7.1""",
    "sanic": """aiofiles==0.5.0 aiohttp==3.6.2 async-timeout==3.0.1
    certifi==2020.4.5.1 chardet==3.0.4 coverage==5.1 httptools==0.1.1
    h11==0.8.1 h2==3.2.0 httpcore==0.3.0 httpx==0.9.3 idna==2.9
    multidict==4.7.6 py-cpuinfo==5.0.0 pytest-benchmark==3.2.3
    pytest-cov==2.9.0 pytest-sanic==1.6.1 pytest-sugar==0.9.3
    rfc3986==1.4.0 sniffio==1.1.0 termcolor==1.1.0 websockets==8.1
    yarl==1.4.2 uvloop==0.14.0 ujson==1.35 async-generator==1.10
    beautifulsoup4==4.9.1 gunicorn==20.0.4 uvicorn==0.11.5
    requests==2.23.0 urllib3==1.25.9""",
}
SMOKE = {
    "ansible": ["pytest", "jinja2", "yaml", "cryptography", "mock"],
    "cookiecutter": ["pytest", "jinja2", "jinja2_time", "binaryornot", "click", "poyo", "past", "freezegun"],
    "fastapi": ["pytest", "pydantic", "starlette", "email_validator", "multipart", "requests"],
    "httpie": ["pytest", "pytest_httpbin", "httpbin", "requests", "pygments", "mock"],
    "sanic": ["pytest", "aiohttp", "httptools", "uvloop", "ujson", "websockets", "httpx"],
}
FORBIDDEN = {"ansible", "ansible-base", "fastapi", "httpie", "sanic", "cookiecutter", "pkg-resources"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def name_key(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def exact_pins(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-e ")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
        if not match:
            raise ValueError("non-exact metadata requirement: " + line)
        key = name_key(match[1])
        if key in result and result[key] != match[2]:
            raise ValueError("conflicting dependency pin: " + key)
        result[key] = match[2]
    return result


def build_plan(source_plan, bugsinpy, interpreter, output):
    source_plan, bugsinpy, interpreter, output = map(Path, (source_plan, bugsinpy, interpreter, output))
    raw = source_plan.read_bytes()
    cohort = json.loads(raw)
    profiles, assignments, pins = {}, {}, {str(source_plan.resolve()): hashlib.sha256(raw).hexdigest()}
    for bug in cohort["bugs"]:
        project = bug["project"]
        directory = bugsinpy / "projects" / project / "bugs" / str(bug["bug_id"])
        metadata_path = directory / "requirements.txt"
        metadata_sha = sha(metadata_path)
        if metadata_sha != bug["metadata_files"]["requirements.txt"]["sha256"]:
            raise ValueError("source-plan metadata pin changed")
        pins[str(metadata_path.resolve())] = metadata_sha
        metadata = exact_pins(decode(metadata_path))
        chosen = exact_pins("\n".join(COMMON.split()))
        chosen.update(exact_pins("\n".join(EXTRAS[project].split())))
        # Metadata wins over proposed support versions. Setup-only pytest pins
        # are explicit in EXTRAS; target packages never enter dependencies.
        chosen.update({k: metadata[k] for k in chosen if k in metadata})
        if project == "sanic" and "requests-async" in metadata:
            chosen["requests-async"] = metadata["requests-async"]
        if FORBIDDEN & chosen.keys():
            raise ValueError("target checkout would be shadowed by an installed package")
        key = project + "-" + hashlib.sha256(canonical(chosen)).hexdigest()[:12]
        profiles.setdefault(key, {"project": project,
            "requirements": [k + "==" + v for k, v in sorted(chosen.items())],
            "smoke_imports": SMOKE[project], "source_paths": ["lib"] if project == "ansible" else [],
            "plain_pytest": True, "groups": [], "metadata_pins": {},
            "support_pins_not_in_group_metadata": {}})
        profiles[key]["groups"].append(bug["group_id"])
        profiles[key]["metadata_pins"][bug["group_id"]] = metadata_sha
        profiles[key]["support_pins_not_in_group_metadata"][bug["group_id"]] = {
            k: v for k, v in chosen.items() if k not in metadata}
        assignments[bug["group_id"]] = key
    result = {"schema": "hepta.prospective-runtime-plan.v1", "profiles": profiles,
        "group_profiles": assignments, "file_pins": pins,
        "interpreter": str(interpreter.resolve()), "interpreter_sha256": sha(interpreter),
        "bootstrap": ["pip==24.0", "setuptools==49.6.0", "wheel==0.36.2"],
        "source_plan_sha256": hashlib.sha256(raw).hexdigest(),
        "builder_policy": {"benchmark_commands_permitted": False, "import_smoke_only": True,
            "same_environment_for_both_revisions": True, "target_packages_forbidden": sorted(FORBIDDEN),
            "no_changes_to_old_environments": True, "minimum_free_disk_bytes": 250000000,
            "per_install_timeout_seconds": 600, "pip_cache_shared_only_within_new_runtime_root": True},
        "authority": "Exact selected BugsInPy requirements pins take precedence. Missing small support packages come from static source/test imports and setup requirements, fixed before outcomes.",
        "exclusions": "Desktop/docs/scientific tooling is not installed. Target editable/install steps are replaced by checkout source paths. pkg-resources==0.0.0 is distro bookkeeping. Cookiecutter tox hooks are bypassed by the declared explicit-pytest adapter.",
        "compatibility": ["Actual interpreter is CPython 3.8.20 for every profile; upstream declarations include 3.6.9, 3.7.3 and 3.8.3.",
            "Pytest --assert=plain disables expression rewriting, not Python assertions, and is uniform across both revisions.",
            "Sanic bug 5 metadata pytest 5.4.3 overrides source tox pytest 3.3.2. Other source-to-metadata differences retain metadata pins.",
            "Ansible missing test support uses the project-wide static superset pytest-mock 1.2 and mock 4.0.2.",
            "Cookiecutter unpinned test_requirements.txt supplies pytest/cov/mock/freezegun names; chosen support versions are recorded explicitly."],
        "code_sha256": {Path(__file__).name: sha(__file__)}}
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    output.write_bytes(canonical(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-plan", "bugsinpy", "interpreter", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = build_plan(args.source_plan, args.bugsinpy, args.interpreter, args.output)
    print(json.dumps({"profiles": len(result["profiles"]), "groups": len(result["group_profiles"]),
                      "plan_sha256": sha(args.output)}))
