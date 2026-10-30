use std::path::Path;

fn main() -> anyhow::Result<()> {
    let out = Path::new(env!("CARGO_MANIFEST_DIR")).join("../core/config.schema.json");
    codex_config::schema::write_config_schema(&out)
}
