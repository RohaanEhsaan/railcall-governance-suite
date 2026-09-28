import json
from pathlib import Path

paths = [
    Path("C:/railcall-shopify/module.json"),
    Path("C:/Users/rohan/.railcall/station/modules/rohan-shopify-admin/module.json")
]

for p in paths:
    if not p.exists():
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    data["provider"] = "shopify"

    for cmd in data.get("commands", []):
        raw_name = cmd.get("name")
        if not raw_name.startswith("shopify."):
            cmd["id"] = f"shopify.{raw_name}"
        else:
            cmd["id"] = raw_name
        
        cmd["provider"] = "shopify"
        
        # Ensure input schema values are typed as string for Studio UI compatibility
        for key in ("inputs", "input_schema"):
            schema_dict = cmd.get(key, {})
            for param, meta in schema_dict.items():
                if isinstance(meta, dict) and meta.get("type") in ("number", "integer", "boolean"):
                    meta["type"] = "string"

        # Add expected_fingerprint to state-changing commands
        if raw_name in ("add_order_tags", "update_inventory"):
            for k in ("inputs", "input_schema"):
                cmd[k]["expected_fingerprint"] = {
                    "type": "string",
                    "label": "Expected State Fingerprint (SHA-256)",
                    "required": False,
                    "help": "Cryptographic anti-drift fingerprint from get_order."
                }

        # Add ceiling override flag to create_refund
        if raw_name == "create_refund":
            for k in ("inputs", "input_schema"):
                cmd[k]["allow_high_refund"] = {
                    "type": "string",
                    "label": "Allow High Refund (> $100)",
                    "required": False,
                    "help": "Set to 'true' to authorize refunds over the safety ceiling."
                }

    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Normalized manifest: {p}")
