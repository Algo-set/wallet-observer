use std::fs;
use std::path::Path;

#[test]
fn crate_has_no_signing_or_transaction_surface() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut text = fs::read_to_string(root.join("Cargo.toml")).unwrap();
    collect_source(&root.join("src"), &mut text);
    let lower = text.to_ascii_lowercase();
    for forbidden in [
        "eth_sendtransaction",
        "eth_sendrawtransaction",
        "eth_signtransaction",
        "personal_sign",
        "private_key",
        "secret_key",
        "mnemonic",
        "localsigner",
        "alloy-signer",
        "ethers-signers",
        "secp256k1",
    ] {
        assert!(
            !lower.contains(forbidden),
            "forbidden capability: {forbidden}"
        );
    }
    assert!(!text.contains("/Users/"));
    assert!(!contains_concrete_evm_address(&text));
}

fn collect_source(path: &Path, output: &mut String) {
    for entry in fs::read_dir(path).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            collect_source(&path, output);
        } else if path.extension().and_then(|value| value.to_str()) == Some("rs") {
            output.push_str(&fs::read_to_string(path).unwrap());
        }
    }
}

fn contains_concrete_evm_address(text: &str) -> bool {
    let bytes = text.as_bytes();
    bytes.windows(42).any(|window| {
        window.starts_with(b"0x") && window[2..].iter().all(|byte| byte.is_ascii_hexdigit())
    })
}
