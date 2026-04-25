# Location: /secrets/examples/vault_get_secret.py
# Purpose: Retrieve a secret from HashiCorp Vault (KV v2).
# Install: pip install hvac
# Usage: export VAULT_TOKEN=...; python vault_get_secret.py https://vault.example.com secret/path key

import hvac
import os
import sys

def get_secret(vault_addr, token, secret_path, key="value"):
    client = hvac.Client(url=vault_addr, token=token)
    read_response = client.secrets.kv.v2.read_secret_version(path=secret_path)
    return read_response["data"]["data"].get(key)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python vault_get_secret.py <vault_addr> <secret_path> [key]")
        sys.exit(1)
    vault_addr = sys.argv[1]
    secret_path = sys.argv[2]
    key = sys.argv[3] if len(sys.argv) > 3 else "value"
    token = os.environ.get("VAULT_TOKEN")
    if not token:
        print("Set VAULT_TOKEN in environment for authentication")
        sys.exit(1)
    secret = get_secret(vault_addr, token, secret_path, key)
    # Do not print secrets in production. This is for local testing only.
    print("RETRIEVED_SECRET_PLACEHOLDER")
