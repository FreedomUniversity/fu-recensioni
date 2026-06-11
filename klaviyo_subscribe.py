#!/usr/bin/env python3
"""KLAVIYO SUBSCRIBE — sblocca le email recensione.
I contatti aggiunti alla lista TRUSTPILOT entrano SENZA consenso (never_subscribed):
Klaviyo, per legge anti-spam, non manda loro l'email del flow 'Automazione Trustpilot'.
Questo script (ogni tick) li iscrive con consenso single opt-in e li ri-innesca nel flow
(Added to List), così ricevono il link recensione. Idempotente via 'seen': ogni profilo
viene processato UNA sola volta → niente doppio invio anche se restasse non iscritto."""
import os, sys, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

KL   = rcfg.secret("KLAVIYO_TOKEN", "~/.config/klaviyo-token")
LIST = "TnYVNH"                       # lista TRUSTPILOT
BASE = "https://a.klaviyo.com"
HEAD = {"Authorization": f"Klaviyo-API-Key {KL}", "revision": "2024-10-15", "Content-Type": "application/json"}
SEEN = os.path.join(rcfg.STATE, "klaviyo_subscribed_seen.json")

def _req(path, body=None, method="GET"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=HEAD)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.getcode(), json.loads(r.read() or b"{}")

def _load_seen():
    try: return set(json.load(open(SEEN)))
    except Exception: return set()

def _save_seen(s): json.dump(sorted(s), open(SEEN, "w"))

def _not_subscribed(seen):
    out, url = [], f"/api/lists/{LIST}/profiles/?additional-fields%5Bprofile%5D=subscriptions&page%5Bsize%5D=100"
    while url:
        _, d = _req(url)
        for p in d.get("data", []):
            c = p.get("attributes", {}).get("subscriptions", {}).get("email", {}).get("marketing", {}).get("consent")
            if c != "SUBSCRIBED" and p["id"] not in seen and p["attributes"].get("email"):
                out.append((p["id"], p["attributes"]["email"]))
        nxt = d.get("links", {}).get("next")
        url = nxt.replace(BASE, "") if nxt else None
    return out

def main():
    if not KL:
        print("klaviyo_subscribe: manca KLAVIYO_TOKEN"); return
    seen = _load_seen()
    targets = _not_subscribed(seen)
    if not targets:
        print("klaviyo_subscribe: nessun nuovo contatto da iscrivere"); return
    emails = [e for _, e in targets]; ids = [i for i, _ in targets]
    print(f"klaviyo_subscribe: {len(ids)} nuovo/i contatto/i → iscrivo + innesco")
    # 1) subscribe (consenso single opt-in)
    for i in range(0, len(emails), 90):
        b = emails[i:i+90]
        body = {"data": {"type": "profile-subscription-bulk-create-job", "attributes": {
            "custom_source": "Richiesta recensione FU",
            "profiles": {"data": [{"type": "profile", "attributes": {"email": em,
                "subscriptions": {"email": {"marketing": {"consent": "SUBSCRIBED"}}}}} for em in b]}},
            "relationships": {"list": {"data": {"type": "list", "id": LIST}}}}}
        try: _req("/api/profile-subscription-bulk-create-jobs/", body, "POST")
        except Exception as e: print("  subscribe err:", e)
        time.sleep(2)
    time.sleep(45)  # lascia applicare il consenso
    # 2) ri-innesca il flow (Added to List con consenso valido)
    for i in range(0, len(ids), 90):
        chunk = [{"type": "profile", "id": x} for x in ids[i:i+90]]
        try:
            _req(f"/api/lists/{LIST}/relationships/profiles/", {"data": chunk}, "DELETE"); time.sleep(2)
            _req(f"/api/lists/{LIST}/relationships/profiles/", {"data": chunk}, "POST"); time.sleep(2)
        except Exception as e: print("  retrigger err:", e)
    seen.update(ids); _save_seen(seen)
    print(f"klaviyo_subscribe: completati {len(ids)} (seen totale {len(seen)})")

if __name__ == "__main__":
    main()
