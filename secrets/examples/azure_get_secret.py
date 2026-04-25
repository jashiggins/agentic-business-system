# Location: /secrets/examples/azure_get_secret.py
# Purpose: Retrieve a secret from Azure Key Vault.
# Install: pip install azure-identity azure-keyvault-secrets
# Usage: python azure_get_secret.py https://my-vault.vault.azure.net/ secret-name

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import sys

def get_secret(vault_url, secret_name):
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    secret = client.get_secret(secret_name)
    return secret.value

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python azure_get_secret.py <vault_url> <secret_name>")
        sys.exit(1)
    vault_url = sys.argv[1]
    secret_name = sys.argv[2]
    val = get_secret(vault_url, secret_name)
    # Do not print secrets in production. This is for local testing only.
    print("RETRIEVED_SECRET_PLACEHOLDER")
