use super::find_native_python_with_probe;
use super::parse_native_python;
use pretty_assertions::assert_eq;

#[test]
fn prefers_native_primary_and_preserves_resolved_unicode_path() -> anyhow::Result<()> {
    let mut candidates = Vec::new();
    let resolved = find_native_python_with_probe(|candidate| {
        candidates.push(candidate.to_owned());
        Ok("cpython\r\nwin32\r\nnt\r\nC:\\工具\\Python\\python.exe\r\n".to_owned())
    })?;
    assert_eq!(
        (resolved, candidates),
        (
            "C:\\工具\\Python\\python.exe".to_owned(),
            vec!["python.exe".to_owned()],
        )
    );
    Ok(())
}

#[test]
fn rejects_non_native_and_ambiguous_probe_outputs() {
    for output in [
        "cpython\nmsys\nposix\n/usr/bin/python3\n",
        "cpython\ncygwin\nposix\n/usr/bin/python3\n",
        "cpython\nlinux\nposix\n/usr/bin/python3\n",
        "cpython\nwin32\nposix\nC:\\Python\\python.exe\n",
        "pypy\nwin32\nnt\nC:\\Python\\python.exe\n",
        "cpython\nwin32\nnt\n",
        "cpython\nwin32\nnt\npython.exe\n",
        "cpython\nwin32\nnt\nC:python.exe\n",
        "cpython\nwin32\nnt\nC:\\Python\\python.exe\nextra\n",
        "cpython\nwin32\nnt\nC:\\Python\\python\0.exe\n",
    ] {
        assert!(parse_native_python(output).is_err(), "accepted {output:?}");
    }
}

#[test]
fn verifies_alias_only_after_primary_failure() -> anyhow::Result<()> {
    let mut candidates = Vec::new();
    let resolved = find_native_python_with_probe(|candidate| {
        candidates.push(candidate.to_owned());
        match candidate {
            "python.exe" => Err("unavailable".to_owned()),
            "python3.exe" => Ok("cpython\nwin32\nnt\n\\\\host\\share\\python.exe\n".to_owned()),
            unexpected => panic!("unexpected probe candidate {unexpected}"),
        }
    })?;
    assert_eq!(
        (resolved, candidates),
        (
            "\\\\host\\share\\python.exe".to_owned(),
            vec!["python.exe".to_owned(), "python3.exe".to_owned()],
        )
    );
    Ok(())
}

#[test]
fn reports_failure_when_only_posix_runtimes_exist() {
    let error =
        find_native_python_with_probe(
            |_| Ok("cpython\nmsys\nposix\n/usr/bin/python3\n".to_owned()),
        )
        .expect_err("a POSIX interpreter does not exercise Native ReadConsoleW");
    let message = error.to_string();
    assert!(message.contains("python.exe:"));
    assert!(message.contains("python3.exe:"));
    assert!(message.contains("requires native CPython"));
}
