# Location: /secrets/examples/local_get_secret.py
# Purpose: Local development fallback using .env (do NOT commit .env to repo).
# Install: pip install python-dotenv
# Usage: create a .env file with DB_READONLY_PASSWORD=local-secret then run.

from dotenv import load_dotenv
import os

load_dotenv()  # loads .env in current directory

def get_secret_from_env(key):
    return os.getenv(key)

if __name__ == "__main__":
    key = "DB_READONLY_PASSWORD"
    val = get_secret_from_env(key)
    # Do not print secrets in production. This is for local testing only.
    print("RETRIEVED_SECRET_PLACEHOLDER")
