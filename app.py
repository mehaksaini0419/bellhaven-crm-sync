"""Local review app.

Shows every open proposal with its evidence. Nothing reaches the CRM until
a human clicks Approve. Rejections are remembered too, so the pipeline
does not nag about them on the next run.

    python app.py     ->  http://127.0.0.1:5000
"""
import json
import os
from flask import Flask, render_template_string, request, redirect, url_for
import config
import store
from crm_client import CRMClient

app = Flask(__name__)
crm = CRMClient()

TPL = """
<!doctype html><meta charset=utf-8>
<title>Bellhaven CRM Review</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#faf7f2;color:#222}
 header{background:#fff;border-bottom:1px solid #e5ded3;padding:16px 28px}
 h1{margin:0;font-size:19px}
 .sub{color:#777;font-size:13px;margin-top:4px}
 .wrap{padding:24px 28px;max-width:1000px}
 .card{background:#fff;border:1px solid #e5ded3;border-radius:8px;padding:16px 18px;margin-bottom:14px}
 .type{display:inline-block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
       padding:3px 9px;border-radius:99px;background:#eef2ff;color:#3730a3;font-weight:600}
 .type.chow_reparent{background:#fef3c7;color:#92400e}
 .type.mark_duplicate{background:#fee2e2;color:#991b1b}
 .type.not_on_website{background:#f3f4f6;color:#374151}
 .type.create_missing_account{background:#dcfce7;color:#166534}
 .type.review_low_confidence{background:#fae8ff;color:#86198f}
 .name{font-weight:650;font-size:15px;margin:9px 0 2px}
 .conf{float:right;font-size:12px;color:#666}
 ul{margin:8px 0 10px 18px;padding:0;font-size:13.5px;color:#444}
 li{margin:3px 0}
 pre{background:#f7f5f1;border:1px solid #ece7de;border-radius:6px;padding:9px 11px;
     font-size:12.5px;overflow-x:auto;margin:6px 0 12px}
 button{border:0;border-radius:6px;padding:8px 16px;font-size:13.5px;cursor:pointer;font-weight:600}
 .ok{background:#166534;color:#fff}
 .no{background:#fff;color:#666;border:1px solid #d6cec2}
 form{display:inline}
 .empty{background:#fff;border:1px dashed #d6cec2;border-radius:8px;padding:40px;text-align:center;color:#777}
 .bar{margin-bottom:18px;font-size:13px;color:#555}
 .bar b{color:#222}
</style>
<header>
  <h1>Bellhaven CRM Review Queue</h1>
  <div class=sub>Nothing is written to the CRM until you approve it.
    &nbsp;·&nbsp; <a href="/history">view decision history</a></div>
</header>
<div class=wrap>
  <div class=bar><b>{{proposals|length}}</b> open &middot; <b>{{decided}}</b> already decided</div>
  {% if not proposals %}
    <div class=empty>Queue is empty. Run <code>python pipeline.py</code> to refresh.</div>
  {% endif %}
  {% for p in proposals %}
  <div class=card>
    <span class="type {{p.type}}">{{p.type.replace('_',' ')}}</span>
    <span class=conf>confidence {{'%.2f'|format(p.confidence)}}</span>
    <div class=name>{{p.account_name or p.website_name}}</div>
    <ul>{% for e in p.evidence %}<li>{{e}}</li>{% endfor %}</ul>
    <pre>{{p.action | tojson(indent=2)}}</pre>
    <form method=post action="{{url_for('decide')}}">
      <input type=hidden name=fp value="{{p.fingerprint}}">
      <input type=hidden name=decision value=approve>
      <button class=ok>Approve</button>
    </form>
    <form method=post action="{{url_for('decide')}}">
      <input type=hidden name=fp value="{{p.fingerprint}}">
      <input type=hidden name=decision value=reject>
      <button class=no>Reject</button>
    </form>
  </div>
  {% endfor %}
</div>
"""


def load():
    if not os.path.exists(config.PROPOSALS_FILE):
        return []
    return json.load(open(config.PROPOSALS_FILE))


def apply_action(p):
    """Execute an approved proposal. This is the only path that writes."""
    a = p["action"]
    op = a["op"]

    if op == "patch":
        return crm.patch_account(p["account_id"], a["fields"])

    if op == "create":
        return crm.create_account(a["fields"])

    if op == "chow":
        # 1. create the successor account under the correct parent
        new = crm.create_account(a["new_account_fields"])
        new_id = new.get("account_id") if isinstance(new, dict) else None
        # 2. point the old account at it, leaving parent_id untouched
        old = crm.patch_account(a["old_account_id"], {
            "chow_current_account": new_id,
            "note": a["old_account_note"],
        })
        return {"created": new, "old_updated": old}

    raise ValueError(f"unknown op {op}")


@app.route("/")
def index():
    props = [p for p in load() if p["fingerprint"] not in store.already_decided()]
    return render_template_string(TPL, proposals=props,
                                  decided=len(store.already_decided()))


HIST_TPL = """
<!doctype html><meta charset=utf-8>
<title>Decision History — Bellhaven CRM</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#faf7f2;color:#222}
 header{background:#fff;border-bottom:1px solid #e5ded3;padding:16px 28px}
 h1{margin:0;font-size:19px}
 .sub{color:#777;font-size:13px;margin-top:4px}
 .wrap{padding:24px 28px;max-width:1050px}
 table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5ded3;
       border-radius:8px;overflow:hidden;font-size:13.5px}
 th{background:#f7f5f1;text-align:left;padding:9px 12px;font-size:11.5px;
    text-transform:uppercase;letter-spacing:.05em;color:#666}
 td{padding:9px 12px;border-top:1px solid #f0ebe3;vertical-align:top}
 .approve{color:#166534;font-weight:650}
 .reject{color:#991b1b;font-weight:650}
 code{background:#f4f1ec;padding:1px 5px;border-radius:4px;font-size:12px}
 .bar{margin-bottom:16px;font-size:13px;color:#555}
</style>
<header>
  <h1>Decision History</h1>
  <div class=sub>Every proposal a human ruled on, newest first.
    &nbsp;·&nbsp; <a href="/">back to queue</a></div>
</header>
<div class=wrap>
  <div class=bar><b>{{rows|length}}</b> decisions
    &middot; {{approved}} approved &middot; {{rejected}} rejected</div>
  <table>
    <tr><th>When</th><th>Decision</th><th>Type</th><th>Account</th><th>Change</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{r.decided_at.replace('T',' ').replace('Z','')}}</td>
      <td class="{{r.decision}}">{{r.decision}}</td>
      <td>{{r.proposal.type.replace('_',' ')}}</td>
      <td>{{r.proposal.account_name or r.proposal.website_name }}<br>
          <code>{{r.proposal.account_id or 'new'}}</code></td>
      <td>{% set a = r.proposal.action %}
        {% if a.op == 'patch' %}
          {% for k,v in a.fields.items() %}{% if k != 'note' %}
            <code>{{k}}</code> = {{v}}<br>
          {% endif %}{% endfor %}
        {% elif a.op == 'create' %}
          created <code>{{a.fields.name}}</code>
        {% elif a.op == 'chow' %}
          CHOW: new account under Bellhaven, old record linked
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
"""


@app.route("/history")
def history():
    rows = store.history()
    return render_template_string(
        HIST_TPL, rows=rows,
        approved=sum(1 for r in rows if r["decision"] == "approve"),
        rejected=sum(1 for r in rows if r["decision"] == "reject"))


@app.route("/decide", methods=["POST"])
def decide():
    fp = request.form["fp"]
    decision = request.form["decision"]
    p = next((x for x in load() if x["fingerprint"] == fp), None)
    if not p:
        return redirect(url_for("index"))
    result = None
    if decision == "approve":
        try:
            result = apply_action(p)
        except Exception as e:
            result = {"error": str(e)}
    store.record(p, decision, result)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
