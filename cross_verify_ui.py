"""A small web page for trying cross_verify: paste the JSON, press Verify, read the result.

HOW TO RUN (from this folder)
    python cross_verify_ui.py                 then open  http://127.0.0.1:8000  in a browser
    python cross_verify_ui.py --port 9000     to use another port
Stop it with Ctrl+C. Only the standard library is used (plus what cross_verify needs).
The page is served to this computer only (127.0.0.1). The settings file is read again on every
request, so an edit to cross_verify_config.json shows up at once. Changes to the .py files need a restart.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cross_verify as cv

MAX_BODY = 1_000_000  # bytes accepted in one request

EXAMPLE = [
    {
        "field": "applicant_name",
        "type": "name",
        "base": "Nishanth Kumar",
        "candidates": [
            {"source": "aadhaar", "value": "NISHANTH KUMAR"},
            {"source": "pan", "value": "Kumar Nishanth"},
            {"source": "passport", "value": "Nishant Kumar"},
        ],
    },
    {
        "field": "date_of_birth",
        "type": "dob",
        "base": "12-03-1998",
        "candidates": {"aadhaar": "12/03/1998", "pan": "13-03-1998"},
    },
    {
        "field": "address",
        "type": "address",
        "base": "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore - 560034",
        "candidates": {"aadhaar": "402 Sai Residence 2nd Cross Koramangala Bengaluru 560034"},
    },
]

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>cross_verify</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{box-sizing:border-box} body{margin:0;font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;color:#1f2933;background:#f4f6f8}
header{background:#1f2933;color:#fff;padding:10px 20px;font-size:16px} header span{opacity:.7;font-size:13px;margin-left:10px}
main{display:grid;grid-template-columns:minmax(380px,1fr) minmax(420px,1.3fr);gap:16px;padding:16px;align-items:start}
@media(max-width:900px){main{grid-template-columns:1fr}}
section{background:#fff;border:1px solid #d9e0e6;border-radius:8px;padding:14px}
h2{margin:0 0 10px;font-size:15px} h3{margin:12px 0 6px;font-size:13px}
textarea{width:100%;height:340px;font:13px/1.4 Consolas,monospace;border:1px solid #b8c2cc;border-radius:6px;padding:8px;resize:vertical}
button{font:inherit;padding:7px 16px;border:1px solid #b8c2cc;border-radius:6px;background:#fff;cursor:pointer}
button.go{background:#2563eb;border-color:#2563eb;color:#fff;font-weight:600} button:disabled{opacity:.6}
.bar{display:flex;gap:8px;align-items:center;margin:8px 0} .muted{color:#6b7782}
details{border:1px solid #d9e0e6;border-radius:6px;padding:6px 10px;margin-top:10px} summary{cursor:pointer;font-weight:600}
pre{margin:8px 0 2px;font:12px/1.45 Consolas,monospace;white-space:pre;overflow-x:auto}
pre.out{background:#f4f6f8;border-radius:6px;padding:10px;max-height:640px;overflow:auto;white-space:pre-wrap}
.tabs{display:flex;gap:6px;margin-bottom:10px} .tabs button.on{background:#e8eefc;border-color:#2563eb}
.chip{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12px;font-weight:700;color:#fff}
.chip.green{background:#1a9b4b} .chip.yellow{background:#d99a00} .chip.red{background:#d33a3a}
.overall{border-radius:8px;padding:10px 12px;margin-bottom:12px;border:1px solid} .overall.green{background:#e8f6ed;border-color:#1a9b4b}
.overall.yellow{background:#fff7dd;border-color:#d99a00} .overall.red{background:#fdecec;border-color:#d33a3a}
.field{border:1px solid #d9e0e6;border-radius:8px;margin-bottom:12px;overflow:hidden}
.field>.head{background:#f4f6f8;padding:8px 12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.cmp{padding:10px 12px;border-top:1px solid #e5eaee;border-left:5px solid} .cmp.green{border-left-color:#1a9b4b}
.cmp.yellow{border-left-color:#d99a00} .cmp.red{border-left-color:#d33a3a}
.cmp .head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.line{display:flex;gap:8px;margin:3px 0} .line .label{width:70px;color:#6b7782;flex:none}
.line .text{white-space:pre-wrap;word-break:break-word}
.seg.match{background:#cdeed8} .seg.moved,.seg.spelling,.seg.initial{background:#ffe8a3}
.seg.conflict,.seg.missing,.seg.extra{background:#f8c7c7} .seg.ignored{color:#8a949e;text-decoration:line-through}
ul{margin:6px 0 0;padding-left:20px} li code{font-weight:700} li.fail{color:#b42323} li.warn{color:#8a6100}
table{border-collapse:collapse;margin-top:6px;font-size:13px} th,td{border:1px solid #d9e0e6;padding:3px 8px;text-align:left}
.err{background:#fdecec;border:1px solid #d33a3a;border-radius:8px;padding:10px 12px;color:#8f1d1d}
</style></head><body>
<header>cross_verify<span>compare a trusted value with the same value from other documents</span></header>
<main>
<section>
  <h2>1. Input JSON</h2>
  <textarea id="input" spellcheck="false"></textarea>
  <div class="bar">
    <button class="go" id="go">Verify</button><button id="load-all" style="background:#059669;color:#fff;border-color:#059669;font-weight:600">⚡ Load All 246 Benchmark Cases</button><button id="example">Load example</button><button id="format">Format JSON</button>
    <span class="muted">Ctrl+Enter also verifies</span>
  </div>
  <details open><summary>Input structure</summary>
<pre>[                                   a list of checks (or {"checks": [ ... ]})
  {
    "field": "applicant_name",        any label you like, shown in the result
    "type": "name",                   see the list of types below
    "kind": "pan",                    only for "id" and "text", and only when the type does not imply it
    "base": "Nishanth Kumar",         the trusted value. null = unknown (every candidate is red)
    "candidates": [                   the same value read from other documents
      {
        "source": "aadhaar",          required: the name of the document
        "value": "NISHANTH KUMAR"     the value read from it (text, or a date)
      }
    ]
  }
]

Shorthand for candidates:  "candidates": {"aadhaar": "NISHANTH KUMAR", "pan": "Kumar Nishanth"}

Types, and the names you may use instead:
  name      a person's name
  dob       day, month, year in that order, e.g. 12-03-1998, 12/03/1998, 12 March 1998
  address   an Indian address: pincode, city, house and street numbers, place words
  id        an identity number.  aadhaar | pan | passport | voter_id | driving_licence | id_number
  amount    money.  "Rs. 12,50,000/-", "1250000", "12.5 lakh", "USD 48000".  money | fee
  email     an email address.  email_id
  phone     a phone number, with or without +91.  mobile | mobile_number | phone_number
  text      short text or a body's name.  gender | relationship | nationality | university | employer | course</pre>
  </details>
  <details><summary>How the colours are decided</summary>
<pre>GREEN   the values are the same after clean-up (capitals, spaces, labels, titles)
YELLOW  a partial difference that needs a look:
          name     words in another order, an initial for a full word, a missing or extra word
          address  a missing part, a small spelling difference, a pincode in the same area
RED     anything else: a different spelling or word, a different date, a different number or city,
        a missing or unreadable value
Names are compared letter for letter: Vinay and Vijay are red.
A date of birth is green only when day, month and year are all equal, otherwise red.</pre>
  </details>
  <details><summary>Output structure</summary>
<pre>{
  "request_id": "...",              id of this run
  "mode": "fuzzy",
  "config_label": "...", "config_hash": "...",     which settings were used
  "overall": {                      the worst comparison speaks for the whole report
    "color": "red", "status": "mismatch",          green/match, yellow/warning, red/mismatch
    "needs_review": true,
    "counts": {"match": 2, "warning": 2, "mismatch": 2}
  },
  "fields": [
    {
      "field": "applicant_name", "type": "name",
      "base": {"raw": "...", "normalized": "..."},
      "color": "...", "status": "...", "needs_review": true,    worst of its comparisons
      "comparisons": [
        {
          "source": "pan", "id": "pan",
          "raw": "...", "normalized": "...",                  the value as given, and cleaned
          "color": "...", "status": "...",                  the colour is the worst severity of the reasons
          "needs_review": true,                             true unless the colour is green
          "reasons": [{"code": "TOKEN_CONFLICT", "severity": "info|warn|fail", "message": "..."}],
          "highlight": {                                      pieces of the text to colour
            "base": [{"text": "Nishanth", "start": 0, "end": 8, "kind": "conflict"}, ...],
            "candidate": [ ... ]                              kind: match, moved, spelling, initial,
          },                                                  conflict, missing, extra, ignored, ...
          "components": [ ... ]                               dob and address only: part by part
        }
      ]
    }
  ]
}</pre>
  </details>
</section>
<section>
  <h2>2. Output</h2>
  <div class="tabs"><button id="tab-result" class="on">Result</button><button id="tab-json">JSON</button></div>
  <div id="result" class="muted">Press Verify to see the result here.</div>
  <pre id="json" class="out" hidden></pre>
</section>
</main>
<script>
const EXAMPLE = __EXAMPLE__;
const $ = id => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
const chip = color => el("span", "chip " + color, color.toUpperCase());
const meta = r => (r.needs_review ? "needs review" : "");

function line(label, segs) {
  const row = el("div", "line"), box = el("span", "text");
  row.append(el("span", "label", label), box);
  if (!segs.length) box.append(el("span", "muted", "(empty)"));
  for (const s of segs) box.append(el("span", "seg " + s.kind, s.text));
  return row;
}
function show(v) { return Array.isArray(v) ? v.join(", ") : v === null ? "" : String(v); }

function comparison(c) {
  const card = el("div", "cmp " + c.color), head = el("div", "head");
  head.append(chip(c.color), el("strong", "", c.id), el("span", "muted", meta(c)));
  card.append(head, line("Base", c.highlight.base), line("Document", c.highlight.candidate));
  if (c.reasons.length) {
    const list = el("ul");
    for (const r of c.reasons) {
      const li = el("li", r.severity);
      li.append(el("code", "", r.code), " " + r.message);
      list.append(li);
    }
    card.append(list);
  }
  if (c.components) {
    const table = el("table"), header = el("tr");
    for (const h of ["part", "base", "document", "result"]) header.append(el("th", "", h));
    table.append(header);
    for (const p of c.components) {
      const row = el("tr");
      for (const v of [p.component, show(p.base), show(p.candidate), p.relation || p.status]) row.append(el("td", "", v));
      table.append(row);
    }
    card.append(table);
  }
  return card;
}

function render(report) {
  const out = $("result");
  out.replaceChildren();
  out.className = "";
  if (report.error) { out.append(el("div", "err", report.error)); return; }
  const o = report.overall, banner = el("div", "overall " + o.color);
  banner.append(chip(o.color), ` Overall: ${meta(o)} · ${o.counts.match} match, ${o.counts.warning} warning, ${o.counts.mismatch} mismatch`);
  banner.append(el("div", "muted", `request ${report.request_id} · mode ${report.mode} · settings ${report.config_label}`));
  out.append(banner);
  for (const f of report.fields) {
    const box = el("div", "field"), head = el("div", "head");
    head.append(chip(f.color), el("strong", "", f.field), el("span", "muted", `${f.type} · base: ${f.base.raw} → ${f.base.normalized}`));
    box.append(head);
    for (const c of f.comparisons) box.append(comparison(c));
    out.append(box);
  }
}

async function run() {
  $("go").disabled = true;
  let report;
  try {
    const res = await fetch("/verify", {method: "POST", headers: {"Content-Type": "application/json"}, body: $("input").value});
    report = await res.json();
  } catch (e) {
    report = {error: "Could not reach the server: " + e.message};
  }
  $("json").textContent = JSON.stringify(report, null, 2);
  render(report);
  $("go").disabled = false;
}
function tab(name) {
  $("result").hidden = name !== "result";
  $("json").hidden = name !== "json";
  $("tab-result").className = name === "result" ? "on" : "";
  $("tab-json").className = name === "json" ? "on" : "";
}
$("input").value = JSON.stringify(EXAMPLE, null, 2);
$("go").onclick = run;
$("example").onclick = () => { $("input").value = JSON.stringify(EXAMPLE, null, 2); };
$("load-all").onclick = async () => {
  $("go").disabled = true;
  $("load-all").disabled = true;
  $("result").textContent = "Loading and running all 246 cases...";
  try {
    const res = await fetch("/benchmark_dataset.json");
    const data = await res.json();
    $("input").value = JSON.stringify(data, null, 2);
    await run();
  } catch (e) {
    render({error: "Failed to load benchmark dataset: " + e.message});
  } finally {
    $("go").disabled = false;
    $("load-all").disabled = false;
  }
};
$("format").onclick = () => {
  try { $("input").value = JSON.stringify(JSON.parse($("input").value), null, 2); }
  catch (e) { render({error: "Not valid JSON: " + e.message}); tab("result"); }
};
$("input").addEventListener("keydown", e => { if (e.ctrlKey && e.key === "Enter") run(); });
$("tab-result").onclick = () => tab("result");
$("tab-json").onclick = () => tab("json");
</script></body></html>
"""  # noqa: E501  (long lines are fine inside the page)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: object) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            page = PAGE.replace("__EXAMPLE__", json.dumps(EXAMPLE).replace("</", "<\\/"))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/benchmark_dataset.json":
            ds_path = Path(__file__).resolve().parent / "benchmark_dataset.json"
            if ds_path.is_file():
                self._send(200, ds_path.read_bytes(), "application/json; charset=utf-8")
            else:
                self._json(404, {"error": "benchmark_dataset.json not found"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/verify":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.rfile.read(min(length, 20 * MAX_BODY))  # read and drop it, so the browser can read the reply
            return self._json(413, {"error": f"the input is larger than {MAX_BODY} bytes"})
        try:
            verify = cv.create_verifier()  # reads the settings file again, so edits apply at once
            report = verify(json.loads(self.rfile.read(length)))
        except ValueError as exc:  # not valid JSON, or a request the verifier refuses (InputError)
            return self._json(400, {"error": str(exc)})
        except cv.CrossVerifyError as exc:  # the settings file is broken, or the mode is not developed yet
            return self._json(500, {"error": str(exc)})
        self._json(200, report)


def main() -> None:
    parser = argparse.ArgumentParser(description="A small web page for trying cross_verify.")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default 8000)")
    port = parser.parse_args().port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"cross_verify UI: open http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
