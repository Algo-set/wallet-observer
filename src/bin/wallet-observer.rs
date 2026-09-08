use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{SystemTime, UNIX_EPOCH};
use wallet_observer::{analyze, observe, ObserverConfig, PortfolioPolicy, PortfolioSnapshot};

const USAGE: &str = "\
Usage:
  wallet-observer snapshot CONFIG.json OUTPUT.json
  wallet-observer analyze SNAPSHOT.json POLICY.json [OUTPUT.json]

The program reads balances and produces reports. It cannot sign or broadcast transactions.
";

#[tokio::main]
async fn main() -> ExitCode {
    match run(std::env::args().skip(1).collect()).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}\n\n{USAGE}");
            ExitCode::from(2)
        }
    }
}

async fn run(args: Vec<String>) -> Result<(), String> {
    match args.as_slice() {
        [command, config, output] if command == "snapshot" => {
            let config: ObserverConfig = read_json(config)?;
            let snapshot = observe(&config).await.map_err(|error| error.to_string())?;
            write_atomic(Path::new(output), &snapshot)
        }
        [command, snapshot, policy] if command == "analyze" => {
            let snapshot: PortfolioSnapshot = read_json(snapshot)?;
            let policy: PortfolioPolicy = read_json(policy)?;
            let report =
                analyze(&snapshot, &policy, unix_time_ms()).map_err(|error| error.to_string())?;
            println!("{}", serde_json::to_string_pretty(&report).unwrap());
            Ok(())
        }
        [command, snapshot, policy, output] if command == "analyze" => {
            let snapshot: PortfolioSnapshot = read_json(snapshot)?;
            let policy: PortfolioPolicy = read_json(policy)?;
            let report =
                analyze(&snapshot, &policy, unix_time_ms()).map_err(|error| error.to_string())?;
            write_atomic(Path::new(output), &report)
        }
        _ => Err("invalid arguments".to_string()),
    }
}

fn read_json<T: serde::de::DeserializeOwned>(path: &str) -> Result<T, String> {
    let content = fs::read_to_string(path).map_err(|error| format!("{path}: {error}"))?;
    serde_json::from_str(&content).map_err(|error| format!("{path}: {error}"))
}

fn write_atomic<T: serde::Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let temporary = PathBuf::from(format!("{}.tmp", path.display()));
    let content = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    fs::write(&temporary, content).map_err(|error| error.to_string())?;
    fs::rename(&temporary, path).map_err(|error| error.to_string())
}

fn unix_time_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(i64::MAX as u128) as i64
}
