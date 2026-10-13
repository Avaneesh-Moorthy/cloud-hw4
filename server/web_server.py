"""
HW4 service 1 - a plain-Python web server that runs on a VM.

  GET  /<file>                       -> 200 + file contents   (file is in the URL path)
  POST /  body {"filename": "<file>"}, form field filename=<file>, or plain text
                                     -> 200 + file contents   (file is in the payload)
  file not in bucket                 -> 404  logged to Cloud Logging, severity WARNING
  PUT/DELETE/HEAD/CONNECT/OPTIONS/TRACE/PATCH (and any other method)
                                     -> 501  logged to Cloud Logging, severity ERROR
  X-country is an export-restricted  -> 400  logged to Cloud Logging, severity CRITICAL,
  country                                    and published to Pub/Sub for service 2
  GET /                              -> small HTML form (to send a POST from a browser)

Uses only the standard library HTTP server (ThreadingHTTPServer: one thread per
connection) plus Google's Cloud Storage, Pub/Sub and Cloud Logging client libraries.
On the VM it authenticates automatically as the VM's service account.

Run:  python3 web_server.py --port 80 --bucket B --prefix pages/ --topic projects/P/topics/T
"""

import argparse
import datetime
import html
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

FORBIDDEN = {"north korea", "iran", "cuba", "myanmar", "iraq",
             "libya", "sudan", "zimbabwe", "syria"}
SUPPORTED = {"GET", "POST"}

CFG = {"bucket": "", "prefix": "pages/", "topic": ""}
STATE = {"bucket": None, "publisher": None, "log": None}   # filled in by setup()

# request counters, read by monitor.py during the stress test
STATS = {"requests": 0, "by_status": {}, "started": time.time()}
STATS_LOCK = threading.Lock()


def count(status):
    with STATS_LOCK:
        STATS["requests"] += 1
        k = str(status)
        STATS["by_status"][k] = STATS["by_status"].get(k, 0) + 1


def stats_writer(path, every=1.0):
    while True:
        with STATS_LOCK:
            snap = json.dumps({**STATS, "time": time.time()})
        try:
            with open(path + ".tmp", "w") as f:
                f.write(snap)
            os.replace(path + ".tmp", path)
        except OSError:
            pass
        time.sleep(every)


# ------------------------------------------------------------------ logging

def setup_logging(use_cloud):
    """WARNING/ERROR/CRITICAL records become Cloud Logging entries with that
    severity. Fields passed in extra={"json_fields": {...}} become the entry's
    jsonPayload (a structured log). The handler sends entries from a
    background thread, so logging never blocks a request."""
    log = logging.getLogger("hw4-web-server")
    log.setLevel(logging.INFO)
    log.propagate = False
    if use_cloud:
        import google.cloud.logging
        from google.cloud.logging.handlers import CloudLoggingHandler
        client = google.cloud.logging.Client()
        log.addHandler(CloudLoggingHandler(client, name="hw4-web-server"))
    else:  # local testing: same structure, printed as JSON
        class J(logging.Formatter):
            def format(self, r):
                return json.dumps({"severity": r.levelname, "message": r.getMessage(),
                                   **getattr(r, "json_fields", {})})
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(J())
        log.addHandler(h)
    return log


def log_event(severity, status, reason, req, **extra):
    fields = {"status": status, "reason": reason, "method": req.command,
              "path": req.path, "client_ip": req.client_address[0],
              "country": req.headers.get("X-country"),
              "user_agent": req.headers.get("User-Agent")}
    fields.update(extra)
    # simple print as well (goes to the VM's system journal)
    print(f"{severity} {status}: {reason} | method={req.command} path={req.path}", flush=True)
    STATE["log"].log(getattr(logging, severity), f"{status} {reason}",
                     extra={"json_fields": fields,
                            "http_request": {"requestMethod": req.command,
                                             "requestUrl": req.path,
                                             "status": status,
                                             "remoteIp": req.client_address[0]}})


# ------------------------------------------------------------------ storage

def candidates(name):
    """'12.html', 'pages/12.html' and '<bucket>/pages/12.html' all work."""
    name = unquote(name).lstrip("/")
    if name.startswith(CFG["bucket"] + "/"):
        name = name[len(CFG["bucket"]) + 1:]
    if name.startswith(CFG["prefix"]):
        return [name]
    return [CFG["prefix"] + name.split("/")[-1], name]


def fetch(name):
    """Return the file's bytes, or None if it is not in the bucket."""
    from google.api_core.exceptions import NotFound
    for obj in candidates(name):
        if not obj or obj.endswith("/"):
            continue
        try:
            return STATE["bucket"].blob(obj).download_as_bytes()
        except NotFound:
            continue
    return None


def publish_forbidden(msg):
    if not CFG["topic"]:
        return
    fut = STATE["publisher"].publish(CFG["topic"], json.dumps(msg).encode(),
                                     country=msg["country"])
    fut.add_done_callback(lambda f: f.exception() and
                          print("Pub/Sub publish failed:", f.exception(), flush=True))


FORM = b"""<!doctype html><html><body style="font-family:sans-serif">
<h2>HW4 file server (VM)</h2>
<p>GET: append a file name to the URL, e.g. <code>/123.html</code></p>
<form method="POST"><label>File name (sent with POST):
<input name="filename" value="123.html"></label> <button type="submit">POST</button></form>
</body></html>"""


# ------------------------------------------------------------------ handler

class Handler(BaseHTTPRequestHandler):
    server_version = "HW4FileServer/1.0"
    protocol_version = "HTTP/1.0"      # one request per connection, like the client

    def log_message(self, fmt, *args):  # no per-request access log (keeps stress tests fast)
        pass

    def send(self, status, body, ctype="text/plain; charset=utf-8"):
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        count(status)

    # 3. every method other than GET/POST -> 501, severity ERROR
    def not_implemented(self):
        log_event("ERROR", 501, "method not implemented", self)
        self.send(501, b"501 Not Implemented\n")

    def __getattr__(self, name):        # do_PUT, do_DELETE, do_TRACE, do_FOO ...
        if name.startswith("do_"):
            return self.not_implemented
        raise AttributeError(name)

    def do_GET(self):
        self.serve(self.path.split("?")[0].lstrip("/"))

    def do_POST(self):
        n = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
        raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        ctype = self.headers.get("Content-Type", "")
        name = ""
        if "json" in ctype:
            try:
                d = json.loads(raw)
                name = str(d.get("filename") or d.get("file") or "")
            except (ValueError, AttributeError):
                pass
        elif "form" in ctype:
            q = parse_qs(raw)
            name = (q.get("filename") or q.get("file") or [""])[0]
        else:
            name = raw.strip()
        self.serve(name.lstrip("/"))

    def serve(self, filename):
        if self.command == "GET" and filename == "":
            return self.send(200, FORM, "text/html; charset=utf-8")

        # 7. export restrictions
        country = (self.headers.get("X-country") or "").strip()
        if country.lower() in FORBIDDEN:
            msg = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   "country": country, "file": filename, "method": self.command,
                   "client_ip": self.headers.get("X-client-IP") or self.client_address[0]}
            publish_forbidden(msg)
            log_event("CRITICAL", 400, "forbidden country", self, forbidden=msg)
            return self.send(400, f"400 Permission denied: export to {html.escape(country)} "
                                  f"is prohibited\n".encode())

        # 2. missing file -> 404, severity WARNING
        data = fetch(filename) if filename else None
        if data is None:
            log_event("WARNING", 404, "file not found", self, file=filename)
            return self.send(404, f"404 Not Found: {html.escape(filename)}\n".encode())

        # 1. found
        self.send(200, data, "text/html; charset=utf-8")


def setup(args):
    CFG.update(bucket=args.bucket, prefix=args.prefix, topic=args.topic)
    STATE["log"] = setup_logging(not args.local)
    if not args.local:
        from google.cloud import pubsub_v1, storage
        STATE["bucket"] = storage.Client().bucket(args.bucket)
        STATE["publisher"] = pubsub_v1.PublisherClient()


def main():
    ap = argparse.ArgumentParser(description="HW4 file server")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--bucket", default="cedar-pottery-508921-u1-pages")
    ap.add_argument("--prefix", default="pages/")
    ap.add_argument("--topic", default="")
    ap.add_argument("--stats-file", default="/var/tmp/hw4_stats.json")
    ap.add_argument("--local", action="store_true", help="testing only: no Google clients")
    args = ap.parse_args()
    setup(args)
    threading.Thread(target=stats_writer, args=(args.stats_file,), daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    srv.request_queue_size = 128
    print(f"HW4 file server on :{args.port}, bucket={args.bucket}/{args.prefix}, "
          f"topic={args.topic or '(none)'}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
