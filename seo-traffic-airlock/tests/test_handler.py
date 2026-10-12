import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "handlers"))
import handler  # noqa: E402


def robots(text, paths="/", agent="Googlebot"):
    result, receipt = handler.seo_audit_robots_txt(
        {"robots_txt": text, "test_paths": paths, "user_agent": agent})
    return result, receipt


def allowed(text, path, agent="Googlebot"):
    result, _ = robots(text, path, agent)
    return result["path_results"][0]["allowed"]


def types(result, key="risk_findings"):
    return [f["type"] for f in result[key]]


class RobotsMatching(unittest.TestCase):
    def test_prefix_wildcard(self):
        rule = "User-agent: *\nDisallow: /fish*"
        for path in ("/fish.html", "/fishheads/yummy.html", "/fish?id=anything"):
            self.assertFalse(allowed(rule, path), path)
        for path in ("/Fish.asp", "/catfish", "/?id=fish"):
            self.assertTrue(allowed(rule, path), path)

    def test_extension_wildcard(self):
        rule = "User-agent: *\nDisallow: /*.php"
        for path in ("/index.php", "/folder/filename.php?parameters"):
            self.assertFalse(allowed(rule, path), path)
        self.assertTrue(allowed(rule, "/windows.PHP"))

    def test_end_anchor(self):
        rule = "User-agent: *\nDisallow: /*.php$"
        self.assertFalse(allowed(rule, "/folder/filename.php"))
        self.assertTrue(allowed(rule, "/filename.php?parameters"))
        self.assertTrue(allowed(rule, "/filename.php/"))

    def test_longest_match_wins(self):
        rule = "User-agent: *\nDisallow: /folder\nAllow: /folder/public"
        self.assertTrue(allowed(rule, "/folder/public/page"))
        self.assertFalse(allowed(rule, "/folder/private"))

    def test_tie_goes_to_allow(self):
        self.assertTrue(allowed("User-agent: *\nDisallow: /page\nAllow: /page", "/page"))

    def test_specific_group_overrides_star_and_is_not_merged(self):
        rule = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /"
        self.assertTrue(allowed(rule, "/anything", "Googlebot"))
        self.assertFalse(allowed(rule, "/anything", "SomeOtherBot"))

    def test_family_fallback(self):
        rule = "User-agent: googlebot\nDisallow: /secret"
        self.assertFalse(allowed(rule, "/secret", "Googlebot-Image"))

    def test_multiple_agents_share_a_group(self):
        rule = "User-agent: a\nUser-agent: b\nDisallow: /x"
        self.assertFalse(allowed(rule, "/x", "a"))
        self.assertFalse(allowed(rule, "/x", "b"))
        self.assertTrue(allowed(rule, "/x", "c"))

    def test_comments_case_and_bom_are_tolerated(self):
        rule = "\ufeffUSER-AGENT: *   # everyone\nDISALLOW: /p # private\n"
        self.assertFalse(allowed(rule, "/p/x"))

    def test_full_url_test_path_is_reduced_to_path(self):
        self.assertFalse(allowed("User-agent: *\nDisallow: /p", "https://example.com/p?x=1"))

    def test_empty_disallow_allows_everything(self):
        self.assertTrue(allowed("User-agent: *\nDisallow:", "/anything"))


class RobotsSafetyFindings(unittest.TestCase):
    def verdict(self, text):
        result, _ = robots(text)
        return result["verdict"], types(result)

    def test_plain_site_wide_block(self):
        self.assertEqual(self.verdict("User-agent: *\nDisallow: /")[0], "BLOCKS_SITE")

    def test_phrasings_the_original_draft_missed(self):
        cases = {
            "inline comment": "User-agent: *\nDisallow: / # temporary",
            "lowercase googlebot": "User-agent: googlebot\nDisallow: /",
            "wildcard slash": "User-agent: *\nDisallow: /*",
            "bingbot uppercase": "User-agent: BINGBOT\nDisallow: /",
            "extra whitespace": "User-agent:*\nDisallow:   /   ",
            "CRLF line endings": "User-agent: *\r\nDisallow: /\r\n",
        }
        for label, text in cases.items():
            verdict, found = self.verdict(text)
            self.assertEqual(verdict, "BLOCKS_SITE", label)
            self.assertIn("SITE_WIDE_BLOCK", found, label)

    def test_specific_bot_block_is_reported_for_that_bot(self):
        result, _ = robots("User-agent: *\nAllow: /\n\nUser-agent: Googlebot\nDisallow: /")
        blocked = [f for f in result["risk_findings"] if f["type"] == "SITE_WIDE_BLOCK"]
        self.assertEqual([f["agent"] for f in blocked], ["googlebot"])

    def test_homepage_only_block_is_a_warning(self):
        verdict, found = self.verdict("User-agent: *\nDisallow: /$")
        self.assertEqual(verdict, "REVIEW")
        self.assertIn("HOMEPAGE_BLOCKED", found)

    def test_normal_file_is_ok(self):
        verdict, found = self.verdict("User-agent: *\nDisallow: /admin\nAllow: /\nSitemap: https://e.com/s.xml")
        self.assertEqual((verdict, found), ("OK", []))

    def test_empty_file_is_allow_all(self):
        result, _ = robots("")
        self.assertEqual(result["verdict"], "OK")
        self.assertTrue(result["path_results"][0]["allowed"])

    def test_orphan_rules_warn(self):
        result, _ = robots("Disallow: /x\nUser-agent: *\nAllow: /")
        self.assertIn("ORPHAN_RULES", types(result))

    def test_sitemaps_are_collected(self):
        result, _ = robots("User-agent: *\nAllow: /\nSitemap: https://e.com/a.xml\nSitemap: https://e.com/b.xml")
        self.assertEqual(result["sitemaps_declared"], ["https://e.com/a.xml", "https://e.com/b.xml"])

    def test_oversize_warning_and_hard_limit(self):
        big = "User-agent: *\n" + ("Disallow: /x\n" * 50000)
        result, _ = robots(big)
        self.assertIn("OVER_500KIB", types(result))
        with self.assertRaises(RuntimeError):
            robots("a" * (handler.MAX_ROBOTS_BYTES + 1))

    def test_requires_input_and_caps_paths(self):
        with self.assertRaises(RuntimeError):
            handler.seo_audit_robots_txt({})
        with self.assertRaises(RuntimeError):
            robots("User-agent: *\nAllow: /", paths=",".join("/p%d" % i for i in range(201)))

    def test_receipt_shape(self):
        _, receipt = robots("User-agent: *\nDisallow: /")
        self.assertEqual(receipt["kind"], "seo.audit_robots_txt")
        self.assertEqual(receipt["critical_findings"], 1)


class RedirectGraph(unittest.TestCase):
    def run_rules(self, rules):
        result, _ = handler.seo_preview_redirect_graph({"redirect_rules": rules})
        return result

    def finding_types(self, result):
        return [f["type"] for f in result["findings"]]

    def test_two_node_loop(self):
        result = self.run_rules("/a -> /b\n/b -> /a")
        self.assertEqual(result["verdict"], "UNSAFE")
        loops = [f for f in result["findings"] if f["type"] == "LOOP"]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["cycle"], ["/a", "/b"])

    def test_three_node_loop_reported_once(self):
        result = self.run_rules([
            {"source": "/old-blog", "target": "/new-blog"},
            {"source": "/new-blog", "target": "/legacy-blog"},
            {"source": "/legacy-blog", "target": "/old-blog"}])
        loops = [f for f in result["findings"] if f["type"] == "LOOP"]
        self.assertEqual(len(loops), 1)
        self.assertEqual(set(loops[0]["cycle"]), {"/old-blog", "/new-blog", "/legacy-blog"})
        self.assertEqual(result["verdict"], "UNSAFE")

    def test_rule_feeding_a_loop(self):
        result = self.run_rules("/x -> /a\n/a -> /b\n/b -> /a")
        self.assertIn("FEEDS_LOOP", self.finding_types(result))

    def test_chain_reports_head_and_flattening(self):
        result = self.run_rules("/a -> /b\n/b -> /c")
        chains = [f for f in result["findings"] if f["type"] == "CHAIN"]
        self.assertEqual(len(chains), 1)
        self.assertEqual((chains[0]["source"], chains[0]["hops"], chains[0]["final_target"]), ("/a", 2, "/c"))
        self.assertEqual(result["flatten_suggestions"], [{"source": "/a", "target": "/c"}])
        self.assertEqual(result["verdict"], "REVIEW")

    def test_self_redirect(self):
        result = self.run_rules("/a -> /a")
        self.assertIn("SELF_REDIRECT", self.finding_types(result))
        self.assertEqual(result["verdict"], "UNSAFE")

    def test_conflicting_sources_are_flagged_not_silently_collapsed(self):
        result = self.run_rules("/a -> /b\n/a -> /c")
        conflict = [f for f in result["findings"] if f["type"] == "CONFLICTING_SOURCE"]
        self.assertEqual(conflict[0]["targets"], ["/b", "/c"])
        self.assertEqual(result["verdict"], "UNSAFE")

    def test_exact_duplicates_warn(self):
        result = self.run_rules("/a -> /b\n/a -> /b")
        self.assertEqual(self.finding_types(result), ["DUPLICATE_RULE"])
        self.assertEqual(result["verdict"], "REVIEW")

    def test_clean_rules_are_ok(self):
        self.assertEqual(self.run_rules("/a -> /b\n/c -> /d")["verdict"], "OK")

    def test_batch_size_warning(self):
        rules = "\n".join("/s%d -> /t%d" % (i, i) for i in range(26))
        result = self.run_rules(rules)
        self.assertIn("BATCH_TOO_LARGE", self.finding_types(result))
        self.assertEqual(self.run_rules("\n".join("/s%d -> /t%d" % (i, i) for i in range(25)))["verdict"], "OK")

    def test_input_formats(self):
        as_json = json.dumps([{"source": "/a", "target": "/b"}])
        for value in ("/a -> /b", "/a => /b", "/a \u2192 /b", "/a -> /b; /c -> /d", as_json, ["/a -> /b"],
                      [{"source": "/a", "target": "/b"}]):
            self.assertEqual(self.run_rules(value)["unique_sources"] >= 1, True, value)

    def test_malformed_rules_refuse_instead_of_skipping(self):
        for bad in ("/a", "/a ->", "-> /b", [{"source": "/a"}], "[not json"):
            with self.assertRaises(RuntimeError, msg=str(bad)):
                self.run_rules(bad)
        with self.assertRaises(RuntimeError):
            self.run_rules("")

    def test_rule_cap(self):
        with self.assertRaises(RuntimeError):
            self.run_rules("\n".join("/s%d -> /t%d" % (i, i) for i in range(handler.MAX_REDIRECT_RULES + 1)))


class _Site(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def _send(self, code, headers=None, body=b""):
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self._route()

    def do_GET(self):
        self._route()

    def _route(self):
        _Site.requests.append((self.command, self.path))
        base = "http://127.0.0.1:%d" % self.server.server_port
        path = self.path
        xml = {"Content-Type": "application/xml"}
        if path == "/sitemap.xml":
            urls = [base + "/ok", base + "/gone", base + "/moved", base + "/noindex",
                    base + "/head-blocked", "http://off-host.invalid/x", "ftp://127.0.0.1/x",
                    "http://localhost:%d/leak" % self.server.server_port]
            body = ("<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' "
                    "xmlns:image='http://www.google.com/schemas/sitemap-image/1.1'>"
                    + "".join("<url><loc>%s</loc><image:image><image:loc>%s/img.png</image:loc></image:image></url>"
                              % (u, base) for u in urls) + "</urlset>").encode()
            return self._send(200, xml, body)
        if path == "/clean.xml":
            body = ("<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>%s/ok</loc></url>"
                    "</urlset>" % base).encode()
            return self._send(200, xml, body)
        if path == "/index.xml":
            body = ("<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                    "<sitemap><loc>%s/sitemap.xml</loc></sitemap><sitemap><loc>%s/clean.xml</loc></sitemap>"
                    "</sitemapindex>" % (base, base)).encode()
            return self._send(200, xml, body)
        if path == "/bomb.xml":
            return self._send(200, xml, b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'>]><urlset>&a;</urlset>")
        if path == "/broken.xml":
            return self._send(200, xml, b"<urlset><url>")
        if path == "/wrongroot.xml":
            return self._send(200, xml, b"<html></html>")
        if path == "/redirecting-sitemap.xml":
            return self._send(302, {"Location": "/sitemap.xml"})
        if path == "/ok":
            return self._send(200, {}, b"ok")
        if path == "/gone":
            return self._send(404)
        if path == "/moved":
            return self._send(301, {"Location": "/ok"})
        if path == "/noindex":
            return self._send(200, {"X-Robots-Tag": "noindex, nofollow"}, b"x")
        if path == "/head-blocked":
            return self._send(405 if self.command == "HEAD" else 200, {}, b"x")
        return self._send(404)


class SitemapCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = "127.0.0.1:%d" % cls.server.server_port
        cls.base = "http://" + cls.host

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Site.requests.clear()
        self.configure({"SEO_SITE_HOST": self.host})

    def tearDown(self):
        handler.__dict__.pop("__rc_helpers__", None)

    def configure(self, entry):
        handler.__dict__["__rc_helpers__"] = {"vault_get": lambda name: entry if name == "seo" else None}

    def run_check(self, path, **extra):
        return handler.seo_verify_sitemap_urls(dict({"sitemap_url": self.base + path}, **extra))

    def test_finds_real_problems_and_pins_requests_to_host(self):
        result, receipt = self.run_check("/sitemap.xml")
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertEqual(result["entries_in_sitemap"], 8)
        self.assertEqual(result["checked"], 5)
        self.assertEqual(result["off_host_skipped"], 3)
        self.assertNotIn("/leak", [path for _, path in _Site.requests])
        issues = {p["url"].rsplit("/", 1)[-1]: p["issue"] for p in result["problems"]}
        self.assertEqual(issues, {"gone": "CLIENT_ERROR", "moved": "REDIRECT", "noindex": "NOINDEX_HEADER"})
        moved = [p for p in result["problems"] if p["issue"] == "REDIRECT"][0]
        self.assertEqual((moved["status"], moved["location"]), (301, "/ok"))
        self.assertEqual(result["status_counts"], {"200": 3, "404": 1, "301": 1})
        self.assertEqual(receipt["checked"], 5)
        self.assertEqual(receipt["problems"], 3)

    def test_redirects_are_never_followed(self):
        self.run_check("/sitemap.xml")
        moved_hits = [r for r in _Site.requests if r[1] == "/moved"]
        self.assertTrue(moved_hits)
        # /ok is requested once by its own sitemap entry; /moved never causes a second request to it
        self.assertEqual(sum(1 for _, p in _Site.requests if p == "/ok"), 1)

    def test_head_falls_back_to_get(self):
        self.run_check("/sitemap.xml")
        self.assertIn(("HEAD", "/head-blocked"), _Site.requests)
        self.assertIn(("GET", "/head-blocked"), _Site.requests)

    def test_image_locs_are_not_counted_as_pages(self):
        result, _ = self.run_check("/sitemap.xml")
        self.assertFalse(any("img.png" in p["url"] for p in result["problems"]))
        self.assertEqual(result["entries_in_sitemap"], 8)

    def test_max_urls_truncates(self):
        result, _ = self.run_check("/sitemap.xml", max_urls="2")
        self.assertEqual(result["checked"], 2)
        self.assertTrue(result["truncated"])

    def test_clean_sitemap_is_ok(self):
        result, _ = self.run_check("/clean.xml")
        self.assertEqual((result["verdict"], result["problems_total"], result["checked"]), ("OK", 0, 1))

    def test_index_is_listed_not_expanded(self):
        result, _ = self.run_check("/index.xml")
        self.assertEqual(result["verdict"], "NOT_CHECKED_INDEX")
        self.assertEqual(len(result["child_sitemaps"]), 2)
        self.assertEqual(result["checked"], 0)
        self.assertEqual([p for _, p in _Site.requests], ["/index.xml"])

    def test_refuses_when_host_not_configured(self):
        self.configure({})
        with self.assertRaises(RuntimeError):
            self.run_check("/sitemap.xml")
        self.assertEqual(_Site.requests, [])

    def test_refuses_off_host_sitemap_without_any_request(self):
        for bad in ("http://off-host.invalid/sitemap.xml", "file:///etc/passwd", "ftp://127.0.0.1/s.xml",
                    "http://user:pw@" + self.host + "/sitemap.xml"):
            with self.assertRaises(RuntimeError, msg=bad):
                handler.seo_verify_sitemap_urls({"sitemap_url": bad})
        self.assertEqual(_Site.requests, [])

    def test_pin_is_enforced_even_when_the_target_is_reachable(self):
        self.configure({"SEO_SITE_HOST": "127.0.0.1:1"})
        with self.assertRaises(RuntimeError):
            self.run_check("/sitemap.xml")
        self.assertEqual(_Site.requests, [])

    def test_opener_speaks_only_http(self):
        opener = handler._build_opener()
        names = {type(h).__name__ for h in opener.handlers}
        self.assertTrue({"HTTPHandler", "HTTPSHandler"} <= names)
        self.assertFalse(names & {"FileHandler", "FTPHandler", "DataHandler", "ProxyHandler"})
        with self.assertRaises(Exception):
            opener.open("file:///etc/hostname")

    def test_refuses_entity_declarations(self):
        with self.assertRaises(RuntimeError):
            self.run_check("/bomb.xml")

    def test_refuses_malformed_and_wrong_root(self):
        for path in ("/broken.xml", "/wrongroot.xml"):
            with self.assertRaises(RuntimeError, msg=path):
                self.run_check(path)

    def test_refuses_redirecting_sitemap(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.run_check("/redirecting-sitemap.xml")
        self.assertIn("302", str(ctx.exception))

    def test_refuses_missing_sitemap_and_gzip(self):
        with self.assertRaises(RuntimeError):
            self.run_check("/nope.xml")
        with self.assertRaises(RuntimeError):
            self.run_check("/sitemap.xml.gz")

    def test_size_cap(self):
        original = handler.MAX_SITEMAP_BYTES
        handler.MAX_SITEMAP_BYTES = 50
        try:
            with self.assertRaises(RuntimeError):
                self.run_check("/sitemap.xml")
        finally:
            handler.MAX_SITEMAP_BYTES = original

    def test_unreachable_url_is_reported(self):
        handler.__dict__["__rc_helpers__"] = {"vault_get": lambda name: {"SEO_SITE_HOST": "127.0.0.1:9"}}
        status, headers, error = handler._probe_url(
            handler._build_opener(), "http://127.0.0.1:9/x")
        self.assertIsNone(status)
        self.assertTrue(error)
        self.assertEqual(handler._classify("http://127.0.0.1:9/x", status, headers, error)["issue"], "UNREACHABLE")


class ManifestConsistency(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            return json.load(handle)

    def check(self, name, expected_commands, expected_network):
        manifest = self.load(name)
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["requires"]["filesystem_writes"], [])
        self.assertIs(manifest["requires"]["subprocess"], False)
        self.assertEqual(manifest["requires"]["network"], expected_network)
        self.assertEqual([c["id"] for c in manifest["commands"]], expected_commands)
        declared = {s["name"] for s in manifest.get("secrets", [])}
        used = set()
        for cmd in manifest["commands"]:
            function = getattr(handler, cmd["id"].replace(".", "_"), None)
            self.assertTrue(callable(function), cmd["id"])
            self.assertEqual(cmd["inputs"], cmd["input_schema"], cmd["id"])
            self.assertEqual(cmd["provider"], "seo")
            self.assertEqual((cmd["mode"], cmd["side_effects"]), ("read", "none"))
            self.assertTrue(cmd["input_schema"], cmd["id"])
            self.assertTrue(set(cmd["requires"]) <= declared, cmd["id"])
            used.update(cmd["requires"])
        self.assertEqual(used, declared)

    def test_default_manifest(self):
        self.check("module.json", ["seo.audit_robots_txt", "seo.preview_redirect_graph"], [])

    def test_sitemap_manifest(self):
        self.check("module.with-sitemap.json",
                   ["seo.audit_robots_txt", "seo.preview_redirect_graph", "seo.verify_sitemap_urls"],
                   ["REPLACE-ME.example.com"])

    def test_default_manifest_has_no_network_and_no_credentials(self):
        manifest = self.load("module.json")
        self.assertNotIn("secrets", manifest)
        self.assertEqual(manifest["requires"]["network"], [])


class FlattenedInput(unittest.TestCase):
    """A single-line form field can strip newlines; that must never produce a false OK."""

    def test_flattened_robots_refuses_instead_of_passing(self):
        with self.assertRaises(RuntimeError) as ctx:
            robots("User-agent: * Disallow: /", "/products")
        self.assertIn("line breaks were lost", str(ctx.exception))

    def test_typed_backslash_n_is_recovered_and_still_blocks(self):
        result, _ = robots("User-agent: *\\nDisallow: /", "/products")
        self.assertEqual(result["verdict"], "BLOCKS_SITE")
        self.assertFalse(result["path_results"][0]["allowed"])

    def test_single_directive_on_one_line_is_not_refused(self):
        # One directive is unambiguous, so it is analysed normally. With no User-agent line it is an orphan rule.
        result, _ = robots("Disallow: /admin", "/admin/x")
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertEqual(types(result), ["ORPHAN_RULES"])
        result, _ = robots("User-agent: *", "/admin/x")
        self.assertEqual(result["verdict"], "OK")

    def test_flattened_redirects_refuse_instead_of_passing(self):
        for flat in ("/a -> /b /b -> /a", "/a -> /b -> /a", "/a  b -> /c"):
            with self.assertRaises(RuntimeError, msg=flat):
                handler.seo_preview_redirect_graph({"redirect_rules": flat})

    def test_semicolon_separated_redirects_work_on_one_line(self):
        result, _ = handler.seo_preview_redirect_graph({"redirect_rules": "/a -> /b; /b -> /a"})
        self.assertEqual(result["verdict"], "UNSAFE")


if __name__ == "__main__":
    unittest.main()