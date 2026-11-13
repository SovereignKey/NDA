# Automatic delivery with Google Apps Script (about 5 minutes, once)

When this is set up, the moment the counterparty clicks **Sign & Execute Agreement** the signed PDF and
the signing record are saved to a folder in your Google Drive, the PDF is emailed to you, and a copy
is emailed to the signer. Nothing for the signer to download or send. You countersign from a link in
that email, and the fully executed PDF is then emailed to both parties.

## 1. Create the script

1. Signed in to the Google account you want the copies to come from, open https://script.google.com and click **New project**.
2. Delete the placeholder code, paste the whole contents of `apps-script/Code.gs`, and save (name the project "NDA signing receiver").

## 2. Set the script properties

Project Settings (gear icon) → **Script properties** → Add:

| Property | Value |
|---|---|
| `NOTIFY_TO` | `mhuberty@gspartners.com` |
| `ADMIN_TOKEN` | any long random string (this protects the countersign links) |
| `PAGE_URL` | `https://sovereignkey.github.io/NDA/` |
| `FOLDER_NAME` | `NDA Signatures` (optional) |

## 3. Deploy as a web app

1. **Deploy → New deployment**, type **Web app**.
2. Execute as: **Me**. Who has access: **Anyone**. (This is what lets the signing page post to it; the URL is unguessable and the script only accepts well-formed signing records.)
3. Click **Deploy**, approve the permissions it asks for (Drive and Mail), and copy the **Web app URL** (ends in `/exec`).

## 4. Point the page at it

In `config.js` set `submitUrl` to that URL, then:

```bash
python3 build.py
```

```bash
git add -A && git commit -m "Deliver signatures to Apps Script" && git push
```

GitHub Pages redeploys in about a minute. Test the live page; after signing it should say "delivered to George Smith Partners" and the email should arrive within a minute.

## Countersigning

Each notification email contains a private countersign link
(`…/NDA/?countersign=<id>&token=<ADMIN_TOKEN>`). Open it on any device, sign in the GSP block, and the
fully executed PDF is emailed to the signer and to `NOTIFY_TO`. The Drive folder `NDA Signatures/<id>/`
holds `record.json`, the counterparty-signed PDF and the executed PDF.

## Changing the code later

Edit the script, then **Deploy → Manage deployments → edit (pencil) → Version: New version → Deploy**.
The URL stays the same.
