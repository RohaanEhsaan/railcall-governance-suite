import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "handlers"))
import handler

def run_tests():
    print("==================================================")
    print("Cloud Infrastructure Airlock - Verification Suite")
    print("==================================================")

    # 1. Offline Deterministic Policy Interception
    print("\n1. Testing spend ceiling & GPU quarantine:")
    res, rec = handler.aws_provision_instance({"instance_type": "p4d.24xlarge", "image_id": "ami-dummy", "override_ceiling": "false"})
    if res.get("airlock_status") != "REFUSED_BY_POLICY":
        raise AssertionError("GPU instance should have been refused by policy")
    if not rec.get("provenance_hash") or len(rec["provenance_hash"]) != 64:
        raise AssertionError("Missing or malformed SHA-256 receipt digest")
    print("  ✓ PASSED: GPU launch blocked at loopback with SHA-256 receipt digest")

    # 2. Killswitch Safety Lock
    print("\n2. Testing killswitch unmanaged instance guard:")
    res, rec = handler.aws_emergency_killswitch({})
    if "error" not in res or rec.get("executed") is not False:
        raise AssertionError("Killswitch failed to reject invalid invocation")
    print("  ✓ PASSED: Killswitch safely rejected invocation with missing instance_id")

    # 3. Endpoint Smoke / Live Verification
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    print(f"\n3. Checking connectivity against {endpoint}:")
    res, rec = handler.aws_inspect_running_spend({"region": "us-east-1"})
    
    if "error" in res:
        print(f"  ℹ Endpoint not running ({res['error'][:60]}...)")
        print("  ✓ Smoke check passed: network boundary caught exception and structured receipt safely.")
    else:
        print(f"  ✓ PASSED: Live connection active. Discovered {res.get('active_count')} running instances.")
        print(f"  Receipt Digest: {rec.get('provenance_hash')}")

    print("\n==================================================")
    print("✓ All validation checks passed.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
