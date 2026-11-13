#!/usr/bin/env python3
"""Click-through NDA signing server (standard library only).

  python3 server.py                 # serves on http://localhost:8790
  PORT=9000 python3 server.py       # custom port

Routes
  GET  /                               signing page
  POST /api/sign                       counterparty signature -> signed/<id>/
  GET  /admin?token=...                list of signing records, countersign links
  GET  /api/record/<id>?token=...      record JSON (used by the countersign page)
  POST /api/countersign/<id>?token=... GSP countersignature -> fully executed PDF
  GET  /admin/file/<id>/<name>?token=  download a stored PDF / record

Optional email delivery (set as environment variables):
  SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM, NOTIFY_TO (comma separated)
"""
import base64, datetime, hashlib, html, json, os, re, secrets, smtplib, sys, threading
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
SIGNED = os.path.join(ROOT, "signed")
STATIC = {"/": "index.html", "/index.html": "index.html", "/agreement.js": "agreement.js",
          "/config.js": "config.js", "/vendor/jspdf.umd.min.js": "vendor/jspdf.umd.min.js"}
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".pdf": "application/pdf", ".json": "application/json; charset=utf-8"}
MAX_BODY = 20 * 1024 * 1024
LOCK = threading.Lock()


def admin_token():
    tok = os.environ.get("ADMIN_TOKEN")
    if tok:
        return tok
    path = os.path.join(ROOT, ".admin-token")
    if os.path.exists(path):
        return open(path).read().strip()
    tok = secrets.token_urlsafe(24)
    with open(path, "w") as f:
        f.write(tok)
    os.chmod(path, 0o600)
    return tok


TOKEN = admin_token()


def send_mail(to, subject, body, attachments=()):
    host = os.environ.get("SMTP_HOST")
    if not host or not to:
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "nda@localhost"))
    msg["To"] = ", ".join(to) if isinstance(to, (list, tuple)) else to
    msg["Subject"] = subject
    msg.set_content(body)
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            if port != 465:
                s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[mail] failed: {e}", file=sys.stderr)
        return False


def safe_name(s):
    return re.sub(r"[^\w\- .]+", "", s).strip() or "file"


def validate_record(rec, countersign=False):
    need = {"counterparty": ["name", "entity", "address", "email"], "signer": ["name", "title", "email"]}
    for k, subs in need.items():
        if not isinstance(rec.get(k), dict):
            return f"missing {k}"
        for s in subs:
            if not str(rec[k].get(s, "")).strip():
                return f"missing {k}.{s}"
    for k in ("signedAt", "effectiveDate", "documentId", "agreementText", "textHash"):
        if not rec.get(k):
            return f"missing {k}"
    sig = rec.get("signature") or {}
    if not str(sig.get("image", "")).startswith("data:image/png;base64,"):
        return "missing signature"
    if countersign:
        g = rec.get("gsp") or {}
        if not g.get("signer") or not g["signer"].get("name") or not g["signer"].get("title"):
            return "missing GSP signer"
        if not str((g.get("signature") or {}).get("image", "")).startswith("data:image/png;base64,"):
            return "missing GSP signature"
    # Integrity: text hash must match the agreement text.
    if hashlib.sha256(rec["agreementText"].encode("utf-8")).hexdigest() != rec["textHash"]:
        return "agreement text hash mismatch"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "NDASign/1.0"

    # ---- helpers ----
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _authed(self, q):
        return secrets.compare_digest(q.get("token", [""])[0], TOKEN)

    def _ip(self):
        fwd = self.headers.get("X-Forwarded-For") or self.headers.get("CF-Connecting-IP")
        return (fwd.split(",")[0].strip() if fwd else self.client_address[0])

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            raise ValueError("bad body size")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), fmt % args))
        sys.stdout.flush()

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        if path in STATIC:
            fp = os.path.join(ROOT, STATIC[path])
            with open(fp, "rb") as f:
                return self._send(200, f.read(), MIME[os.path.splitext(fp)[1]])
        if path == "/admin":
            if not self._authed(q):
                return self._send(403, "Forbidden: add ?token=<ADMIN_TOKEN>", "text/plain")
            return self._send(200, self.admin_page(q["token"][0]), "text/html; charset=utf-8")
        m = re.fullmatch(r"/api/record/([\w\-]+)", path)
        if m:
            if not self._authed(q):
                return self._json(403, {"error": "forbidden"})
            fp = os.path.join(SIGNED, m.group(1), "record.json")
            if not os.path.exists(fp):
                return self._json(404, {"error": "no such record"})
            with open(fp, "rb") as f:
                return self._send(200, f.read())
        m = re.fullmatch(r"/admin/file/([\w\-]+)/([\w\-. ]+)", path)
        if m:
            if not self._authed(q):
                return self._json(403, {"error": "forbidden"})
            fp = os.path.join(SIGNED, m.group(1), m.group(2))
            if not os.path.isfile(fp) or ".." in path:
                return self._json(404, {"error": "not found"})
            disp = "inline" if q.get("inline") else "attachment"
            with open(fp, "rb") as f:
                return self._send(200, f.read(), MIME.get(os.path.splitext(fp)[1], "application/octet-stream"),
                                  {"Content-Disposition": f'{disp}; filename="{m.group(2)}"'})
        if path == "/healthz":
            return self._send(200, "ok", "text/plain")
        return self._send(404, "Not found", "text/plain")

    # ---- POST ----
    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            body = self._read_json()
        except Exception:  # noqa: BLE001
            return self._json(400, {"error": "invalid JSON body"})
        rec, pdf_b64 = body.get("record"), body.get("pdf")
        if not isinstance(rec, dict) or not pdf_b64:
            return self._json(400, {"error": "record and pdf are required"})
        try:
            pdf = base64.b64decode(pdf_b64)
        except Exception:  # noqa: BLE001
            return self._json(400, {"error": "pdf must be base64"})
        if not pdf.startswith(b"%PDF"):
            return self._json(400, {"error": "pdf is not a PDF"})

        if u.path == "/api/sign":
            err = validate_record(rec)
            if err:
                return self._json(400, {"error": err})
            now = datetime.datetime.now(datetime.timezone.utc)
            rid = now.strftime("%Y%m%d-%H%M%S") + "-" + rec["documentId"][:8]
            rec["id"] = rid
            rec["ip"] = self._ip()
            rec["serverReceivedAt"] = now.isoformat()
            d = os.path.join(SIGNED, rid)
            with LOCK:
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "record.json"), "w") as f:
                    json.dump(rec, f, indent=2)
                with open(os.path.join(d, "counterparty-signed.pdf"), "wb") as f:
                    f.write(pdf)
            print(f"[sign] {rid} {rec['counterparty']['name']} / {rec['signer']['name']} <{rec['signer']['email']}> from {rec['ip']}")
            fname = safe_name(body.get("fileName") or f"Mutual CNDA - {rec['counterparty']['name']} - signed.pdf")
            notify = [a.strip() for a in os.environ.get("NOTIFY_TO", "").split(",") if a.strip()]
            mailed = send_mail(notify, f"Signed: {rec.get('deal','')} Mutual CNDA - {rec['counterparty']['name']}",
                               f"{rec['signer']['name']} ({rec['signer']['title']}) signed for {rec['counterparty']['name']} at {rec['signedAtLocal']}.\n"
                               f"Document ID: {rec['documentId']}\nRecord: {rid}\n\nCountersign: see the admin page.",
                               [(fname, pdf)])
            send_mail(rec["signer"]["email"], f"Your signed copy: {rec.get('deal','')} Mutual CNDA",
                      f"Thank you, {rec['signer']['name']}. Attached is the agreement as you signed it on {rec['signedAtLocal']}.\n"
                      f"Document ID: {rec['documentId']}\n\nYou will receive the fully executed copy once George Smith Partners countersigns.",
                      [(fname, pdf)])
            return self._json(200, {"id": rid, "message": "Delivered to George Smith Partners." + (" Notification email sent." if mailed else "")})

        m = re.fullmatch(r"/api/countersign/([\w\-]+)", u.path)
        if m:
            if not self._authed(q):
                return self._json(403, {"error": "forbidden"})
            rid = m.group(1)
            d = os.path.join(SIGNED, rid)
            fp = os.path.join(d, "record.json")
            if not os.path.exists(fp):
                return self._json(404, {"error": "no such record"})
            with open(fp) as f:
                stored = json.load(f)
            if stored.get("gsp"):
                return self._json(409, {"error": "already countersigned"})
            # Only the gsp block may be added; everything else must be unchanged.
            for k in ("documentId", "textHash", "signedAt"):
                if rec.get(k) != stored.get(k):
                    return self._json(400, {"error": f"record mismatch on {k}"})
            err = validate_record(rec, countersign=True)
            if err:
                return self._json(400, {"error": err})
            stored["gsp"] = rec["gsp"]
            stored["gsp"]["ip"] = self._ip()
            stored["gsp"]["serverReceivedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with LOCK:
                with open(fp, "w") as f:
                    json.dump(stored, f, indent=2)
                with open(os.path.join(d, "fully-executed.pdf"), "wb") as f:
                    f.write(pdf)
            print(f"[countersign] {rid} by {rec['gsp']['signer']['name']}")
            fname = safe_name(body.get("fileName") or f"Mutual CNDA - {stored['counterparty']['name']} - EXECUTED.pdf")
            notify = [a.strip() for a in os.environ.get("NOTIFY_TO", "").split(",") if a.strip()]
            mailed = send_mail([stored["signer"]["email"]] + notify, f"Fully executed: {stored.get('deal','')} Mutual CNDA - {stored['counterparty']['name']}",
                               f"Attached is the fully executed Mutual Confidentiality and Non-Disclosure Agreement between George Smith Partners, Inc. and {stored['counterparty']['name']}.\n"
                               f"Effective Date: {stored['effectiveDate']}\nDocument ID: {stored['documentId']}", [(fname, pdf)])
            return self._json(200, {"id": rid, "message": "Fully executed copy stored." + (" Emailed to both parties." if mailed else " Email delivery is not configured, so send the downloaded copy to the counterparty.")})
        return self._json(404, {"error": "not found"})

    # ---- admin page ----
    def admin_page(self, token):
        rows = []
        if os.path.isdir(SIGNED):
            for rid in sorted(os.listdir(SIGNED), reverse=True):
                fp = os.path.join(SIGNED, rid, "record.json")
                if not os.path.isfile(fp):
                    continue
                with open(fp) as f:
                    r = json.load(f)
                e = html.escape
                status = "Fully executed" if r.get("gsp") else "Awaiting GSP countersignature"
                links = [f'<a href="/admin/file/{rid}/counterparty-signed.pdf?token={token}&inline=1" target="_blank">View counterparty-signed PDF</a>',
                         f'<a href="/admin/file/{rid}/counterparty-signed.pdf?token={token}">Download</a>',
                         f'<a href="/admin/file/{rid}/record.json?token={token}">Record</a>']
                if r.get("gsp"):
                    links.insert(0, f'<a href="/admin/file/{rid}/fully-executed.pdf?token={token}&inline=1" target="_blank"><b>View executed PDF</b></a> · <a href="/admin/file/{rid}/fully-executed.pdf?token={token}">Download</a>')
                else:
                    links.insert(0, f'<a href="/?countersign={rid}&token={token}"><b>Countersign now</b></a>')
                rows.append(f"<tr><td>{e(rid)}</td><td>{e(r['counterparty']['name'])}<br><small>{e(r['signer']['name'])}, {e(r['signer']['title'])} &lt;{e(r['signer']['email'])}&gt;</small></td>"
                            f"<td>{e(r.get('signedAtLocal',''))}</td><td>{status}</td><td>{' · '.join(links)}</td></tr>")
        body = "".join(rows) or '<tr><td colspan="5">No signatures yet.</td></tr>'
        return f"""<!doctype html><meta charset="utf-8"><title>NDA signing records</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:32px;color:#111}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e5e7eb;padding:8px 10px;text-align:left;vertical-align:top}}th{{background:#f3f4f6}}a{{color:#1d4ed8}}</style>
<h1>Mutual CNDA – signing records</h1><p>Records are stored in <code>{html.escape(SIGNED)}</code>. Keep this link private; the token in the URL grants access.</p>
<table><tr><th>Record</th><th>Counterparty / signer</th><th>Signed</th><th>Status</th><th>Files</th></tr>{body}</table>"""


def main():
    port = int(os.environ.get("PORT", "8790"))
    os.makedirs(SIGNED, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"NDA signing page:  http://localhost:{port}/")
    print(f"Admin / records:   http://localhost:{port}/admin?token={TOKEN}")
    print(f"Signed records go to {SIGNED}")
    if not os.environ.get("SMTP_HOST"):
        print("Email delivery: not configured (set SMTP_HOST/SMTP_USER/SMTP_PASS/NOTIFY_TO to enable). Records are still stored locally.")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
