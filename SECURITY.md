# Security policy

## Supported versions

Security fixes are applied to the latest commit on the default branch and to
the latest tagged release when releases exist.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/Algo-set/wallet-observer/security/advisories/new). Do not include credentials, account identifiers, private
endpoints, or exploit details in a public issue.

Include the affected package and version, a minimal reproduction, impact, and
any suggested mitigation. Maintainers should acknowledge a complete report
within seven days and coordinate disclosure after a fix is available.

## Security boundaries

- `wallet_observer` can read balances and produce policy recommendations, but
  cannot construct, sign, approve, or broadcast transactions.
- Endpoint and account values belong in the caller's secret store or process
  environment. They must not be committed, logged, or included in reports.
