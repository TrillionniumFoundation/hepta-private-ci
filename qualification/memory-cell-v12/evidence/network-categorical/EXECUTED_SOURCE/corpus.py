"""Source-bound tasks from real Hepta technical documents.

Prompts are authored template paraphrases, not observed production questions.
Phases are a declared document-arrival curriculum, not historical timestamps.
"""

import hashlib
from pathlib import Path
import re
import subprocess

from learned import canonical


SOURCE_COMMIT = "527218f9b823540830907f861a309310b71d38c9"
SKIP_HEADINGS = {"identity, mission and ownership", "source binding and implementation status",
                 "verification, acceptance and evidence", "risks and open issues"}
TEMPLATES = {
    "train": ("For {module}, explain {topic}.",
              "What does the {module} guide specify about {topic}?",
              "Find the requirements for {topic} in {module}."),
    "calibration": ("I am working on {module}; what should I know concerning {topic}?",),
    "test": ("Describe how {module} handles {topic}.",
             "Before changing {module}, I need the documented rules on {topic}."),
}
TOPICS = {
    "Boundary, responsibilities and non-goals": ("division of responsibilities", "what work is owned here", "operations outside this component's remit", "which responsibilities must stay with other modules"),
    "Internal architecture and component decomposition": ("internal components", "how the implementation is organized", "the pieces that cooperate inside this module", "how incoming work passes through its components"),
    "Contracts, ports and compatibility": ("input and output interfaces", "accepted protocol versions", "the messages this module consumes and produces", "how callers know whether an interface change is compatible"),
    "Data authority, persistence and migrations": ("durable storage ownership", "upgrading stored representations", "who may change persistent records", "how stored data is converted when its format changes"),
    "Runtime, concurrency and transaction model": ("concurrent execution", "transaction boundaries", "what happens when workers run simultaneously", "how a write becomes committed without conflicting writers"),
    "Failure semantics, recovery and rollback": ("handling interrupted operations", "reopening after a crash", "how to return to a previous working state", "what to do after a failed operation with uncertain effects"),
    "Security, privacy and threat controls": ("protecting private data", "authorization checks", "how hostile or unauthorized inputs are handled", "which checks prevent information from crossing access boundaries"),
    "Performance, capacity and hot-path policy": ("resource budgets", "latency and memory limits", "how work is bounded when capacity is exhausted", "which costs matter on the frequently executed path"),
    "Observability and operations": ("operational monitoring", "diagnostic telemetry", "which measurements reveal trouble in a running service", "how an operator investigates a degraded instance"),
    "Verification and qualification": ("required checks", "evidence needed for acceptance", "how correctness is demonstrated before adoption", "which experiments decide whether an implementation qualifies"),
    "Implementation sequence and work packages": ("development stages", "implementation dependencies", "which engineering work must happen first", "how the implementation work is divided and ordered"),
    "Activation, compatibility and retirement": ("turning a candidate on or off", "replacing a deployed version", "when a new version can start serving", "how an old implementation is removed without breaking consumers"),
    "Definition of module completion": ("completion criteria", "conditions for finishing the module", "what remains before this work can be called complete", "which obligations must all be met at delivery"),
    "V8.2 pre-coding implementation-readiness overlay": ("preparation before implementation", "readiness before writing code", "which prerequisites must be established before coding starts", "how a proposed implementation is made ready for engineering"),
    "Source implementation receipt": ("recorded source evidence", "what source implementation was recorded", "which source files substantiate the implementation claim", "what the recorded implementation evidence actually covers"),
}


def _documents(repo):
    tree = subprocess.check_output(["git", "ls-tree", "-r", SOURCE_COMMIT, "--", "docs/modules"], cwd=repo, text=True)
    expected = {line.split("\t", 1)[1]: line.split()[2] for line in tree.splitlines()}
    documents = []
    for path in sorted((repo / "docs/modules").glob("*/TECHNICAL.md")):
        relative = path.relative_to(repo).as_posix()
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if expected.get(relative) != blob:
            raise ValueError("document differs from pinned Git source: " + relative)
        documents.append((relative, raw.decode(), hashlib.sha256(raw).hexdigest()))
    if not documents:
        raise ValueError("no pinned technical documents")
    return documents


def build_corpus(repo):
    repo = Path(repo)
    records, queries, provenance, metadata = [], [], [], []
    documents = _documents(repo)
    for index, (path, text, source_id) in enumerate(documents):
        module_match = re.search(r"\*\*Module:\*\*\s*`([^`]+)`", text)
        if not module_match:
            continue
        module = module_match.group(1)
        phase = index % 3
        metadata.append(dict(module=module, source_id=source_id, path=path,
                             fields={label.lower(): re.search(r"\*\*" + label + r":\*\*\s*`([^`]+)`", text).group(1)
                                     for label in ("Owner", "Deputy", "Lifecycle")}))
        dep = re.search(r"Direct dependencies:\s*\n(.*?)(?:\n\n|\Z)", text, re.S)
        dependencies = re.findall(r"`([^`]+)`", dep.group(1)) if dep else []
        matches = list(re.finditer(r"^## ([^\n]+)$", text, re.M))
        for pos, match in enumerate(matches):
            heading = re.sub(r"^\d+[.．]?\s*", "", match.group(1)).strip()
            if heading.lower() in SKIP_HEADINGS:
                continue
            stop = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
            section = text[match.end():stop].strip()
            if len(section) < 100:
                continue
            # Retain the entire section for lexical controls; truncation is not hidden.
            kind = "procedure" if any(w in heading.lower() for w in ("algorithm", "recovery", "execution", "workflow")) else "semantic"
            if any(w in heading.lower() for w in ("lifecycle", "state model", "state and")):
                kind = "event"
            identity = hashlib.sha256(canonical([source_id, heading, section])).hexdigest()
            record = dict(id=identity, text=module + "\n" + heading + "\n" + section,
                          kind=kind, source_id=source_id, version=1, available_phase=phase,
                          module=module, heading=heading, dependencies=dependencies, path=path)
            records.append(record)
            for split, templates in TEMPLATES.items():
                for number, template in enumerate(templates):
                    variants = TOPICS.get(heading, (heading.lower(),) * 4)
                    topic = (variants[0] if number == 2 else heading.lower()) if split == "train" else variants[1 if split == "calibration" else 2 + number]
                    prompt = template.format(module=module.replace(".", " "), topic=topic)
                    queries.append(dict(id=hashlib.sha256(canonical([identity, split, number])).hexdigest(),
                                        text=prompt, target_ids=[identity], phase=phase, split=split))
        provenance.append(dict(path=path, source_sha256=source_id,
                               git_commit=SOURCE_COMMIT, bytes=len(text.encode())))
    # Unsupported fields and absent modules are distinct negative families.
    arrival = {r["module"]: r["available_phase"] for r in records}
    for module in (m["module"] for m in metadata):
        for split, topic in (("calibration", "the personal telephone number of its maintainer"),
                             ("test", "the owner's birthday and private street address")):
            prompt = "For " + module.replace(".", " ") + ", provide " + topic + "."
            queries.append(dict(id=hashlib.sha256(prompt.encode()).hexdigest(), text=prompt,
                                target_ids=[], phase=arrival[module], split=split))
    # Paired evidence requests force composition; answers remain source IDs for
    # this retrieval experiment, not a claim that a reader understood the prose.
    for module in arrival:
        candidates = {r["heading"]: r["id"] for r in records if r["module"] == module}
        first, second = "Data authority, persistence and migrations", "Failure semantics, recovery and rollback"
        if first not in candidates or second not in candidates:
            continue
        for split, phrase in (("train", "persistent-data migration and failure recovery"),
                              ("calibration", "upgrading saved data and reopening after a crash"),
                              ("test", "changing a stored format and returning safely after an interrupted cutover")):
            prompt = "For " + module.replace(".", " ") + ", find both contracts needed for " + phrase + "."
            queries.append(dict(id=hashlib.sha256(prompt.encode()).hexdigest(), text=prompt,
                                target_ids=[candidates[first], candidates[second]], phase=arrival[module], split=split))
    for split, name in (("calibration", "quantum bakery control"), ("test", "stellar gardening scheduler")):
        prompt = "What is the checkpoint recovery contract for " + name + "?"
        queries.append(dict(id=hashlib.sha256(prompt.encode()).hexdigest(), text=prompt,
                            target_ids=[], phase=2, split=split))
    result = dict(schema="hepta.memory.real-source-corpus.v12", source_commit=SOURCE_COMMIT,
                  records=records, queries=queries, provenance=provenance, metadata=metadata,
                  limitations=["authored template paraphrases", "document-arrival phases are not historical chronology",
                               "technical guides describe targets as well as existing implementations",
                               "answers concern what a document says, not verified deployment behavior"])
    result["corpus_sha256"] = hashlib.sha256(canonical(result)).hexdigest()
    return result
