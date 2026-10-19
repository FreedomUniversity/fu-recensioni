#!/usr/bin/env python3
"""
PROVE su invio.py — senza rete, senza mandare niente a nessuno.
================================================================
Provano le decisioni che costano care, non il codice facile:

  1. Un invito NON consegnato non deve MAI risultare "inviato". Il registro dedup
     vale a vita: un falso "inviato" cancella la richiesta per sempre e nessuno se
     ne accorge. E' il difetto che aveva Klaviyo, ed e' il motivo di questo file.
  2. Senza l'indirizzo AFS non si manda: partirebbe una mail che genera una
     recensione "spontanea", bruciando la richiesta per una recensione che vale meno.
  3. Un indirizzo non valido e' "soppresso" (non riprovare), non "in coda"
     (riprova all'infinito ogni 10 minuti, per sempre).

  python3 test_invio.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("RECENSIONI_TEST", "1")
os.environ["TRUSTPILOT_AFS_BCC"] = "prova+test@invite.trustpilot.com"
os.environ["GHL_TOKEN_FU"] = "finto"
os.environ["GHL_LOCATION_FU"] = "finta"

import invio

ok_tot = 0
ko = []


def prova(nome, atteso, ottenuto):
    global ok_tot
    if atteso == ottenuto:
        ok_tot += 1
        print(f"  ✅ {nome}")
    else:
        ko.append(nome)
        print(f"  ❌ {nome}\n       atteso {atteso} · ottenuto {ottenuto}")


print("\nPROVE invio.py — nessuna mail parte davvero\n" + "-" * 48)

# 1. email non valide → soppresso (non si ritenta all'infinito)
for cattiva in ("", "   ", "pippo", "pippo@", "@dominio.it", "pippo@dominio"):
    prova(f"email non valida {cattiva!r} → soppresso",
          (False, "soppresso"), invio.manda_invito(cattiva, "Tizio"))

# 2. GHL irraggiungibile → IN CODA (None), mai un falso "inviato"
os.environ["GHL_FORCE_FAIL"] = "1"
import importlib
importlib.reload(invio)
prova("GHL giù → in coda, MAI 'inviato'",
      (False, None), invio.manda_invito("vero@esempio.it", "Tizio"))
del os.environ["GHL_FORCE_FAIL"]

# 3. senza indirizzo AFS → non si manda (la recensione sarebbe spontanea)
os.environ["TRUSTPILOT_AFS_BCC"] = ""
importlib.reload(invio)
prova("senza BCC AFS → non manda",
      (False, None), invio.manda_invito("vero@esempio.it", "Tizio"))
os.environ["TRUSTPILOT_AFS_BCC"] = "prova+test@invite.trustpilot.com"
importlib.reload(invio)

# 4. il corpo saluta per nome, e regge un nome vuoto senza esplodere
prova("saluto col nome", True, "Ciao Mario," in invio._corpo("Mario Rossi"))
prova("nome vuoto → saluto generico", True, "Ciao," in invio._corpo(""))
prova("nome None → non esplode", True, "Ciao," in invio._corpo(None))

print("-" * 48)
print(f"  {ok_tot} passate" + (f" · {len(ko)} FALLITE: {ko}" if ko else " · 0 fallite"))
raise SystemExit(1 if ko else 0)
