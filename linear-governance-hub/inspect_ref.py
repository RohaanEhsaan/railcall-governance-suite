from pathlib import Path

base = Path("C:/Users/rohan/.railcall/station/modules")
patterns = ["*github*", "*hubspot*", "*airtable*", "*stripe*"]

found = []
for pat in patterns:
    found.extend(base.glob(f"{pat}/**/handler.py"))

if found:
    ref_path = found[0]
    print(f"=== Reference file: {ref_path} ===\n")
    lines = ref_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for idx, line in enumerate(lines[:80]):
        print(f"{idx+1:02d}: {line}")
else:
    print("No reference handler found under", base)
