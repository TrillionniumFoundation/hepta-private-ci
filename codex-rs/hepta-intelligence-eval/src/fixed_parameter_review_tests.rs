//! Original measured paired execution must reach final use before publication.
use super::*;
use crate::paired_supervised_test_support::{SigningFixture, Sink, inputs, runner};

#[test]
fn original_full_sink_is_not_reached_after_parameter_final_use_is_withdrawn() {
    let signing = SigningFixture::new(false);
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut owner = runner();
    let execution = owner
        .evaluate_paired_with_clock(
            &registration,
            &mut provider,
            &signing.trust,
            &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    let context = signing.context();
    let evidence = signing.evaluation(&execution, &context);
    let mut sink = Sink::default();
    let mut checks = 0;
    let mut guarded = CurrentParameterSink {
        inner: &mut sink,
        current: || -> HostResult<()> {
            checks += 1;
            Err("actual final parameter source/clock admission withdrawn".into())
        },
    };
    let result = owner.qualify_paired_with_clock(
        &execution,
        &context,
        &evidence,
        &signing.trust,
        &mut guarded,
        &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
    );
    assert!(result.is_err());
    assert_eq!(checks, 1);
    assert_eq!(sink.calls, 0);
    let mut guarded = CurrentParameterSink {
        inner: &mut sink,
        current: || -> HostResult<()> { Ok(()) },
    };
    let receipt = owner
        .qualify_paired_with_clock(
            &execution,
            &context,
            &evidence,
            &signing.trust,
            &mut guarded,
            &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    receipt.validate_integrity().unwrap();
    assert_eq!(sink.calls, 1);
    assert!(!receipt.authority.grants_any());
}
