use super::*;

#[test]
fn terminal_reads_revalidate_exact_conversion_and_both_audit_bytes() {
    for index in 0..3 {
        let study = must(studies::new(-0.002, 32, 6));
        let (_, loaded) = must(study.load());
        let f = &study.fixture;
        must(crate::terminal_review::verify(
            &loaded.inputs,
            &loaded.gate,
            &f.conversion,
            &f.replay,
            &f.statistics,
        ));
        let path = [&f.conversion, &f.replay, &f.statistics][index];
        let mut replacement = must(read(path));
        // Identical parsed values still constitute different committed bytes.
        // Directly exercising the second read avoids a flaky race test.
        replacement.push(b' ');
        must(fs::write(path, replacement));
        let error = crate::terminal_review::verify(
            &loaded.inputs,
            &loaded.gate,
            &f.conversion,
            &f.replay,
            &f.statistics,
        )
        .unwrap_err();
        assert!(
            error
                .to_string()
                .contains("read differs from its bound commitment")
        );
        assert!(!f.output.exists());
    }
}

#[test]
fn profile_audit_read_cannot_use_uncommitted_bytes_with_valid_profile_fields() {
    for index in 0..2 {
        let study = must(studies::new(-0.002, 32, 6));
        let (profile, loaded) = must(study.load());
        let f = &study.fixture;
        let path = [&f.replay, &f.statistics][index];
        let mut replacement = must(read(path));
        replacement.push(b' ');
        must(fs::write(path, replacement));
        let error = admission::positive("prepare", &profile, &loaded, f.paths(), &f.output, None)
            .unwrap_err();
        assert!(error.to_string().contains("profile audit read differs"));
        assert!(!f.output.exists());
    }
}
