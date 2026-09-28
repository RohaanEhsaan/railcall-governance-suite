import urllib.request
import json

key = input("Paste your Linear API key: ").strip()

payload = json.dumps({"query": "{ teams { nodes { id name key } } }"}).encode("utf-8")
req = urllib.request.Request(
    "https://api.linear.app/graphql",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": key
    }
)
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        nodes = data.get("data", {}).get("teams", {}).get("nodes", [])
        if not nodes:
            print("No teams found or invalid response:", data)
        for t in nodes:
            print("\n------------------------------")
            print("Name:", t.get("name"))
            print("Key: ", t.get("key"))
            print("UUID:", t.get("id"))
            print("------------------------------\n")
except Exception as e:
    print("Request failed:", e)
