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
        if cmd.get("name") == "create_issue" or cmd.get("id") == "linear.create_issue":
            if "priority" in cmd.get("inputs", {}):
                cmd["inputs"]["priority"]["type"] = "string"
            if "priority" in cmd.get("input_schema", {}):
                cmd["input_schema"]["priority"]["type"] = "string"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Updated schema in {p}")
