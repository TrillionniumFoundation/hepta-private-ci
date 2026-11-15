"""Deterministic four-row opposite-world cohorts for multi-hop controlled relations.

Labels never appear in public fixture rows. This remains synthetic test grammar,
not natural MultiRC, future field data or real pretrained Granite features.
"""
from collections import Counter
import random
from hashlib import sha256

from v9_typed_graph import TYPES, canonical, digest

TRAIN = {
    "object": "coin bead stamp token key marble shell button",
    "person": "Ada Ben Cleo Drew Esme Finn Gina Hugo",
    "box": "blue green silver bronze peach purple crimson amber",
    "shelf": "cedar willow pine maple birch elm acacia cypress",
    "room": "north south west east central upper lower middle",
    "building": "stone brick copper glass timber steel marble coral",
    "district": "harbor valley forest summit river coastal prairie canyon",
}
NOVEL = {
    "object": "anchor prism ribbon whistle pebble locket thimble lantern",
    "person": "Alden Briar Cassia Dorian Elian Freya Galen Hazel",
    "box": "violet teal ivory coral indigo jade tan mauve",
    "shelf": "spruce poplar ash fir beech alder olive walnut",
    "room": "amber azure umber rose mist sunny quiet bright",
    "building": "granite basalt limestone quartz porcelain obsidian sandstone chalk",
    "district": "orchard meadow tundra lagoon glacier desert marsh ocean",
}
VERBS = (
    "The {a} belongs to {b}.",
    "{a} stores all their possessions in the {b} box.",
    "The {a} box is on the {b} shelf.",
    "The {a} shelf is in the {b} room.",
    "The {a} room is in the {b} building.",
    "The {a} building is in the {b} district.",
)


def panel(role, depth, groups, *, seed=1703):
    if (role not in ("train", "held_known", "held_novel") or type(depth) is not int
            or not 2 <= depth <= 6 or type(groups) is not int or not 1 <= groups <= 256
            or type(seed) is not int or not 0 <= seed <= 2**32 - 1):
        raise ValueError("registered, bounded non-overlapping cohort required")
    lexicon = NOVEL if role == "held_novel" else TRAIN
    rng = random.Random(f"hepta/v9/source/{role}/{depth}/{seed}")
    used, public, truth = set(), [], {}
    trials = 0
    while len(public) < groups * 4:
        trials += 1
        if trials > groups * 500:
            raise RuntimeError("bounded distinct source generation exhausted")
        chosen = {typ: rng.sample(lexicon[typ].split(), 2) for typ in TYPES[:depth + 1]}
        signature = digest(chosen)
        if signature in used:
            continue
        used.add(signature)
        group = len(public) // 4
        order = rng.sample(range(2 * depth), 2 * depth)
        worlds = []
        for world in range(2):
            # Object ownership swaps, every other fact stays fixed. Exactly the
            # same global word inventory appears in both worlds.
            original = []
            for level in range(depth):
                for branch in range(2):
                    destination_branch = branch ^ world if level == 0 else branch
                    original.append(VERBS[level].format(
                        a=chosen[TYPES[level]][branch],
                        b=chosen[TYPES[level + 1]][destination_branch]))
            facts = tuple(original[i] for i in order)
            worlds.append(facts)
            for answer in range(2):
                cid = f"{role}/{depth}/{group}/world-{world}/candidate-{answer}"
                case = dict(case_id=cid, source_group=f"{role}/{depth}/{group}",
                            facts=facts,
                            question=f"Where is the {chosen['object'][0]} at the {TYPES[depth]} level?",
                            candidate=f"The {chosen[TYPES[depth]][answer]} {TYPES[depth]}.")
                public.append(case)
                truth[cid] = int(answer == world)
        if Counter(" ".join(worlds[0]).split()) != Counter(" ".join(worlds[1]).split()):
            raise RuntimeError("uncontrolled word-count counterfactual")
    return public, truth


def dataset_design():
    design = {"schema": "hepta.v9.multihop-controlled.v1", "seed": 1703,
              "train_depths": [2, 3, 4], "held_depths": [2, 3, 4, 5, 6],
              "train_groups_per_depth": 24, "held_groups_per_depth": 24,
              "roles": ["train", "held_known", "held_novel"],
              "future_calendar_window": False, "real_granite_encoder_calls": 0,
              "pretrained_checkpoint_loaded": False, "natural_language_generalization": False,
              "synthetic_grammar": True, "production_accepted": False,
              "authority": "DENY_ALL", "model_selection": False}
    public, answers = [], {}
    for role in design["roles"]:
        for depth in (design["train_depths"] if role == "train" else design["held_depths"]):
            new, truth = panel(role, depth, 24)
            public.extend(new)
            if answers.keys() & truth.keys():
                raise RuntimeError("source identity collision")
            answers.update(truth)
    groups = set()
    for case in public:
        group = case["source_group"]
        groups.add(group)
        if "label" in case or "answer" in case or "support" in case:
            raise RuntimeError("answer leakage into public material")
    design["public_cases"] = len(public)
    design["independent_groups"] = len(groups)
    design["public_sha256"] = digest(public)
    design["labels_sha256"] = digest(answers)
    return design, public, answers
