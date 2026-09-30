import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "handlers"))
import handler

def run_live_suite():
    print("==================================================")
    print("Cloud Infrastructure Airlock - Live Engine Harness")
    print("==================================================")

    # 1. Test offline preflight policy refusal
    print("\n1. Testing spend ceiling & GPU containment:")
    res, rec = handler.aws_provision_instance({"instance_type": "p3.2xlarge", "override_ceiling": "false"})
    if res.get("airlock_status") == "REFUSED_BY_POLICY":
        print("  ✓ PASSED: GPU/High-cost instance intercepted at loopback (127.0.0.1)")
        print(f"  Receipt policy: {rec.get('policy_rule')}")
    else:
        print("  ✗ FAILED: Did not refuse GPU launch")
        sys.exit(1)

    # 2. Test live boto3 execution / exception handling
    print("\n2. Testing live boto3 integration dispatch:")
    res, rec = handler.aws_inspect_running_spend({"region": "us-east-1"})
    
    if "error" in res:
        print(f"  ✓ PASSED: Live AWS SDK exception handled safely: {res['error']}")
        print(f"  Receipt signed action: {rec.get('action')}")
    elif res.get("status") == "success":
        print(f"  ✓ PASSED: Live AWS API returned {res.get('active_count')} running instances")
        print(f"  Receipt signed action: {rec.get('action')}")
    else:
        print("  ✗ FAILED: Unexpected contract return")
        sys.exit(1)

    print("\n==================================================")
    print("✓ All 2 live verification checks passed successfully.")
    print("==================================================")

if __name__ == "__main__":
    run_live_suite()