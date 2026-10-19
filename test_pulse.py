#!/usr/bin/env python3
"""Mette alla prova le due guardie del pulse SENZA rete e SENZA aspettare lunedì:
  1. la finestra oraria (lunedì 09:00–10:59, ora di Roma vera)
  2. l'anti-doppione a due marker, col reset dello stato simulato — cioè il difetto
     esatto che il 19/10 ha prodotto 24 classifiche in un giorno.
Usa un rcfg finto: nessun token, nessuna chiamata a Slack."""
import sys, os, types, datetime, tempfile, shutil

REPO = os.path.dirname(os.path.abspath(__file__))
TMP  = tempfile.mkdtemp(prefix="prova_pulse_")
STATE = os.path.join(TMP, "state"); os.makedirs(STATE)
HOME_FINTA = os.path.join(TMP, "home"); os.makedirs(os.path.join(HOME_FINTA, ".config"))
os.environ["HOME"] = HOME_FINTA                      # il 2° marker finisce qui

# rcfg finto: niente freno, niente segreti veri
rcfg = types.ModuleType("rcfg"); rcfg.STATE = STATE
rcfg.secret = lambda *a, **k: "xoxb-FINTO-NON-USATO"
sys.modules["rcfg"] = rcfg
sys.path.insert(0, REPO)
import recensioni_pulse as P

esiti = []
def check(nome, atteso, ottenuto):
    ok = atteso == ottenuto
    esiti.append(ok)
    print(f"{'✅' if ok else '❌'} {nome}: atteso={atteso} ottenuto={ottenuto}")

print("── 1. FINESTRA ORARIA ──")
casi = [
    ("lunedì 09:02 (il caso buono)",            datetime.datetime(2026, 10, 19,  9,  2), True),
    ("lunedì 10:59 (ultimo minuto utile)",      datetime.datetime(2026, 10, 19, 10, 59), True),
    ("lunedì 11:00 (un minuto dopo)",           datetime.datetime(2026, 10, 19, 11,  0), False),
    ("lunedì 15:06 (lo spam di oggi)",          datetime.datetime(2026, 10, 19, 15,  6), False),
    ("lunedì 08:59 (troppo presto)",            datetime.datetime(2026, 10, 19,  8, 59), False),
    ("martedì 09:30 (giorno sbagliato)",        datetime.datetime(2026, 10, 20,  9, 30), False),
    ("domenica 10:00",                          datetime.datetime(2026, 10, 18, 10,  0), False),
]
for nome, quando, atteso in casi:
    check(nome, atteso, P.finestra_ok(quando))

print("\n── 2. ANTI-DOPPIONE, col reset dello stato ──")
check("all'inizio: mai uscita questa settimana", False, P._gia_uscita())
P._segna()
check("dopo _segna(): risulta già uscita", True, P._gia_uscita())

m_stato, m_locale = P.WEEK_MARKS
check("marker nello stato scritto",   True, os.path.exists(m_stato))
check("marker fuori dal clone scritto", True, os.path.exists(m_locale))

# IL CASO CHE CI HA FREGATO: `git reset --hard` spazza via lo stato clonato
shutil.rmtree(STATE); os.makedirs(STATE)
check("reset dello stato: il marker git è sparito", False, os.path.exists(m_stato))
check("MA il pulse sa ancora di essere uscito", True, P._gia_uscita())

# e la settimana dopo deve tornare a parlare
open(m_locale, "w").write("2026-W01")
check("settimana nuova: può uscire di nuovo", False, P._gia_uscita())

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'TUTTO VERDE' if all(esiti) else 'CI SONO ROSSI'} — {sum(esiti)}/{len(esiti)}")
sys.exit(0 if all(esiti) else 1)
