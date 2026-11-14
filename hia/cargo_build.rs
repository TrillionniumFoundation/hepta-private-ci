// Shared build-script support. Validates input/artifact identity, not compiler
// correctness or authenticity against a malicious owner of the whole build.

const HIA_LINK_FIELDS: &[&str] = &[
    "module",
    "target",
    "mode",
    "revision",
    "symbol",
    "object",
    "archive",
    "archive_member",
    "source_sha256",
    "toolchain_lock_sha256",
    "build_driver_sha256",
    "cargo_helper_sha256",
    "object_sha256",
    "text_sha256",
    "archive_sha256",
    "compiler_sha256",
    "build_report_sha256",
];

fn hia_sha256(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut state = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut padded = data.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for chunk in padded.chunks_exact(64) {
        let mut words = [0u32; 64];
        for (word, bytes) in words[..16].iter_mut().zip(chunk.chunks_exact(4)) {
            *word = u32::from_be_bytes(
                bytes
                    .try_into()
                    .unwrap_or_else(|_| panic!("four-byte SHA word")),
            );
        }
        for i in 16..64 {
            let x = words[i - 15];
            let y = words[i - 2];
            let s0 = x.rotate_right(7) ^ x.rotate_right(18) ^ (x >> 3);
            let s1 = y.rotate_right(17) ^ y.rotate_right(19) ^ (y >> 10);
            words[i] = words[i - 16]
                .wrapping_add(s0)
                .wrapping_add(words[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ ((!e) & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(choose)
                .wrapping_add(K[i])
                .wrapping_add(words[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(majority);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (word, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *word = word.wrapping_add(value);
        }
    }
    state.iter().map(|word| format!("{word:08x}")).collect()
}

fn hia_read(path: &std::path::Path) -> Vec<u8> {
    println!("cargo:rerun-if-changed={}", path.display());
    let metadata = std::fs::metadata(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    assert!(
        metadata.is_file() && metadata.len() <= 32 * 1024 * 1024,
        "invalid HIA build input"
    );
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    assert!(
        data.len() <= 32 * 1024 * 1024,
        "HIA build input exceeds limit"
    );
    data
}

fn hia_checked(path: &std::path::Path, expected: &str) -> Vec<u8> {
    assert!(
        expected.len() == 64
            && expected
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "invalid lowercase SHA256"
    );
    let data = hia_read(path);
    assert_eq!(
        hia_sha256(&data),
        expected,
        "HIA input changed: {}",
        path.display()
    );
    data
}

fn hia_json_field(text: &str, key: &str) -> String {
    // The builder uses indent=2. Nested child reports cannot satisfy a root field.
    let prefix = format!("  \"{key}\": ");
    let values: Vec<_> = text
        .lines()
        .filter_map(|line| line.strip_prefix(&prefix))
        .collect();
    assert_eq!(values.len(), 1, "missing or duplicate HIA JSON field {key}");
    values[0].strip_suffix(',').unwrap_or(values[0]).to_owned()
}

fn hia_archive_member(data: &[u8]) -> &[u8] {
    assert!(
        data.starts_with(b"!<arch>\n"),
        "expected ordinary static archive"
    );
    let mut at = 8usize;
    let mut member = None;
    let mut indexes = 0;
    while at < data.len() {
        let header = data
            .get(
                at..at
                    .checked_add(60)
                    .unwrap_or_else(|| panic!("archive header overflow")),
            )
            .unwrap_or_else(|| panic!("truncated archive"));
        assert_eq!(&header[58..], b"`\n", "invalid archive header");
        let name = std::str::from_utf8(&header[..16])
            .unwrap_or_else(|_| panic!("ASCII member"))
            .trim_end_matches(' ');
        let size_text = std::str::from_utf8(&header[48..58])
            .unwrap_or_else(|_| panic!("ASCII member length"))
            .trim_matches(' ');
        assert!(
            !size_text.is_empty() && size_text.bytes().all(|b| b.is_ascii_digit()),
            "bad archive length"
        );
        let size: usize = size_text
            .parse()
            .unwrap_or_else(|_| panic!("archive size overflow"));
        at += 60;
        let end = at
            .checked_add(size)
            .unwrap_or_else(|| panic!("archive offset overflow"));
        let bytes = data
            .get(at..end)
            .unwrap_or_else(|| panic!("truncated archive payload"));
        match name {
            "/" => {
                indexes += 1;
                assert!(indexes <= 1, "duplicate archive index");
            }
            "hia.o/" => {
                assert!(member.is_none(), "duplicate HIA object");
                member = Some(bytes);
            }
            _ => panic!("unexpected static archive member {name}"),
        }
        if size % 2 == 1 {
            assert_eq!(data.get(end), Some(&b'\n'), "invalid archive padding");
        }
        at = end
            .checked_add(size % 2)
            .unwrap_or_else(|| panic!("archive padding overflow"));
    }
    assert_eq!(at, data.len());
    member.unwrap_or_else(|| panic!("missing HIA object"))
}

fn hia_word(data: &[u8], at: usize, width: usize) -> usize {
    let bytes = data
        .get(
            at..at
                .checked_add(width)
                .unwrap_or_else(|| panic!("ELF offset overflow")),
        )
        .unwrap_or_else(|| panic!("truncated ELF"));
    let mut value = 0u64;
    for (shift, byte) in bytes.iter().enumerate() {
        value |= u64::from(*byte) << (shift * 8);
    }
    usize::try_from(value).unwrap_or_else(|_| panic!("ELF value exceeds host address width"))
}

fn hia_object_text<'a>(data: &'a [u8], symbol: &str) -> &'a [u8] {
    assert!(
        data.starts_with(b"\x7fELF\x02\x01\x01"),
        "expected ELF64 little-endian"
    );
    assert_eq!(hia_word(data, 16, 2), 1, "expected ET_REL");
    assert_eq!(hia_word(data, 18, 2), 62, "expected x86-64 object");
    assert_eq!(hia_word(data, 58, 2), 64, "ELF section width");
    let table = hia_word(data, 40, 8);
    let count = hia_word(data, 60, 2);
    let names = hia_word(data, 62, 2);
    assert!(
        count == 6 && names < count,
        "unexpected ELF section inventory"
    );
    let mut sections = Vec::new();
    for i in 0..count {
        let at = table
            .checked_add(i * 64)
            .unwrap_or_else(|| panic!("ELF table overflow"));
        sections.push((
            hia_word(data, at, 4),
            hia_word(data, at + 4, 4),
            hia_word(data, at + 8, 8),
            hia_word(data, at + 24, 8),
            hia_word(data, at + 32, 8),
            hia_word(data, at + 40, 4),
            hia_word(data, at + 56, 8),
        ));
    }
    let slice = |offset: usize, length: usize| {
        data.get(
            offset
                ..offset
                    .checked_add(length)
                    .unwrap_or_else(|| panic!("ELF range overflow")),
        )
        .unwrap_or_else(|| panic!("ELF range outside file"))
    };
    let strings = slice(sections[names].3, sections[names].4);
    let mut text = None;
    let mut symbols = None;
    let mut seen = std::collections::BTreeSet::new();
    for (i, row) in sections.iter().enumerate() {
        let tail = strings
            .get(row.0..)
            .unwrap_or_else(|| panic!("ELF section name outside strings"));
        let end = tail
            .iter()
            .position(|b| *b == 0)
            .unwrap_or_else(|| panic!("ELF section name terminator"));
        let name =
            std::str::from_utf8(&tail[..end]).unwrap_or_else(|_| panic!("ELF section name UTF8"));
        assert!(seen.insert(name), "duplicate ELF section name");
        match name {
            "" => assert_eq!(i, 0),
            ".text" => {
                assert!(row.1 == 1 && row.2 == 6 && row.4 > 0);
                text = Some(i);
            }
            ".symtab" => {
                assert_eq!(row.1, 2);
                symbols = Some(i);
            }
            ".strtab" | ".shstrtab" => assert_eq!(row.1, 3),
            ".note.GNU-stack" => assert!(row.1 == 1 && row.2 == 0 && row.4 == 0),
            _ => panic!("unexpected ELF section {name}"),
        }
        let _ = slice(row.3, row.4);
    }
    let text_index = text.unwrap_or_else(|| panic!("missing ELF text"));
    let sym = sections[symbols.unwrap_or_else(|| panic!("missing ELF symbols"))];
    assert!(sym.6 == 24 && sym.4 % 24 == 0 && sym.5 < count);
    let names_row = sections[sym.5];
    assert_eq!(names_row.1, 3);
    let names_data = slice(names_row.3, names_row.4);
    let mut exported = 0;
    for entry in slice(sym.3, sym.4).chunks_exact(24) {
        let binding = entry[4] >> 4;
        assert!(binding <= 1, "weak or unsupported ELF symbol");
        if binding == 0 {
            continue;
        }
        let name_at = hia_word(entry, 0, 4);
        let name = names_data
            .get(name_at..)
            .unwrap_or_else(|| panic!("symbol string offset"));
        let end = name
            .iter()
            .position(|b| *b == 0)
            .unwrap_or_else(|| panic!("symbol string terminator"));
        assert_eq!(&name[..end], symbol.as_bytes(), "unexpected native symbol");
        assert_eq!(entry[4] & 15, 2, "symbol must be a function");
        assert_eq!(
            hia_word(entry, 6, 2),
            text_index,
            "undefined or non-text symbol"
        );
        let start = hia_word(entry, 8, 8);
        let length = hia_word(entry, 16, 8);
        assert!(
            length > 0
                && start <= sections[text_index].4
                && length <= sections[text_index].4 - start
        );
        exported += 1;
    }
    assert_eq!(exported, 1, "expected one unique HIA export");
    let row = sections[text_index];
    slice(row.3, row.4)
}

/// Validate current HIA sources and exact static build, then link captured bytes.
/// Call only when the native feature and supported target are selected.
pub fn link_native(module: &str) {
    if std::env::var_os("CARGO_FEATURE_HIA_NATIVE").is_none() {
        return;
    }
    for (key, value) in [
        ("CARGO_CFG_TARGET_OS", "linux"),
        ("CARGO_CFG_TARGET_ARCH", "x86_64"),
        ("CARGO_CFG_TARGET_ENV", "gnu"),
        ("CARGO_CFG_TARGET_POINTER_WIDTH", "64"),
        ("CARGO_CFG_TARGET_ENDIAN", "little"),
    ] {
        assert_eq!(
            std::env::var(key).as_deref(),
            Ok(value),
            "unsupported HIA target {key}"
        );
    }
    assert!(
        !module.is_empty()
            && module
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
    );
    println!("cargo:rerun-if-env-changed=CODEX_HIA_NATIVE_LIB_DIR");
    let dir = std::path::PathBuf::from(
        std::env::var_os("CODEX_HIA_NATIVE_LIB_DIR")
            .unwrap_or_else(|| panic!("HIA feature requires CODEX_HIA_NATIVE_LIB_DIR")),
    );
    let manifest = std::path::PathBuf::from(
        std::env::var_os("CARGO_MANIFEST_DIR")
            .unwrap_or_else(|| panic!("Cargo manifest directory")),
    );
    let root = manifest
        .ancestors()
        .find(|p| p.join("hia/toolchain.json").is_file())
        .unwrap_or_else(|| panic!("HIA source root"))
        .join("hia");
    let receipt_bytes = hia_read(&dir.join(format!("{module}.link")));
    assert!(
        receipt_bytes.is_ascii()
            && !receipt_bytes.contains(&b'\r')
            && receipt_bytes.ends_with(b"\n"),
        "noncanonical link receipt"
    );
    let receipt = std::str::from_utf8(&receipt_bytes).unwrap_or_else(|_| panic!("ASCII receipt"));
    let lines: Vec<_> = receipt
        .strip_suffix('\n')
        .unwrap_or_else(|| panic!("receipt newline"))
        .split('\n')
        .collect();
    assert_eq!(lines[0], "codex.hia.static-link.v1");
    assert_eq!(
        lines.len(),
        HIA_LINK_FIELDS.len() + 1,
        "link receipt field count"
    );
    let mut fields = std::collections::BTreeMap::new();
    for (key, line) in HIA_LINK_FIELDS.iter().zip(&lines[1..]) {
        let value = line
            .strip_prefix(&format!("{key}="))
            .unwrap_or_else(|| panic!("receipt field order"));
        assert!(!value.is_empty(), "empty link receipt field");
        fields.insert(*key, value);
    }
    let get = |key| *fields.get(key).unwrap_or_else(|| panic!("receipt field"));
    let symbol = format!("codex_hia_{module}");
    let object_name = format!("{module}.namespaced.o");
    let archive_name = format!("lib{symbol}.a");
    for (key, expected) in [
        ("module", module),
        ("mode", "native-selfhost"),
        ("target", "x86_64-unknown-linux-gnu"),
        ("symbol", &symbol),
        ("object", &object_name),
        ("archive", &archive_name),
        ("archive_member", "hia.o"),
    ] {
        assert_eq!(get(key), expected, "incorrect HIA receipt {key}");
    }
    let lock = hia_checked(&root.join("toolchain.json"), get("toolchain_lock_sha256"));
    let lock_text = std::str::from_utf8(&lock).unwrap_or_else(|_| panic!("toolchain JSON UTF8"));
    assert_eq!(
        hia_json_field(lock_text, "revision"),
        format!("\"{}\"", get("revision"))
    );
    assert_eq!(
        hia_json_field(lock_text, "target"),
        format!("\"{}\"", get("target"))
    );
    hia_checked(&root.join(format!("{module}.hepta")), get("source_sha256"));
    hia_checked(&root.join("build.py"), get("build_driver_sha256"));
    hia_checked(&root.join("cargo_build.rs"), get("cargo_helper_sha256"));
    let report = hia_checked(&dir.join("build.json"), get("build_report_sha256"));
    let report = std::str::from_utf8(&report).unwrap_or_else(|_| panic!("build JSON UTF8"));
    for (key, expected) in [
        ("status", "\"built\""),
        ("build_mode", "\"native-selfhost\""),
        ("compiler_fixed_point", "true"),
    ] {
        assert_eq!(
            hia_json_field(report, key),
            expected,
            "unqualified HIA build field {key}"
        );
    }
    for key in [
        "toolchain_lock_sha256",
        "build_driver_sha256",
        "cargo_helper_sha256",
        "compiler_sha256",
    ] {
        assert_eq!(
            hia_json_field(report, key),
            format!("\"{}\"", get(key)),
            "build/receipt disagreement"
        );
    }
    for generation in ["B1", "B2", "B3"] {
        hia_checked(
            &dir.join("bootstrap")
                .join(format!("{generation}.image.bin")),
            get("compiler_sha256"),
        );
    }
    let object = hia_checked(&dir.join(&object_name), get("object_sha256"));
    assert_eq!(
        hia_sha256(hia_object_text(&object, &symbol)),
        get("text_sha256")
    );
    let archive = hia_checked(&dir.join(&archive_name), get("archive_sha256"));
    assert_eq!(
        hia_archive_member(&archive),
        object,
        "archive/object disagreement"
    );
    // Link captured bytes from Cargo's directory, not the mutable source path.
    let out = std::path::PathBuf::from(
        std::env::var_os("OUT_DIR").unwrap_or_else(|| panic!("Cargo output directory")),
    );
    std::fs::create_dir_all(&out).unwrap_or_else(|_| panic!("create Cargo output directory"));
    let staged = out.join(&archive_name);
    std::fs::write(&staged, &archive).unwrap_or_else(|_| panic!("stage checked HIA archive"));
    assert_eq!(
        std::fs::read(&staged).unwrap_or_else(|_| panic!("read staged archive")),
        archive
    );
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static={symbol}");
}
