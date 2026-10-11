//! Lossless complete-hash table for bounded combined cognitive attachments.
use serde_json::Value;
use serde_json::json;

pub(super) fn intern_combined_digests(memories: &mut [Value]) -> Option<Vec<String>> {
    fn intern(value: &mut Value, digests: &mut Vec<String>) -> Option<()> {
        let text = value.as_str()?;
        if text.len() != 64 || !text.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return None;
        }
        let index = match digests.iter().position(|known| known == text) {
            Some(index) => index,
            None => {
                digests.push(text.to_owned());
                digests.len() - 1
            }
        };
        *value = json!(index);
        Some(())
    }
    let mut digests = Vec::new();
    for memory in memories {
        intern(memory.get_mut("h")?, &mut digests)?;
        for citation in memory.get_mut("q")?.as_array_mut()? {
            intern(citation.get_mut("h")?, &mut digests)?;
        }
    }
    Some(digests)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    #[test]
    fn combined_digest_table_preserves_every_exact_hash_and_citation() {
        let a = "11".repeat(32);
        let b = "22".repeat(32);
        let original = vec![
            json!({"m": "local", "h": a, "q": [{"s": "source-a", "h": a}]}),
            json!({"a": "00000000-0000-4000-8000-000000000712", "m": "remote", "h": b, "q": [{"s": "source-b", "h": b}]}),
        ];
        let mut compact = original.clone();
        let table = super::intern_combined_digests(&mut compact).expect("valid full hashes");
        assert_eq!(table, vec![a, b]);
        assert_eq!(compact[0]["h"], compact[0]["q"][0]["h"]);
        for memory in &mut compact {
            let index = memory["h"].as_u64().expect("digest index") as usize;
            memory["h"] = json!(table[index]);
            for citation in memory["q"].as_array_mut().expect("citations") {
                let index = citation["h"].as_u64().expect("citation digest index") as usize;
                citation["h"] = json!(table[index]);
            }
        }
        assert_eq!(compact, original);
        for invalid in ["", "ab", "not-a-digest"] {
            let mut malformed = vec![json!({"h": invalid, "q": []})];
            assert!(super::intern_combined_digests(&mut malformed).is_none());
        }
    }
}
