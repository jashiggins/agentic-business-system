# Location: /secrets/examples/aws_get_secret.py
# Purpose: Retrieve a secret from AWS Secrets Manager.
# Install: pip install boto3
# Usage: python aws_get_secret.py prod/db/readonly

import sys
import boto3
import base64
from botocore.exceptions import ClientError

def get_secret(secret_name, region_name="us-east-1"):
    client = boto3.client("secretsmanager", region_name=region_name)
    try:
        resp = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise
    if 'SecretString' in resp:
        return resp['SecretString']
    return base64.b64decode(resp['SecretBinary']).decode('utf-8')

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python aws_get_secret.py <secret_name> [region]")
        sys.exit(1)
    secret_name = sys.argv[1]
    region = sys.argv[2] if len(sys.argv) > 2 else "us-east-1"
    secret = get_secret(secret_name, region)
    # Do not print secrets in production. This is for local testing only.
    print("RETRIEVED_SECRET_PLACEHOLDER")
