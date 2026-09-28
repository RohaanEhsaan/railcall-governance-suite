import json
from pathlib import Path

paths = [
    Path("C:/Linear/module.json"),
    Path("C:/Users/rohan/.railcall/station/modules/rohan-linear-governance-hub/module.json")
]

for p in paths:
    if not p.exists():
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    for cmd in data.get("commands", []):
        for schema_key in ["inputs", "input_schema"]:
            fields = cmd.get(schema_key, {})
            for field_name, spec in fields.items():
                if isinstance(spec, dict) and spec.get("type") in ("integer", "boolean", "number"):
                    spec["type"] = "string"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Normalized schemas in {p}")
