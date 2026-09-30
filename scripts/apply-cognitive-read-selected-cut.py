#!/usr/bin/env python3
"""Apply the reviewed selected-cut integration during explicit source authoring.

This is not a runtime adapter or qualification repair. Existing source shapes
must match; the resulting ordinary Git diff is committed before qualification.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OWNER = "codex-rs/hepta-memory/src/lane_c_snapshot.rs"
MAIN = "codex-rs/hepta-agentd/src/cognitive_context.rs"
FINAL = "codex-rs/hepta-agentd/src/cognitive_context_final_use.rs"
LIB = "codex-rs/hepta-memory/src/lib.rs"


def change(body: str, old: str, new: str) -> str:
    if body.count(old) != 1:
        raise ValueError(f"selected-cut source shape mismatch: {old[:90]!r}")
    return body.replace(old, new, 1)


def owner_source(body: str) -> str:
    if "async fn lane_c_snapshot_page_inner(" in body:
        if "selected::advance_head_state" not in body or "exact_ids" not in body:
            raise ValueError("incomplete prior selected-cut integration")
        return body
    body = change(body, "use std::collections::BTreeMap;", '#[path = "lane_c_selected_snapshot.rs"]\nmod selected;\npub use selected::DurableCognitiveSelectionSnapshot;\n\nuse std::collections::BTreeMap;')
    body = change(body, "    page_digest: Digest32,\n", "    owner_state_digest: Digest32,\n    page_digest: Digest32,\n")
    body = change(body, "    pub async fn lane_c_snapshot_page(\n", "    async fn lane_c_snapshot_page_inner(\n")
    body = change(body, "        after: Option<DurableCognitiveSnapshotCursor>,\n    ) -> Result<DurableCognitiveSnapshotPage, CognitiveStoreError> {", "        after: Option<DurableCognitiveSnapshotCursor>,\n        exact_ids: Option<&[StableId]>,\n    ) -> Result<DurableCognitiveSnapshotPage, CognitiveStoreError> {")
    wrapper = '''    pub async fn lane_c_snapshot_page(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
        maximum_heads: u32,
        after: Option<DurableCognitiveSnapshotCursor>,
    ) -> Result<DurableCognitiveSnapshotPage, CognitiveStoreError> {
        self.lane_c_snapshot_page_inner(access, scope, now_unix_seconds, maximum_heads, after, None).await
    }

'''
    body = change(body, "    async fn lane_c_snapshot_page_inner(\n", wrapper + "    async fn lane_c_snapshot_page_inner(\n")
    body = change(body, '                "SELECT h.memory_id, h.revision\n', '                "SELECT h.memory_id, h.revision, r.content_sha256, r.verification, r.lifecycle,\n                        r.valid_from_unix_seconds, r.valid_to_unix_seconds\n')
    marker = '        let mut head_set_digest = Digest32::of_bytes(b"hepta.sqlite.lane-c.head-set.v1");\n'
    body = change(body, marker, marker + '        let mut head_state_digest = Digest32::of_bytes(b"hepta.sqlite.lane-c.head-states.v1");\n')
    marker = "                head_set_digest = Digest32::of_bytes(&step);\n"
    body = change(body, marker, marker + "                head_state_digest = selected::advance_head_state(head_state_digest, row, now_unix_seconds)?;\n")
    marker = "        let cut_digest = lane_c_page_cut_digest(\n"
    body = change(body, marker, '''        let owner_state_digest = lane_c_page_cut_digest(
            &scope_id,
            &frontiers,
            u64::try_from(citation_count).map_err(corrupt)?,
            head_state_digest,
            /*observed_at_unix_seconds*/ 0,
        );
''' + marker)
    start = body.index("        let after_memory_id = after\n")
    end = body.index("        let mut records = Vec::new();", start)
    original = body[start:end].rstrip()
    replacement = '''        let (head_ids, has_more) = if let Some(ids) = exact_ids {
            if after.is_some() || ids.len() > maximum_heads {
                return Err(CognitiveStoreError::Invalid("invalid exact-ID owner page".to_string()));
            }
            (ids.iter().map(|id| id.as_str().to_string()).collect::<Vec<_>>(), false)
        } else {
''' + "\n".join("    " + line for line in original.splitlines()) + '''
            (head_ids, has_more)
        };

'''
    body = body[:start] + replacement + body[end:]
    body = change(body, "            page_digest: Digest32::ZERO,\n", "            owner_state_digest,\n            page_digest: Digest32::ZERO,\n")
    return body


def main_source(body: str) -> str:
    if "use codex_hepta_memory::DurableCognitiveSelectionSnapshot as DurableCognitiveSnapshot;" in body:
        if "selected_cut" not in body or "revalidate_lane_c_selection" not in body:
            raise ValueError("incomplete prior Agentd selection integration")
        return body
    body = change(body, "use codex_hepta_memory::DurableCognitiveSnapshot;", "use codex_hepta_memory::DurableCognitiveSelectionSnapshot as DurableCognitiveSnapshot;")
    body = change(body, "    let cut = store.lane_c_snapshot(&access, &scope, now).await?;\n    let read_view = OwnerCutReadView::new(&cut).map_err(map_read_ids_error)?;\n", "")
    marker = "    record_ids.dedup();\n"
    body = change(body, marker, marker + "    let cut = store.lane_c_snapshot_ids(&access, &scope, now, &record_ids).await?;\n    let read_view = OwnerCutReadView::new(cut.owner_snapshot()).map_err(map_read_ids_error)?;\n")
    body = change(body, "            &observation,\n            &cut,\n            context,", "            &observation,\n            cut.owner_snapshot(),\n            context,")
    body = change(body, "    let selected_read = read_selected_items(&read_view, &response.items)?;\n", '''    let selected_ids = response.items.iter().map(|item| {
        StableId::new(item.memory_id.as_str()).map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
    }).collect::<Result<Vec<_>, _>>()?;
    let selected_cut = cut.select_ids(&selected_ids)?;
    let selected_view = OwnerCutReadView::new(selected_cut.owner_snapshot()).map_err(map_read_ids_error)?;
    let selected_read = read_selected_items(&selected_view, &response.items)?;
''')
    body = change(body, "bind_selected_read(&cut, &selected_read, expected_retrieval_context_digest)", "bind_selected_read(&selected_cut, &selected_read, expected_retrieval_context_digest)")
    body = change(body, ".revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)", ".revalidate_lane_c_selection(&access, &scope, &selected_cut, now_seconds()?)")
    return body


def final_source(body: str) -> str:
    if ".lane_c_snapshot_ids(" in body:
        if "cut.owner_snapshot()" not in body or ".revalidate_lane_c_selection(" not in body:
            raise ValueError("incomplete prior final-use selection integration")
        return body
    body = change(body, "use codex_hepta_types::Digest32;\n", "use codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;\n")
    body = change(body, "    let cut = store\n        .lane_c_snapshot(&access, &scope, now_seconds()?)\n        .await?;", '''    let record_ids = items.iter().map(|item| {
        StableId::new(item.memory_id.as_str()).map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
    }).collect::<Result<Vec<_>, _>>()?;
    let cut = store
        .lane_c_snapshot_ids(&access, &scope, now_seconds()?, &record_ids)
        .await?;''')
    body = change(body, "OwnerCutReadView::new(&cut)", "OwnerCutReadView::new(cut.owner_snapshot())")
    body = change(body, ".revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)", ".revalidate_lane_c_selection(&access, &scope, &cut, now_seconds()?)")
    return body


def apply() -> None:
    transforms = {OWNER: owner_source, MAIN: main_source, FINAL: final_source}
    results = {name: transform((ROOT / name).read_text()) for name, transform in transforms.items()}
    body = (ROOT / LIB).read_text()
    new_export = "pub use lane_c_snapshot::DurableCognitiveSelectionSnapshot;\n"
    if new_export not in body:
        body = change(body, "pub use lane_c_snapshot::DurableCognitiveSnapshot;\n", new_export + "pub use lane_c_snapshot::DurableCognitiveSnapshot;\n")
    results[LIB] = body
    for name, content in results.items():
        (ROOT / name).write_text(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) or actual != args.expected_sha:
        raise ValueError("selected-cut authoring requires the exact source commit")
    apply()


if __name__ == "__main__":
    main()
