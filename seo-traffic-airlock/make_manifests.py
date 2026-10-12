import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PUBKEY = "4ded0aa74bbcfe3ede9202b96e78819d1703b4fdcce7915c07ae06734a5661d0"
PLACEHOLDER_HOST = "REPLACE-ME.example.com"


def field(label, help_text, required=False, default=None):
    spec = {"type": "string", "label": label}
    if default is not None:
        spec["default"] = default
    if required:
        spec["required"] = True
    spec["help"] = help_text
    return spec


def command(cid, title, description, inputs, requires):
    return {
        "id": cid,
        "name": cid,
        "title": title,
        "description": description,
        "mode": "read",
        "impact_tier": "READ_ONLY",
        "risk": "low",
        "side_effects": "none",
        "provider": "seo",
        "requires": requires,
        "input_schema": inputs,
        "inputs": json.loads(json.dumps(inputs)),
    }


ROBOTS = command(
    "seo.audit_robots_txt",
    "Audit robots.txt Before Deploy",
    "Evaluates a candidate robots.txt locally with RFC 9309 matching (wildcards, $, longest match wins) "
    "and flags site-wide or homepage blocks before anything is deployed. Zero network egress.",
    {
        "robots_txt": field("robots.txt contents",
                            "Paste the full candidate file. An empty value means allow-all.", required=True),
        "test_paths": field("Paths to test",
                            "Comma- or newline-separated paths, e.g. /products, /admin/login?x=1 (max 200).",
                            default="/"),
        "user_agent": field("Crawler to evaluate as",
                            "Product token such as Googlebot, Bingbot or *.", default="Googlebot"),
    },
    [],
)

REDIRECTS = command(
    "seo.preview_redirect_graph",
    "Preview Redirect Graph",
    "Analyses proposed redirect rules locally: finds loops, self-redirects, conflicting targets, "
    "chains (with flattened suggestions) and oversized batches. Zero network egress.",
    {
        "redirect_rules": field("Redirect rules",
                                "One rule per line (or separated by ;): /old -> /new. "
                                "A JSON list of {source, target} also works (max 5000).", required=True),
    },
    [],
)

SITEMAP = command(
    "seo.verify_sitemap_urls",
    "Verify Sitemap URLs",
    "Fetches a sitemap on your own configured host and checks the HTTP status and X-Robots-Tag of its URLs. "
    "Every request is pinned to SEO_SITE_HOST; redirects are reported, never followed.",
    {
        "sitemap_url": field("Sitemap URL", "Full http(s) URL of a sitemap on your configured host.", required=True),
        "max_urls": field("URLs to check", "How many sitemap URLs to probe (1-100).", default="25"),
    },
    ["SEO_SITE_HOST"],
)


def manifest(commands, network, secrets, description):
    data = {
        "$schema": "https://railcall.ai/schemas/module-v1.json",
        "id": "rohan/seo-traffic-airlock",
        "name": "seo-traffic-airlock",
        "version": "0.1.0",
        "title": "SEO Traffic Airlock",
        "description": description,
        "publisher_pubkey": PUBKEY,
        "author": "rohan",
        "category": "Marketing",
        "entrypoint": "handlers/handler.py",
    }
    if secrets:
        data["secrets"] = secrets
    data["commands"] = commands
    data["manifest_version"] = 2
    data["requires"] = {"network": network, "filesystem_writes": [], "subprocess": False}
    data["provider"] = "seo"
    return data


default = manifest(
    [ROBOTS, REDIRECTS],
    [],
    None,
    "Read-only SEO preflight for autonomous agents: audit a candidate robots.txt and preview redirect rules "
    "before anything is deployed. Runs fully offline - zero network egress, nothing is written or sent.",
)

with_sitemap = manifest(
    [ROBOTS, REDIRECTS, SITEMAP],
    [PLACEHOLDER_HOST],
    [{"name": "SEO_SITE_HOST", "label": "Site host this module may fetch (e.g. www.example.com)"}],
    "Read-only SEO preflight for autonomous agents: audit a candidate robots.txt, preview redirect rules and "
    "verify sitemap URLs on your own site. Network egress is limited to the single host you configure.",
)

for name, data in (("module.json", default), ("module.with-sitemap.json", with_sitemap)):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("wrote", name, "-", len(data["commands"]), "commands")
