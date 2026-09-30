#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


workflow = ".github/workflows/channel-matrix-preserve-unknown.yml"
tool_step = """      - name: Install pinned repository test tools
        uses: taiki-e/install-action@44c6d64aa62cd779e873306675c7a58e86d6d532
        with:
          tool: just@1.51.0,nextest@0.9.103
"""
replace_once(
    workflow,
    "      - name: Resolve immutable identities\n",
    tool_step + "      - name: Resolve immutable identities\n",
)
replace_once(
    workflow,
    "      - name: Materialize deterministic base merge\n",
    tool_step + "      - name: Materialize deterministic base merge\n",
)

content_binding = "codex-rs/hepta-matrix-store/tests/content_binding.rs"
replace_once(
    content_binding,
    "use codex_hepta_paths::HeptaAgentLayout;\nuse codex_hepta_paths::HeptaFleetRoot;\nuse pretty_assertions::assert_eq;\nuse sqlx::Connection;\nuse sqlx::SqliteConnection;\nuse sqlx::sqlite::SqliteConnectOptions;\n",
    "use codex_hepta_paths::HeptaAgentLayout;\nuse codex_hepta_paths::HeptaFleetRoot;\nuse codex_state::SqliteConfig;\nuse codex_utils_absolute_path::AbsolutePathBuf;\nuse pretty_assertions::assert_eq;\n",
)
replace_once(
    content_binding,
    """    let options = SqliteConnectOptions::new().filename(store.path());
    let mut connection = SqliteConnection::connect_with(&options).await?;
    sqlx::query(\"DROP TRIGGER matrix_dispatch_content_bindings_no_update\")
        .execute(&mut connection)
        .await?;
    sqlx::query(\"CREATE TRIGGER matrix_dispatch_content_bindings_no_update BEFORE UPDATE ON matrix_dispatch_content_bindings BEGIN SELECT 1; END\")
        .execute(&mut connection).await?;
    connection.close().await?;
""",
    """    let path = store.path();
    let parent = path
        .parent()
        .ok_or_else(|| std::io::Error::other(\"matrix store parent is missing\"))?;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(parent.to_path_buf())?);
    let pool = sqlite.open_durable_evidence_pool(path).await?;
    sqlx::query(\"DROP TRIGGER matrix_dispatch_content_bindings_no_update\")
        .execute(&pool)
        .await?;
    sqlx::query(\"CREATE TRIGGER matrix_dispatch_content_bindings_no_update BEFORE UPDATE ON matrix_dispatch_content_bindings BEGIN SELECT 1; END\")
        .execute(&pool)
        .await?;
    pool.close().await;
""",
)

replace_once(
    "codex-rs/hepta-matrix-sdk/tests/final_poll_regressions.rs",
    "    let reopened = MatrixDurableStore::open(&layout(&temp)?, MatrixDurableConfig::default()).await?;\n",
    "    let reopened =\n        MatrixDurableStore::open(&layout(&temp)?, MatrixDurableConfig::default()).await?;\n",
)
replace_once(
    "codex-rs/hepta-matrixd/src/final_use.rs",
    """            if head.authority_epoch == current.authority_epoch
                && head.revision == current.revision
            {
""",
    """            if head.authority_epoch == current.authority_epoch && head.revision == current.revision
            {
""",
)

doc_test = "scripts/tests/test_channel_matrix_documentation.py"
doc_method = '''
    def test_all_matrix_qualification_workflows_are_read_only(self) -> None:
        workflows = sorted((ROOT / ".github/workflows").glob("channel-matrix-*.yml"))
        self.assertTrue(workflows)
        for workflow in workflows:
            source = workflow.read_text(encoding="utf-8")
            self.assertNotIn("contents: write", source, workflow.name)
            self.assertNotIn("git push", source, workflow.name)
        self.assertFalse((ROOT / ".github/channel-matrix-repair.py").exists())
        self.assertFalse((ROOT / ".matrix-staging").exists())

'''
replace_once(doc_test, '\n\nif __name__ == "__main__":\n', "\n" + doc_method + '\nif __name__ == "__main__":\n')

for relative in (
    ".github/channel-matrix-one-shot-finalize.py",
    ".github/workflows/channel-matrix-one-shot-finalize.yml",
):
    (ROOT / relative).unlink()
