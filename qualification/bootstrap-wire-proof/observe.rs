
// Qualification-only byte observer. No wire bytes leave this process, and the
// constructed V2 document is neither sealed nor submitted to an owner.
fn check_bootstrap_wire(
    offer: &crate::RootGenerationPublicationOfferV1,
    descriptor: &DeploymentData,
    descriptor_path: &Path,
) -> io::Result<()> {
    use crate::authority_host_service::generation_publication::{
        PublicationVersion, decode_original_publication_bootstrap, encode_original_publication_bootstrap,
    };
    use std::os::unix::fs::FileExt;

    let len = usize::try_from(offer.bootstrap.metadata()?.len()).map_err(io::Error::other)?;
    assert!((1..=65_536).contains(&len));
    let mut raw = vec![0; len];
    offer.bootstrap.read_exact_at(&mut raw, 0)?;
    let (mut route, legacy_prepared) = decode_original_publication_bootstrap(&raw)?;
    assert!(legacy_prepared.is_none());
    assert_eq!(route.purpose, PublicationVersion::LegacyV1.purpose());
    assert_eq!(encode_original_publication_bootstrap(&route, None)?, raw);
    let legacy_json = serde_json::to_value(&route)?;

    let metadata = fs::metadata(descriptor_path)?;
    let prepared_json = serde_json::json!({
        "inputs": descriptor.original_input_data(),
        "material": {
            "path": descriptor_path,
            "device": metadata.dev(), "inode": metadata.ino(), "uid": metadata.uid(),
            "gid": metadata.gid(), "mode": metadata.mode(),
        },
        "successor": PreparedPublicationData::component_successor_wire_fixture()?,
    });
    let prepared: PreparedPublicationData = serde_json::from_value(prepared_json.clone())?;
    assert!(encode_original_publication_bootstrap(&route, Some(&prepared)).is_err());
    route.purpose = PublicationVersion::DurableV2.purpose().into();
    assert!(encode_original_publication_bootstrap(&route, None).is_err());
    let wire = encode_original_publication_bootstrap(&route, Some(&prepared))?;
    let envelope: serde_json::Value = serde_json::from_slice(&wire)?;
    let route_json = serde_json::to_value(&route)?;
    assert_eq!(envelope, serde_json::json!({"schema": 2, "route": route_json, "prepared": prepared_json}));
    let (restored, restored_prepared) = decode_original_publication_bootstrap(&wire)?;
    assert_eq!(serde_json::to_value(&restored)?, route_json);
    assert_eq!(serde_json::to_value(restored_prepared.as_ref())?, prepared_json);
    assert_eq!(encode_original_publication_bootstrap(&restored, restored_prepared.as_ref())?, wire);

    let reject = |changed: serde_json::Value, name: &str| -> io::Result<()> {
        assert!(decode_original_publication_bootstrap(&serde_json::to_vec(&changed)?).is_err(), "{name}");
        Ok(())
    };
    reject(route_json, "bare V2")?;
    let mut hybrid = legacy_json.clone();
    hybrid["schema"] = 2.into();
    reject(hybrid, "legacy with V2 schema")?;
    let mut hybrid = envelope.clone();
    hybrid["route"] = legacy_json;
    reject(hybrid, "enveloped V1")?;
    for (pointer, name, value) in [
        ("/schema", "wrong schema", serde_json::json!(1)),
        ("/prepared", "null preparation", serde_json::Value::Null),
        ("/route/purpose", "unknown purpose", serde_json::json!("wire-fixture/unknown")),
    ] {
        let mut changed = envelope.clone();
        *changed.pointer_mut(pointer).expect("known field") = value;
        reject(changed, name)?;
    }
    for (pointer, field) in [("", "schema"), ("", "prepared"), ("/prepared", "material"),
        ("/prepared", "inputs"), ("/prepared", "successor"), ("/prepared/successor", "source_configuration")] {
        let mut changed = envelope.clone();
        assert!(changed.pointer_mut(pointer).and_then(serde_json::Value::as_object_mut)
            .expect("known object").remove(field).is_some());
        reject(changed, field)?;
    }
    for pointer in ["", "/route", "/prepared", "/prepared/successor"] {
        let mut changed = envelope.clone();
        changed.pointer_mut(pointer).expect("known object")["unknown_wire_field"] = true.into();
        reject(changed, pointer)?;
    }
    eprintln!("QUALIFIED_WIRE_OBJECT v1-positive=1 v2-positive=1 encoder-negative=2 decoder-negative=16 reencode-bytes=2");
    Ok(())
}
