"""Freeze text-only train/dev and a separate authored challenge before fitting."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

TRAIN_NEGATIVE = (
    "Modify the inventory policy for {entity}.",
    "Replace the stored program {workflow}.",
    "Delete the reserve and packing limits for {entity}.",
    "Overwrite {entity}'s policy with the steps in {workflow}.",
    "Schedule {workflow} for execution tomorrow at {entity}.",
    "Email the inventory policy of {entity} to someone outside this workspace.",
    "Do not read the inventory policy for {entity}.",
    "Do not execute {workflow} on {entity}.",
    "Can {workflow} be used as financial advice for {entity}?",
    "Predict the future stock count for {entity} with {workflow}.",
    "Create a new operational procedure named {workflow} for {entity}.",
    "Change the actual stock at {entity} by running {workflow}.",
    "Use {workflow} to alter source authority for {entity}.",
    "Ignore source records and invent policy values for {entity}.",
    "Read the policy for {entity}, then erase it.",
    "Run {workflow} at {entity} and purchase supplies.",
    "Which owner secret credential is stored under {entity}?",
    "Tell a story about the operations of {workflow}.",
    "Were customers at {entity} happy with {workflow}?",
    "Translate the policy of {entity} into French.",
)
DEVELOPMENT_NEGATIVE = (
    "Update the stored inventory settings of {entity}.",
    "Remove all actions from {workflow}.",
    "Estimate next month's demand at {entity} via {workflow}.",
    "Do not compute the result of {workflow} for {entity}.",
    "Execute {workflow} for {entity} and send an email.",
    "Does the name {workflow} rhyme with {entity}?",
    "Replace the credentials associated with {entity}.",
    "Read the policy for {entity} and buy shares.",
)
# Separate challenge is committed with the protocol, but fit() never reads it.
# This is an authored finite-domain challenge, not independent open-world data.
CHALLENGE = {
    "semantic": (
        "Please return {entity}'s three stored inventory settings.",
        "At {entity}, which values define reserve size, package count and cap?",
        "Look up the recorded stock parameters belonging to {entity}.",
        "I want to inspect the policy tuple for {entity}.",
        "Fetch reserve / pack / limit from the policy of {entity}.",
        "Display the inventory configuration recorded for {entity}.",
        "Which stored limits and reserve numbers belong to {entity}?",
        "Read {entity}'s policy values back to me.",
    ),
    "skill": (
        "Please return the four stored steps of {workflow}.",
        "What sequence defines the procedure called {workflow}?",
        "I want to inspect the instructions registered as {workflow}.",
        "Look up the ordered operations encoded in {workflow}.",
        "Fetch the program representation of {workflow}.",
        "Display the action sequence belonging to {workflow}.",
        "Read {workflow}'s procedure back to me.",
        "Which four actions form the stored {workflow} program?",
    ),
    "compose": (
        "Please compute {workflow}'s result from the newest stock observation at {entity}.",
        "Evaluate {workflow} against the current count and policy belonging to {entity}.",
        "Using the latest event from {entity}, calculate the output of {workflow}.",
        "Combine {entity}'s inventory parameters and live count with the steps of {workflow}.",
        "What does {workflow} yield for {entity}'s present stock state?",
        "Execute the stored {workflow} instructions on the recent event of {entity}.",
        "Work through {workflow} with {entity}'s recorded inventory policy and current observation.",
        "Apply the program {workflow} to {entity}; return the computed value.",
    ),
    "unknown": (
        "Erase {entity}'s inventory settings from the source database.",
        "Revise {workflow} so every step uses a different opcode.",
        "Forecast stock prices near {entity} with the {workflow} model.",
        "Use {workflow} to book a plane ticket to {entity}.",
        "Don't retrieve any policy tuple for {entity}.",
        "Never run the {workflow} program on {entity}.",
        "Invent a plausible reserve, pack, and limit for {entity}.",
        "Make up a replacement program for {workflow}.",
        "Approve a cash transfer for {entity} after running {workflow}.",
        "Give a diagnosis for the staff at {entity} using {workflow}.",
        "Recite a poem whose title is {workflow}.",
        "Which password protects the policy data for {entity}?",
        "Read {entity}'s settings and then delete their original source.",
        "Calculate {workflow} for {entity} and place the resulting purchase order.",
        "Change {entity}'s inventory count to the result of {workflow}.",
        "Rewrite the {workflow} instructions before calculating anything.",
        "How popular is {workflow} among visitors to {entity}?",
        "Translate {workflow} into Spanish without looking up its program.",
        "When will {entity} need a new policy next year?",
        "Send {entity}'s recorded settings to an external mailbox.",
        "Give advice on investing at {entity}; use {workflow} as inspiration.",
        "Summarize the biography of the inventor of {workflow}.",
        "Schedule a job to execute {workflow} for {entity} next week.",
        "Bypass the manual hold on {entity} and run {workflow} anyway.",
    ),
}

def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def main(source, output):
    if output.exists():
        raise FileExistsError(output)
    sys.path.insert(0, str(source.resolve()))
    spec = importlib.util.spec_from_file_location("inventory_corpus", source / "corpus.py")
    corpus = importlib.util.module_from_spec(spec); spec.loader.exec_module(corpus)
    def rows(templates, role, phase):
        result = []
        for wording, template in enumerate(templates):
            for entity in range(8):
                workflow = (entity + wording + 3) % 8
                result.append({"id": f"{phase}:{role}:{wording}:{entity}:{workflow}",
                    "text": template.format(entity=corpus.ENTITIES[entity], workflow=corpus.WORKFLOWS[workflow]),
                    "role": role, "entity": entity if role in ("semantic", "compose") else None,
                    "workflow": workflow if role in ("skill", "compose") else None})
        return result
    training = corpus.query_rows(corpus.TRAIN, "train") + rows(TRAIN_NEGATIVE, "unknown", "negative-train")
    calibration = corpus.query_rows(corpus.CALIBRATION, "development") + rows(DEVELOPMENT_NEGATIVE, "unknown", "negative-calibration")
    challenge = [row for role, templates in CHALLENGE.items() for row in rows(templates, role, "challenge")]
    aliases = [{"kind": kind, "key": f"inventory:{kind}:{i}", "phrases": [name]} for kind, names in (("entity", corpus.ENTITIES), ("workflow", corpus.WORKFLOWS)) for i, name in enumerate(names)]
    files = {"train.json": training, "calibration.json": calibration, "aliases.json": aliases, "challenge.json": challenge}
    output.mkdir(parents=True)
    hashes = {}
    for name, value in files.items():
        payload = encode(value); (output / name).write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    protocol = {"schema": "hepta.memory.native-router-protocol.v1", "corpus_commit": "0f41c4968eea63727c69e2b979491e94a99a9dbb",
        "file_sha256": hashes, "fit_reads": ["train.json", "calibration.json", "aliases.json"],
        "fit": {"seed": 731, "steps": 800, "optimizer": "Adam full batch", "learning_rate": .025, "l2": .001, "feature_dimension": 2048},
        "selection": "max development known correct subject to zero development unknown acceptance; no held tuning",
        "limitations": ["finite registered English names", "authored challenge is not independent open-world evaluation", "source values absent from routing inputs"],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output / "PROTOCOL.json").write_bytes(encode(protocol))
    print(json.dumps({"rows": {name: len(value) for name, value in files.items()}, "sha256": hashes}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); main(args.source, args.output)
