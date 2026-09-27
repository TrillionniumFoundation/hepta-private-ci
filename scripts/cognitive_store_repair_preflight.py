#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "cognitive_store_one_shot_repair.py"
text = path.read_text(encoding="utf-8")
old_marker = '''        "    pub async fn revalidate_lane_c_snapshot(\\n",\n'''
new_marker = '''        "    pub async fn revalidate_lane_c_snapshot(\\n        &self,\\n        access: &CognitiveAccess,\\n",\n'''
old_tail = '''    pub async fn revalidate_lane_c_snapshot(\n""",\n    )\n\n    replace(\n        "codex-rs/hepta-agentd/src/state.rs",\n'''
new_tail = '''    pub async fn revalidate_lane_c_snapshot(\n        &self,\n        access: &CognitiveAccess,\n""",\n    )\n\n    replace(\n        "codex-rs/hepta-agentd/src/state.rs",\n'''
for old, new, label in (
    (old_marker, new_marker, "exact read-facade marker"),
    (old_tail, new_tail, "preserved read-facade signature"),
):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one repair-script anchor, found {count}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
