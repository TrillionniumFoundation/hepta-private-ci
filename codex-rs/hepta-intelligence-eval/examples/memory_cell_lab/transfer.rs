//! Artifact-only transport exercises. The current revocation view is separate
//! from the copied model and never inferred from its learned parameters.
use super::data::{Episode, Query, Split};
use super::model::{Bundle, argmax};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

fn read_bounded(path: &Path) -> Result<String, String> {
    let mut text = String::new();
    File::open(path)
        .map_err(|e| e.to_string())?
        .take(4 * 1024 * 1024 + 1)
        .read_to_string(&mut text)
        .map_err(|e| e.to_string())?;
    if text.len() > 4 * 1024 * 1024 {
        return Err("transfer input byte limit".into());
    }
    Ok(text)
}

pub fn export(
    bundle: &Bundle,
    rows: &[Episode],
    dir: &Path,
    expected: &Path,
) -> Result<(), String> {
    fs::create_dir(dir).map_err(|e| e.to_string())?;
    fs::write(dir.join("model.bundle"), bundle.encode()).map_err(|e| e.to_string())?;
    let mut queries = String::from("MCELL-QUERIES-LAB-1\n");
    for row in rows.iter().filter(|r| r.split == Split::FutureA) {
        queries.push_str(&format!(
            "{}\t{}\t{}\t{}\n",
            row.id, row.query.scope, row.query.domain, row.query.text
        ));
    }
    fs::write(dir.join("queries.tsv"), queries).map_err(|e| e.to_string())?;
    infer(dir, expected, None)
}

pub fn infer(dir: &Path, output: &Path, revocations: Option<&Path>) -> Result<(), String> {
    let bundle = Bundle::decode(&read_bounded(&dir.join("model.bundle"))?)?;
    if let Some(path) = revocations {
        let content = read_bounded(path)?;
        let mut lines = content.lines();
        if lines.next() != Some("MCELL-REVOCATIONS-LAB-1") {
            return Err("revocation view version".into());
        }
        let mut revoked = BTreeSet::new();
        for root in lines {
            if root.is_empty() || root.len() > 8192 || !revoked.insert(root.to_owned()) {
                return Err("revocation view shape".into());
            }
        }
        if !bundle.roots.is_disjoint(&revoked) {
            return Err("revoked training root".into());
        }
    }
    let text = read_bounded(&dir.join("queries.tsv"))?;
    let mut lines = text.lines();
    if lines.next() != Some("MCELL-QUERIES-LAB-1") {
        return Err("query view version".into());
    }
    let mut output_text = String::from("episode\tsemantic\tprocedure\n");
    let mut ids = BTreeSet::new();
    for line in lines {
        let f: Vec<_> = line.split('\t').collect();
        if f.len() != 4 || f.iter().any(|s| s.is_empty() || s.len() > 8192) || !ids.insert(f[0]) {
            return Err("query view shape".into());
        }
        let query = Query {
            scope: f[1].into(),
            domain: f[2].parse().map_err(|_| "query domain")?,
            text: f[3].into(),
        };
        let p = bundle.infer(&query)?;
        output_text.push_str(&format!("{}\t{}\t{}\n", f[0], argmax(&p[0]), argmax(&p[1])));
    }
    if ids.is_empty() || ids.len() > 20_000 {
        return Err("query count bound".into());
    }
    // Revalidate all inputs before publishing any output; never overwrite an old receipt.
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)
        .map_err(|e| e.to_string())?;
    file.write_all(output_text.as_bytes())
        .and_then(|_| file.sync_all())
        .map_err(|e| e.to_string())
}
