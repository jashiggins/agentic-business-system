# Location: /tools/verify_audit_log.py
# Purpose: Verify chained audit log entries and signatures.
# Usage: python verify_audit_log.py /path/to/ledger.json
# Note: Replace verify_signature() with your KMS/HSM verification call.

import sys
import json
import hashlib
import base64

def sha256_hex(obj):
    j = json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(j).hexdigest()

def verify_signature(kms_key_id, payload_hash, signature_b64):
    # Placeholder: integrate with your KMS/HSM verify API.
    # Return True if signature verifies payload_hash under kms_key_id.
    # For now, this function returns True for demonstration.
    # Replace with real verification call.
    return True

def verify_ledger(path):
    with open(path, 'r') as f:
        ledger = json.load(f)
    prev_hash = None
    for entry in ledger:
        payload_hash = entry.get('payload_hash')
        if not payload_hash:
            print("Missing payload_hash in entry", entry.get('entry_id'))
            return False
        if entry.get('prev_hash') != prev_hash:
            print("Chain mismatch at", entry.get('entry_id'))
            return False
        sig = entry.get('signature')
        kms = entry.get('kms_key_id')
        if not verify_signature(kms, payload_hash, sig):
            print("Signature verification failed for", entry.get('entry_id'))
            return False
        prev_hash = hashlib.sha256((payload_hash + (prev_hash or '')).encode('utf-8')).hexdigest()
    print("Ledger verification passed")
    return True

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python verify_audit_log.py /path/to/ledger.json")
        sys.exit(2)
    verify_ledger(sys.argv[1])
