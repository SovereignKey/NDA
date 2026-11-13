/**
 * NDA signing receiver (Google Apps Script web app).
 *
 * Receives the signed agreement from the click-through page, stores the PDF and
 * signing record in Google Drive, and emails the signed copy to GSP and to the signer.
 * Also serves the countersign flow: GET ?action=record&id=…&token=… and POST {action:"countersign"}.
 *
 * Script properties (Project Settings → Script properties):
 *   NOTIFY_TO    where signed copies go, e.g. mhuberty@gspartners.com   (required)
 *   ADMIN_TOKEN  secret for the countersign/admin links                 (required, any long random string)
 *   FOLDER_NAME  Drive folder for records (default "NDA Signatures")
 *   PAGE_URL     the signing page, e.g. https://sovereignkey.github.io/NDA/ (used in the countersign link)
 */

var PROPS = PropertiesService.getScriptProperties();

function cfg_(key, fallback) {
  var v = PROPS.getProperty(key);
  return v ? v : fallback;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function folder_() {
  var name = cfg_('FOLDER_NAME', 'NDA Signatures');
  var it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}

function recordFolder_(id, create) {
  var root = folder_();
  var it = root.getFoldersByName(id);
  if (it.hasNext()) return it.next();
  return create ? root.createFolder(id) : null;
}

function readJsonFile_(folder, name) {
  var it = folder.getFilesByName(name);
  if (!it.hasNext()) return null;
  return JSON.parse(it.next().getBlob().getDataAsString('UTF-8'));
}

function writeFile_(folder, name, blob) {
  var it = folder.getFilesByName(name);
  while (it.hasNext()) it.next().setTrashed(true);
  return folder.createFile(blob.setName(name));
}

function safeName_(s) {
  return String(s || 'file').replace(/[^\w\- .]+/g, '').trim() || 'file';
}

function sha256_(s) {
  var raw = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8);
  return raw.map(function (b) { return ('0' + (b & 0xff).toString(16)).slice(-2); }).join('');
}

function validate_(rec, countersign) {
  var need = { counterparty: ['name', 'entity', 'address', 'email'], signer: ['name', 'title', 'email'] };
  for (var k in need) {
    if (!rec[k] || typeof rec[k] !== 'object') return 'missing ' + k;
    for (var i = 0; i < need[k].length; i++) if (!String(rec[k][need[k][i]] || '').trim()) return 'missing ' + k + '.' + need[k][i];
  }
  var keys = ['signedAt', 'effectiveDate', 'documentId', 'agreementText', 'textHash'];
  for (var j = 0; j < keys.length; j++) if (!rec[keys[j]]) return 'missing ' + keys[j];
  if (!rec.signature || String(rec.signature.image || '').indexOf('data:image/png;base64,') !== 0) return 'missing signature';
  if (sha256_(rec.agreementText) !== rec.textHash) return 'agreement text hash mismatch';
  if (countersign) {
    var g = rec.gsp || {};
    if (!g.signer || !g.signer.name || !g.signer.title) return 'missing GSP signer';
    if (!g.signature || String(g.signature.image || '').indexOf('data:image/png;base64,') !== 0) return 'missing GSP signature';
  }
  return null;
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.action === 'record') {
    if (!p.token || p.token !== cfg_('ADMIN_TOKEN', '')) return json_({ error: 'forbidden' });
    var f = recordFolder_(String(p.id || ''), false);
    var rec = f && readJsonFile_(f, 'record.json');
    return rec ? json_(rec) : json_({ error: 'no such record' });
  }
  if (p.action === 'list') {
    if (!p.token || p.token !== cfg_('ADMIN_TOKEN', '')) return json_({ error: 'forbidden' });
    var out = [], it = folder_().getFolders();
    while (it.hasNext()) {
      var fo = it.next(), r = readJsonFile_(fo, 'record.json');
      if (r) out.push({ id: r.id, counterparty: r.counterparty.name, signer: r.signer.name, signedAtLocal: r.signedAtLocal, executed: !!r.gsp, folder: fo.getUrl() });
    }
    return json_(out);
  }
  return json_({ ok: true, service: 'NDA signing receiver' });
}

function doPost(e) {
  var body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return json_({ error: 'invalid JSON body' }); }
  var rec = body.record, pdfB64 = body.pdf;
  if (!rec || typeof rec !== 'object' || !pdfB64) return json_({ error: 'record and pdf are required' });
  var pdfBytes;
  try { pdfBytes = Utilities.base64Decode(pdfB64); } catch (err) { return json_({ error: 'pdf must be base64' }); }
  var pdfBlob = Utilities.newBlob(pdfBytes, 'application/pdf');
  var notify = cfg_('NOTIFY_TO', '').split(',').map(function (s) { return s.trim(); }).filter(String);
  var deal = rec.deal || 'Mutual CNDA';

  if (body.action === 'countersign') {
    if (!body.token || body.token !== cfg_('ADMIN_TOKEN', '')) return json_({ error: 'forbidden' });
    var folder = recordFolder_(String(body.id || ''), false);
    var stored = folder && readJsonFile_(folder, 'record.json');
    if (!stored) return json_({ error: 'no such record' });
    if (stored.gsp) return json_({ error: 'already countersigned' });
    if (rec.documentId !== stored.documentId || rec.textHash !== stored.textHash || rec.signedAt !== stored.signedAt) return json_({ error: 'record mismatch' });
    var err2 = validate_(rec, true);
    if (err2) return json_({ error: err2 });
    stored.gsp = rec.gsp;
    stored.gsp.serverReceivedAt = new Date().toISOString();
    writeFile_(folder, 'record.json', Utilities.newBlob(JSON.stringify(stored, null, 2), 'application/json'));
    var execName = safeName_(body.fileName || (deal + ' - Mutual CNDA - ' + stored.counterparty.name + ' - EXECUTED.pdf'));
    writeFile_(folder, execName, pdfBlob);
    var recipients = [stored.signer.email].concat(notify).join(',');
    MailApp.sendEmail({
      to: recipients,
      subject: 'Fully executed: ' + deal + ' Mutual CNDA - ' + stored.counterparty.name,
      body: 'Attached is the fully executed Mutual Confidentiality and Non-Disclosure Agreement between George Smith Partners, Inc. and ' +
        stored.counterparty.name + '.\n\nEffective Date: ' + stored.effectiveDate + '\nDocument ID: ' + stored.documentId,
      attachments: [pdfBlob.setName(execName)]
    });
    return json_({ id: stored.id, message: 'Fully executed copy stored and emailed to both parties.' });
  }

  // Counterparty signature
  var err = validate_(rec, false);
  if (err) return json_({ error: err });
  var now = new Date();
  var id = Utilities.formatDate(now, 'UTC', 'yyyyMMdd-HHmmss') + '-' + String(rec.documentId).slice(0, 8);
  rec.id = id;
  rec.serverReceivedAt = now.toISOString();
  var f = recordFolder_(id, true);
  writeFile_(f, 'record.json', Utilities.newBlob(JSON.stringify(rec, null, 2), 'application/json'));
  var fname = safeName_(body.fileName || (deal + ' - Mutual CNDA - ' + rec.counterparty.name + ' - signed by counterparty.pdf'));
  writeFile_(f, fname, pdfBlob);

  var page = cfg_('PAGE_URL', '');
  var countersignLink = page ? (page + (page.indexOf('?') < 0 ? '?' : '&') + 'countersign=' + encodeURIComponent(id) + '&token=' + encodeURIComponent(cfg_('ADMIN_TOKEN', ''))) : '(set PAGE_URL in script properties)';
  if (notify.length) {
    MailApp.sendEmail({
      to: notify.join(','),
      subject: 'Signed: ' + deal + ' Mutual CNDA - ' + rec.counterparty.name,
      body: rec.signer.name + ' (' + rec.signer.title + ') signed for ' + rec.counterparty.name + ' at ' + rec.signedAtLocal + '.\n' +
        'Signer email: ' + rec.signer.email + '\nDocument ID: ' + rec.documentId + '\nRecord: ' + id + '\nDrive folder: ' + f.getUrl() +
        '\n\nCountersign for GSP (keep this link private):\n' + countersignLink,
      attachments: [pdfBlob.setName(fname)]
    });
  }
  try {
    MailApp.sendEmail({
      to: rec.signer.email,
      subject: 'Your signed copy: ' + deal + ' Mutual CNDA',
      body: 'Thank you, ' + rec.signer.name + '. Attached is the agreement as you signed it on ' + rec.signedAtLocal + '.\n' +
        'Document ID: ' + rec.documentId + '\n\nYou will receive the fully executed copy once George Smith Partners countersigns.',
      attachments: [pdfBlob.setName(fname)]
    });
  } catch (mailErr) { /* signer copy is best-effort */ }
  return json_({ id: id, message: 'Delivered to George Smith Partners. A copy has been emailed to you.' });
}
