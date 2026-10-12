"""rohan/seo-traffic-airlock - read-only SEO preflight checks for autonomous agents.

Contract (the same shape that executed live through Station Sends on the Linear module):

    def seo_<command>(inputs, stamp=None) -> (result_dict, receipt_dict)

Refusals and failures raise RuntimeError("Airlock Refusal: ..."), so a failed check is
recorded as a failed run and never as a success.

Every command is read-only. Nothing is deployed, written or sent anywhere.

  seo.audit_robots_txt        pure local, zero network
  seo.preview_redirect_graph  pure local, zero network
  seo.verify_sitemap_urls     fetches YOUR site only (every request pinned to SEO_SITE_HOST);
                              registered only in module.with-sitemap.json
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "RailCall-SEO-Airlock/0.1 (read-only preflight)"

# robots.txt
MAX_ROBOTS_BYTES = 1024 * 1024
GOOGLE_ROBOTS_LIMIT_BYTES = 500 * 1024
MAX_TEST_PATHS = 200
PROBE_PATH = "/probe-sample-page"
SENTINEL_AGENTS = ("*", "googlebot", "bingbot")

# redirects
MAX_REDIRECT_RULES = 5000
RECOMMENDED_REDIRECT_BATCH = 25

# sitemap
MAX_SITEMAP_BYTES = 5 * 1024 * 1024
DEFAULT_URLS = 25
MAX_URLS = 100
URL_TIMEOUT = 4
SITEMAP_TIMEOUT = 10
DEADLINE_SECONDS = 40


def _refuse(message):
    raise RuntimeError("Airlock Refusal: " + message)


def _split_items(value, extra_seps=""):
    """Accept a list, a JSON list string, or a newline (and optionally extra-separator) string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    return [p.strip() for p in re.split(r"[\r\n" + extra_seps + r"]+", text) if p.strip()]


def _clamp_int(value, default, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


# ---------------------------------------------------------------------------
# robots.txt matching (RFC 9309 semantics)
# ---------------------------------------------------------------------------
def _parse_robots(text):
    groups = []
    sitemaps = []
    orphans = 0
    ignored = 0
    current = None
    in_rules = False
    for raw in re.split(r"\r\n|\r|\n", text.lstrip("\ufeff")):
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if current is None or in_rules:
                current = {"agents": [], "rules": []}
                groups.append(current)
                in_rules = False
            current["agents"].append(value.lower())
        elif field in ("allow", "disallow"):
            if current is None:
                orphans += 1
                continue
            in_rules = True
            current["rules"].append((field, value))
        elif field == "sitemap":
            sitemaps.append(value)
        else:
            ignored += 1
    return groups, sitemaps, orphans, ignored


def _rule_regex(pattern):
    anchored = pattern.endswith("$")
    core = pattern[:-1] if anchored else pattern
    body = "".join(".*" if ch == "*" else re.escape(ch) for ch in core)
    return re.compile(body + (r"\Z" if anchored else ""), re.DOTALL)


def _select_rules(groups, agent):
    """Pick the single most specific group for this crawler (never merged with '*')."""
    agent = agent.lower()
    used = None
    if any(agent in g["agents"] for g in groups):
        used = agent
    else:
        parts = agent.split("-")
        while len(parts) > 1 and used is None:
            parts.pop()
            candidate = "-".join(parts)
            if any(candidate in g["agents"] for g in groups):
                used = candidate
        if used is None:
            used = "*"
    rules = [rule for g in groups if used in g["agents"] for rule in g["rules"]]
    return used, rules


def _evaluate(rules, path):
    """Longest matching pattern wins; on a tie Allow beats Disallow; no match means allowed."""
    best = None
    for directive, pattern in rules:
        if pattern == "":
            continue
        if _rule_regex(pattern).match(path):
            key = (len(pattern), 1 if directive == "allow" else 0)
            if best is None or key > best[0]:
                best = (key, directive, pattern)
    if best is None:
        return True, None
    return best[1] == "allow", {"directive": best[1], "pattern": best[2]}


def _normalize_path(raw):
    raw = raw.strip()
    parts = urllib.parse.urlsplit(raw)
    if parts.netloc:
        raw = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw


def _robots_findings(groups, orphans, size):
    findings = []
    for agent in SENTINEL_AGENTS:
        used, rules = _select_rules(groups, agent)
        if agent != "*" and used == "*":
            continue  # inherits the '*' group, which is reported once below
        root_ok, _ = _evaluate(rules, "/")
        probe_ok, _ = _evaluate(rules, PROBE_PATH)
        if not root_ok and not probe_ok:
            if agent == "*":
                scope = ("every crawler that has no more specific group "
                         "(that includes Googlebot and Bingbot unless they have their own group)")
            else:
                scope = agent
            findings.append({
                "type": "SITE_WIDE_BLOCK", "severity": "critical", "agent": agent,
                "detail": "These rules block the homepage and ordinary content paths for " + scope
                          + ". Deploying them would de-index the site."})
        elif not root_ok:
            findings.append({
                "type": "HOMEPAGE_BLOCKED", "severity": "warning", "agent": agent,
                "detail": "The homepage '/' is blocked for " + agent + " while other paths are not."})
    if orphans:
        findings.append({
            "type": "ORPHAN_RULES", "severity": "warning", "agent": None,
            "detail": str(orphans) + " Allow/Disallow line(s) appear before any User-agent line and are ignored by crawlers."})
    if size > GOOGLE_ROBOTS_LIMIT_BYTES:
        findings.append({
            "type": "OVER_500KIB", "severity": "warning", "agent": None,
            "detail": "File is " + str(size) + " bytes; Google ignores content beyond 500 KiB."})
    return findings


_DIRECTIVE = re.compile(r"\b(?:user-agent|allow|disallow|sitemap)\s*:", re.IGNORECASE)


def _recover_lines(text):
    """A single-line form field strips newlines. Never let that turn a blocking file into a clean one."""
    if "\n" in text or "\r" in text:
        return text
    if "\\n" in text:
        return text.replace("\\r\\n", "\n").replace("\\n", "\n")
    if len(_DIRECTIVE.findall(text)) > 1:
        _refuse("robots_txt arrived as one line containing several directives, so its line breaks were lost "
                "(single-line form fields strip them). Paste it into a multi-line field, or type \\n between lines.")
    return text


def seo_audit_robots_txt(inputs, stamp=None):
    inputs = inputs or {}
    if inputs.get("robots_txt") is None:
        _refuse("robots_txt is required (paste the full candidate file; an empty string means allow-all).")
    text = _recover_lines(str(inputs["robots_txt"]))
    size = len(text.encode("utf-8"))
    if size > MAX_ROBOTS_BYTES:
        _refuse("robots_txt is " + str(size) + " bytes; the limit for this check is " + str(MAX_ROBOTS_BYTES) + ".")
    agent = str(inputs.get("user_agent") or "Googlebot").strip() or "Googlebot"
    paths = _split_items(inputs.get("test_paths"), ",") or ["/"]
    if len(paths) > MAX_TEST_PATHS:
        _refuse("at most " + str(MAX_TEST_PATHS) + " test paths per call (received " + str(len(paths)) + ").")

    groups, sitemaps, orphans, ignored = _parse_robots(text)
    used, rules = _select_rules(groups, agent)

    path_results = []
    for raw in paths:
        path = _normalize_path(raw)
        allowed, matched = _evaluate(rules, path)
        if matched is not None:
            matched = dict(matched, group=used)
        path_results.append({"path": path, "allowed": allowed, "matched_rule": matched})

    findings = _robots_findings(groups, orphans, size)
    critical = sum(1 for f in findings if f["severity"] == "critical")
    if critical:
        verdict = "BLOCKS_SITE"
    elif findings:
        verdict = "REVIEW"
    else:
        verdict = "OK"

    result = {
        "verdict": verdict,
        "user_agent_checked": agent,
        "group_used": used,
        "path_results": path_results,
        "risk_findings": findings,
        "groups_found": len(groups),
        "sitemaps_declared": sitemaps[:20],
        "ignored_directives": ignored,
        "bytes": size,
        "method": "RFC 9309 matching: longest pattern wins, Allow wins ties, * and $ supported, "
                  "one most-specific group per crawler. Paths are compared as written (no percent-decoding).",
    }
    receipt = {"kind": "seo.audit_robots_txt", "verdict": verdict,
               "critical_findings": critical, "paths_checked": len(path_results)}
    return result, receipt


# ---------------------------------------------------------------------------
# redirect graph
# ---------------------------------------------------------------------------
_ARROW = re.compile(r"\s*(?:->|=>|\u2192)\s*")


def _parse_rules(value):
    if isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        text = str(value or "").strip()
        if text.startswith("["):
            try:
                raw_items = json.loads(text)
            except ValueError:
                _refuse("redirect_rules looks like JSON but does not parse.")
            if not isinstance(raw_items, list):
                _refuse("redirect_rules JSON must be a list.")
        else:
            raw_items = [p for p in re.split(r"[\r\n;]+", text) if p.strip()]
    if not raw_items:
        _refuse("redirect_rules is required (one rule per line: /old -> /new).")
    if len(raw_items) > MAX_REDIRECT_RULES:
        _refuse("at most " + str(MAX_REDIRECT_RULES) + " rules per call (received " + str(len(raw_items)) + ").")
    rules = []
    for index, item in enumerate(raw_items, 1):
        if isinstance(item, dict):
            source, target = item.get("source"), item.get("target")
        else:
            parts = _ARROW.split(str(item).strip(), maxsplit=1)
            source, target = (parts[0], parts[1]) if len(parts) == 2 else (None, None)
        source = "" if source is None else str(source).strip()
        target = "" if target is None else str(target).strip()
        if (not source or not target or re.search(r"\s", source) or re.search(r"\s", target)
                or _ARROW.search(target)):
            _refuse("rule " + str(index) + " is malformed; expected '/source -> /target'. "
                    "A preview that silently skips a rule would mislead you.")
        rules.append((source, target))
    return rules


def seo_preview_redirect_graph(inputs, stamp=None):
    inputs = inputs or {}
    rules = _parse_rules(inputs.get("redirect_rules"))

    graph = {}
    conflicts = {}
    duplicates = []
    self_redirects = []
    for source, target in rules:
        if source == target:
            self_redirects.append(source)
            continue
        if source in graph:
            if graph[source] == target:
                duplicates.append(source)
            else:
                conflicts.setdefault(source, [graph[source]])
                if target not in conflicts[source]:
                    conflicts[source].append(target)
            continue
        graph[source] = target

    cycles = {}
    loop_affected = set()
    for start in graph:
        path = [start]
        seen = {start}
        current = graph[start]
        while current in graph:
            if current in seen:
                cycle = path[path.index(current):]
                loop_affected.update(path)
                pivot = cycle.index(min(cycle))
                cycles[tuple(cycle[pivot:] + cycle[:pivot])] = True
                break
            path.append(current)
            seen.add(current)
            current = graph[current]
    cycle_nodes = {node for cycle in cycles for node in cycle}

    targets = set(graph.values())
    chains = []
    for source in graph:
        if source in loop_affected or source in targets:
            continue  # only report chain heads
        hops = 1
        path = [source, graph[source]]
        current = graph[source]
        while current in graph:
            current = graph[current]
            hops += 1
            path.append(current)
        if hops >= 2:
            chains.append({"source": source, "hops": hops, "final_target": current, "path": path})

    findings = []
    for cycle in cycles:
        findings.append({"type": "LOOP", "severity": "critical", "cycle": list(cycle),
                         "detail": "Redirect loop: " + " -> ".join(list(cycle) + [cycle[0]])})
    for source in sorted(loop_affected - cycle_nodes):
        findings.append({"type": "FEEDS_LOOP", "severity": "critical", "source": source,
                         "detail": source + " redirects into a loop."})
    for source in self_redirects:
        findings.append({"type": "SELF_REDIRECT", "severity": "critical", "source": source,
                         "detail": source + " redirects to itself."})
    for source, found in conflicts.items():
        findings.append({"type": "CONFLICTING_SOURCE", "severity": "critical", "source": source,
                         "targets": found, "detail": source + " is given " + str(len(found)) + " different targets."})
    for chain in chains:
        findings.append({"type": "CHAIN", "severity": "warning", "source": chain["source"],
                         "hops": chain["hops"], "final_target": chain["final_target"],
                         "detail": chain["source"] + " takes " + str(chain["hops"]) + " hops; point it straight at "
                                   + chain["final_target"] + "."})
    for source in duplicates:
        findings.append({"type": "DUPLICATE_RULE", "severity": "warning", "source": source,
                         "detail": source + " is listed more than once with the same target."})
    if len(rules) > RECOMMENDED_REDIRECT_BATCH:
        findings.append({"type": "BATCH_TOO_LARGE", "severity": "warning",
                         "detail": str(len(rules)) + " rules exceeds the recommended batch of "
                                   + str(RECOMMENDED_REDIRECT_BATCH) + "; deploy in smaller reviewable batches."})

    critical = sum(1 for f in findings if f["severity"] == "critical")
    verdict = "UNSAFE" if critical else ("REVIEW" if findings else "OK")
    result = {
        "verdict": verdict,
        "total_rules": len(rules),
        "unique_sources": len(graph),
        "findings": findings,
        "flatten_suggestions": [{"source": c["source"], "target": c["final_target"]} for c in chains],
        "method": "Sources and targets are compared as exact strings (case-sensitive, no trailing-slash folding).",
    }
    receipt = {"kind": "seo.preview_redirect_graph", "verdict": verdict,
               "critical_findings": critical, "total_rules": len(rules)}
    return result, receipt


# ---------------------------------------------------------------------------
# sitemap check (opt-in command; every request is pinned to the configured host)
# ---------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener():
    """HTTP(S) only: no file:, ftp: or data: handlers, no redirect following, no system proxies."""
    opener = urllib.request.OpenerDirector()
    for item in (urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
                 urllib.request.HTTPDefaultErrorHandler(), _NoRedirect(),
                 urllib.request.HTTPErrorProcessor(), urllib.request.UnknownHandler()):
        opener.add_handler(item)
    return opener


def _config():
    helpers = globals().get("__rc_helpers__")
    entry = {}
    if helpers and "vault_get" in helpers:
        try:
            entry = helpers["vault_get"]("seo") or {}
        except Exception:
            entry = {}
    return entry if isinstance(entry, dict) else {}


def _allowed_hosts():
    raw = str(_config().get("SEO_SITE_HOST") or "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _same_host(url, allowed):
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (parts.scheme in ("http", "https") and bool(parts.netloc)
            and "@" not in parts.netloc and parts.netloc.lower() in allowed)


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _request(opener, url, method, timeout):
    """Returns (handle, status, headers, error). Redirects are never followed."""
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        resp = opener.open(req, timeout=timeout)
        return resp, resp.status, resp.headers, None
    except urllib.error.HTTPError as exc:
        return exc, exc.code, exc.headers, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, None, {}, str(getattr(exc, "reason", exc))[:120]


def _probe_url(opener, url):
    handle, status, headers, error = _request(opener, url, "HEAD", URL_TIMEOUT)
    if handle is not None and status in (405, 501):
        handle.close()
        handle, status, headers, error = _request(opener, url, "GET", URL_TIMEOUT)
    if handle is not None:
        handle.close()
    return status, headers, error


def _classify(url, status, headers, error):
    if error:
        return {"url": url, "issue": "UNREACHABLE", "detail": error}
    if 300 <= status < 400:
        return {"url": url, "issue": "REDIRECT", "status": status, "location": headers.get("Location")}
    if 400 <= status < 500:
        return {"url": url, "issue": "CLIENT_ERROR", "status": status}
    if status >= 500:
        return {"url": url, "issue": "SERVER_ERROR", "status": status}
    tag = str(headers.get("X-Robots-Tag") or "")
    if re.search(r"\b(noindex|none)\b", tag, re.IGNORECASE):
        return {"url": url, "issue": "NOINDEX_HEADER", "status": status, "x_robots_tag": tag[:120]}
    return None


def _parse_sitemap(data):
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        _refuse("sitemap contains a DOCTYPE/ENTITY declaration; refusing to parse it (entity-expansion risk).")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        _refuse("sitemap is not well-formed XML: " + str(exc))
    root_kind = _local(root.tag)
    if root_kind not in ("urlset", "sitemapindex"):
        _refuse("sitemap root element is <" + root_kind + ">; expected <urlset> or <sitemapindex>.")
    child_kind = "url" if root_kind == "urlset" else "sitemap"
    entries = []
    for child in root:
        if _local(child.tag) != child_kind:
            continue
        for sub in child:
            if _local(sub.tag) == "loc" and sub.text and sub.text.strip():
                entries.append(sub.text.strip())
    return ("urlset" if root_kind == "urlset" else "index"), entries


def seo_verify_sitemap_urls(inputs, stamp=None):
    inputs = inputs or {}
    sitemap_url = str(inputs.get("sitemap_url") or "").strip()
    if not sitemap_url:
        _refuse("sitemap_url is required.")
    allowed = _allowed_hosts()
    if not allowed:
        _refuse("no site host configured. Save SEO_SITE_HOST (for example www.example.com) for the 'seo' "
                "integration in Studio so every request can be pinned to your own site.")
    if not _same_host(sitemap_url, allowed):
        _refuse("sitemap_url must be an http(s) URL on a configured host (" + ", ".join(sorted(allowed))
                + ") with no embedded credentials.")
    if urllib.parse.urlsplit(sitemap_url).path.lower().endswith(".gz"):
        _refuse("gzip-compressed sitemaps are not supported in this version.")
    max_urls = _clamp_int(inputs.get("max_urls"), DEFAULT_URLS, 1, MAX_URLS)

    opener = _build_opener()
    handle, status, headers, error = _request(opener, sitemap_url, "GET", SITEMAP_TIMEOUT)
    if error:
        _refuse("could not fetch the sitemap: " + error)
    try:
        if status != 200:
            location = headers.get("Location") if hasattr(headers, "get") else None
            _refuse("sitemap returned HTTP " + str(status)
                    + ((" redirecting to " + str(location) + "; pass the final URL") if location else "") + ".")
        data = handle.read(MAX_SITEMAP_BYTES + 1)
    finally:
        handle.close()
    if len(data) > MAX_SITEMAP_BYTES:
        _refuse("sitemap is larger than " + str(MAX_SITEMAP_BYTES) + " bytes.")
    if data[:2] == b"\x1f\x8b":
        _refuse("gzip-compressed sitemaps are not supported in this version.")

    kind, entries = _parse_sitemap(data)
    notes = ("Redirects are reported, never followed. Only HTTP status and the X-Robots-Tag header are "
             "inspected; meta-robots and canonical tags are not.")
    if kind == "index":
        result = {"sitemap_url": sitemap_url, "kind": "index", "verdict": "NOT_CHECKED_INDEX",
                  "child_sitemaps": entries[:20], "entries_in_sitemap": len(entries), "checked": 0,
                  "notes": "This is a sitemap index; its child sitemaps are listed but not fetched. "
                           "Run again with one child sitemap URL. " + notes}
        receipt = {"kind": "seo.verify_sitemap_urls", "host": urllib.parse.urlsplit(sitemap_url).netloc,
                   "checked": 0, "problems": 0}
        return result, receipt

    same_host = [u for u in entries if _same_host(u, allowed)]
    off_host = len(entries) - len(same_host)
    started = time.monotonic()
    counts = {}
    problems = []
    checked = 0
    deadline_hit = False
    for url in same_host[:max_urls]:
        if time.monotonic() - started > DEADLINE_SECONDS:
            deadline_hit = True
            break
        url_status, url_headers, url_error = _probe_url(opener, url)
        checked += 1
        key = "unreachable" if url_error else str(url_status)
        counts[key] = counts.get(key, 0) + 1
        problem = _classify(url, url_status, url_headers, url_error)
        if problem:
            problems.append(problem)

    verdict = "REVIEW" if (problems or off_host or deadline_hit) else "OK"
    result = {
        "sitemap_url": sitemap_url, "kind": "urlset", "verdict": verdict,
        "entries_in_sitemap": len(entries), "checked": checked,
        "truncated": len(same_host) > max_urls, "status_counts": counts,
        "problems": problems[:50], "problems_total": len(problems),
        "off_host_skipped": off_host, "deadline_hit": deadline_hit, "notes": notes,
    }
    receipt = {"kind": "seo.verify_sitemap_urls", "host": urllib.parse.urlsplit(sitemap_url).netloc,
               "checked": checked, "problems": len(problems)}
    return result, receipt