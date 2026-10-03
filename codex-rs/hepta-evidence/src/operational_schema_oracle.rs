//! Complete definitions for the two frozen, CREATE-only operational migrations.
//!
//! These declarations are deliberately derived from compiled migration bytes.
//! The final migration14 backfill INSERT is not part of its preceding trigger.
//! This is not a parser for arbitrary caller-provided SQL or future ALTERs.

use crate::EvidenceError;

const MIGRATIONS: [&str; 2] = [
    include_str!("../migrations/0014_evidence_publication.sql"),
    include_str!("../migrations/0015_evidence_trust_acceptance.sql"),
];

pub(super) fn verify_definition(name: &str, kind: &str, actual: &str) -> Result<(), EvidenceError> {
    let expected = compiled_definition(name, kind)?;
    if normalize(actual) != normalize(expected) {
        return Err(corrupt(
            "operational schema differs from its compiled migration",
        ));
    }
    Ok(())
}

fn compiled_definition(name: &str, kind: &str) -> Result<&'static str, EvidenceError> {
    let keyword = match kind {
        "table" => "TABLE",
        "index" => "INDEX",
        "trigger" => "TRIGGER",
        _ => return Err(corrupt("unknown operational schema object kind")),
    };
    let marker = format!("CREATE {keyword} {name}");
    let mut definition = None;
    for migration in MIGRATIONS {
        for (start, _) in migration.match_indices(&marker) {
            // Governed declarations start at column zero. Do not mistake a
            // comment or a longer object's shared name prefix for this object.
            if start != 0 && migration.as_bytes().get(start - 1) != Some(&b'\n') {
                continue;
            }
            let tail = &migration[start..];
            if !tail
                .as_bytes()
                .get(marker.len())
                .is_some_and(u8::is_ascii_whitespace)
            {
                continue;
            }
            // Both frozen migrations have ordinary table/index statements and
            // trigger bodies ending in an unindented END; no nested CASE/END.
            // Keep internal trigger semicolons and exclude later DML/backfill.
            let end = if kind == "trigger" {
                tail.find("\nEND;").map(|offset| offset + "\nEND".len())
            } else {
                tail.find(';')
            }
            .ok_or_else(|| corrupt("compiled operational definition is incomplete"))?;
            if definition.replace(&tail[..end]).is_some() {
                return Err(corrupt("compiled operational definition is duplicated"));
            }
        }
    }
    definition.ok_or_else(|| corrupt("compiled operational definition is missing"))
}

fn normalize(sql: &str) -> String {
    // SQLite preserves these original CREATE statements apart from layout and
    // the final semicolon. Do not erase comments or lowercase string literals:
    // either can hide a changed CHECK, WHEN condition or trigger body.
    // Keep quoted whitespace byte-for-byte as well. Layout normalization must
    // never change literal values, even if the current fragments ignore them.
    let sql = sql.trim();
    let sql = sql.strip_suffix(';').unwrap_or(sql).trim_end();
    let mut normalized = String::with_capacity(sql.len());
    let mut quote = None;
    let mut pending_space = false;
    let mut characters = sql.chars().peekable();
    while let Some(character) = characters.next() {
        if let Some(delimiter) = quote {
            normalized.push(character);
            if character == delimiter {
                if characters.peek() == Some(&delimiter) {
                    normalized.push(delimiter);
                    characters.next();
                } else {
                    quote = None;
                }
            }
        } else if character.is_ascii_whitespace() {
            pending_space = true;
        } else {
            if pending_space && !normalized.is_empty() {
                normalized.push(' ');
            }
            pending_space = false;
            normalized.push(character);
            quote = match character {
                '\'' | '"' | '`' => Some(character),
                '[' => Some(']'),
                _ => None,
            };
        }
    }
    normalized
}

fn corrupt(reason: &str) -> EvidenceError {
    EvidenceError::Corrupt(reason.to_string())
}
