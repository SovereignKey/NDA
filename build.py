#!/usr/bin/env python3
"""Bundle index.html + agreement.js + config.js + jsPDF into one self-contained HTML file
(for static hosting or sending as an email attachment). Output goes to dist/."""
import os, re
ROOT = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
def inline(m):
    src = m.group(1)
    js = open(os.path.join(ROOT, src), encoding="utf-8").read().replace("</script", "<\\/script")
    return f"<script>/* {src} */\n{js}\n</script>"
out = re.sub(r'<script src="([^"]+)" data-inline></script>', inline, html)

# Escape every non-ASCII character so the single file survives charset transcoding by mail systems
# (Gmail re-encoded a test copy and replaced them with "?", which broke the page).
def js_esc(s):
    return ''.join(c if ord(c) < 128 else (f"\\u{ord(c):04x}" if ord(c) < 0x10000 else
                   f"\\u{0xD800 + ((ord(c) - 0x10000) >> 10):04x}\\u{0xDC00 + ((ord(c) - 0x10000) & 0x3FF):04x}") for c in s)
def css_esc(s):
    return ''.join(c if ord(c) < 128 else f"\\{ord(c):x} " for c in s)
def html_esc(s):
    return ''.join(c if ord(c) < 128 else f"&#x{ord(c):x};" for c in s)
parts = re.split(r'(<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>)', out, flags=re.S)
for i, p in enumerate(parts):
    if p.startswith('<script'):
        m = re.match(r'(<script\b[^>]*>)(.*)(</script>)$', p, flags=re.S); parts[i] = m.group(1) + js_esc(m.group(2)) + m.group(3)
    elif p.startswith('<style'):
        m = re.match(r'(<style\b[^>]*>)(.*)(</style>)$', p, flags=re.S); parts[i] = m.group(1) + css_esc(m.group(2)) + m.group(3)
    else:
        parts[i] = html_esc(p)
out = ''.join(parts)
assert all(ord(c) < 128 for c in out), "non-ASCII remained"
os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
dest = os.path.join(ROOT, "dist", "Maple Condo Development - Mutual CNDA - Click to Sign.html")
open(dest, "w", encoding="utf-8").write(out)
print("wrote", dest, f"({os.path.getsize(dest)//1024} KB)")
# Also publish-ready copy for GitHub Pages (served from /docs on the main branch).
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(out)
open(os.path.join(ROOT, "docs", ".nojekyll"), "w").close()
print("wrote docs/index.html")
