# SEO Traffic Airlock (`rohan/seo-traffic-airlock`)

Deterministic, offline-first preflight deployment airlock for autonomous coding agents (Claude Code, Cursor, Devin) and CI/CD pipelines. Intercepts SEO catastrophes, infinite redirect loops, and site-wide search de-indexing before code reaches production.

> No external network egress (`network: none`), zero credentials, full unit coverage, and every run produces an Ed25519-cryptographically signed audit receipt.

---

## Key Capabilities

- **RFC9309 Compliant robots.txt Parser (`seo.audit_robots_txt`)**: Evaluates candidate directives against business-critical paths with automated preflight guards against catastrophic site-wide blocks (`Disallow: /`).
- **Directed Graph Redirect Engine (`seo.preview_redirect_graph`)**: Detects circular loops, conflicting destinations, and computes hop-flattening recommendations for up to 5,000 rules in sub-millisecond time.
- **Zero-Egress Sandbox**: Runs under `network: none` with zero stored secrets, making it 100% data-exfiltration proof.
- **Offline Cryptographic Attestation**: Mints an Ed25519-signed receipt for every run that can be independently verified offline via `railcall verify` without network access.


## Installation

From the RailCall Marketplace:

```bash
railcall market install rohan/seo-traffic-airlock
```


## CLI Usage

 1. Audit robots.txt Before Deploy

```bash
railcall run seo.audit_robots_txt '{"robots_txt": "User-agent: *\nDisallow: /admin\nAllow: /", "test_paths": ["/", "/admin"]}'
```

### 2. Detect Redirect Loops & Chains

```bash
railcall run seo.preview_redirect_graph '{"redirect_rules": "/a -> /b; /b -> /a; /old -> /mid; /mid -> /new"}'
```

 3. Verify Cryptographic Receipt Offline

```bash
railcall verify
```


 License

MIT
