# Maple Condo Development – Mutual CNDA click-through signing

A self-contained e-signature page for the George Smith Partners Mutual Confidentiality and
Non-Disclosure Agreement. The counterparty opens a link, fills in their entity details, reads the
agreement (blanks fill in live), draws or types a signature, accepts the E-SIGN/UETA
acknowledgement and clicks **Sign & Execute Agreement**. The page generates a PDF (agreement +
signature page + electronic signature certificate with SHA-256 document ID, timestamp, IP, browser)
and delivers it to the server. GSP then countersigns from the admin page, which produces the fully
executed PDF.

No dependencies beyond Python 3 (standard library) and the vendored jsPDF build.

## Files

| File | Purpose |
|---|---|
| `index.html` | The signing page (also the countersign page in `?countersign=` mode) |
| `agreement.js` | The agreement text, transcribed from the Word CNDA. Edit here if the terms change |
| `config.js` | Return email, submit endpoint, optional GSP signer prefill |
| `server.py` | Serves the page, stores signed records in `signed/`, admin page, countersign, optional SMTP email |
| `build.py` | Bundles everything into one HTML file in `dist/` for static hosting or sending as an attachment |
| `vendor/jspdf.umd.min.js` | jsPDF 2.5.1 (PDF generation in the browser) |
| `signed/` | One folder per signature: `record.json`, `counterparty-signed.pdf`, `fully-executed.pdf` |

## Run

```bash
python3 server.py
```

Prints the signing URL (port 8790 by default, `PORT=…` to change) and the admin URL. The admin
token is generated on first run and stored in `.admin-token` (or set `ADMIN_TOKEN`).

Prefill the counterparty's name and email in the link you send:

```
https://<your-host>/?name=First%20Last&email=name%40company.com
```

Other prefill parameters: `company`, `entity`, `address`, `title`.

## Sharing the link with the counterparty

The server must be reachable from the internet for the "click through" link to work. Options,
simplest first:

1. **Tunnel from this Mac** (fastest; keep the laptop awake and the server running until signed):
   `brew install cloudflared` then `cloudflared tunnel --url http://localhost:8790`. It prints a
   public `https://….trycloudflare.com` URL. Put that in the email. (`ngrok http 8790` works too.)
2. **Deploy `server.py`** to any host that runs Python (Render, Railway, Fly.io, a small VM). Set
   `ADMIN_TOKEN` and, if you want automatic email delivery, the SMTP variables below.
3. **No server at all**: run `python3 build.py` and either host
   `dist/Maple Condo Development - Mutual CNDA - Click to Sign.html` on any static host
   (Netlify Drop, S3, GitHub Pages) or attach it to the email. In this mode the signed PDF downloads
   to the signer's computer and the page opens a pre-addressed email (to `returnEmail` in
   `config.js`) for them to attach it to. Countersign by opening the same page and signing in the
   GSP block is not available without the server; sign the returned PDF however you normally do.

## Countersigning (GSP)

Open the admin URL, click **Countersign now** next to the record, enter your name/title/email, sign,
and click **Countersign & Execute Agreement**. The fully executed PDF is stored as
`signed/<id>/fully-executed.pdf` and emailed to both parties if SMTP is configured; otherwise
download it from the admin page and send it to the counterparty.

## Optional email delivery

Set these environment variables before starting the server:

```
SMTP_HOST=smtp.office365.com   SMTP_PORT=587
SMTP_USER=you@gspartners.com    SMTP_PASS=…    SMTP_FROM=you@gspartners.com
NOTIFY_TO=you@gspartners.com    # comma-separated; receives each signed copy
```

On signature the server emails the counterparty-signed PDF to `NOTIFY_TO` and a copy to the signer;
on countersignature it emails the fully executed PDF to the signer and `NOTIFY_TO`.

## Integrity

`documentId` = SHA-256 of {agreement text hash, counterparty details, signer details, signing
timestamp, effective date}. `record.json` holds everything needed to recompute it. The server
rejects records whose agreement text does not match its hash and refuses countersignature on a
record whose identifiers differ from the stored one.
