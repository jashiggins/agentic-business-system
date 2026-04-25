# Secrets Usage Guide

Location: /secrets/README.md

Summary
- Do not store plaintext secrets in the repo.
- Use logical secret IDs in agent configs and resolve them at runtime via the provider.
- Log secret access events to the immutable ledger without recording secret values.

Files
- `secrets_config.json` maps logical IDs to provider references.
- `examples/` contains provider-specific retrieval scripts for local testing.

Runtime pattern
1. Agent requests secret by logical id (e.g., "db_readonly_password").
2. Runtime resolves provider path from `secrets_config.json`.
3. Runtime fetches secret using provider SDK with instance identity.
4. Runtime records an immutable ledger entry: `{actor, secret_id, action:"access", timestamp}`.
5. Secret is used in memory only and discarded immediately.

Rotation and revocation
- Define rotation cadence per secret type.
- Revoke and rotate immediately on suspected compromise.
- Update provider versions and keep `secrets_config.json` mapping current.

Local development
- Use `.env` for local testing only and never commit `.env`.
- Use `local_get_secret.py` for local retrieval.

Security notes
- Use managed identities or short-lived credentials for provider access.
- Ensure secret retrieval calls are audited and that secret values are never logged.
