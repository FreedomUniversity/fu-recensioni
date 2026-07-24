# fu-recensioni — Sistema Recensioni Trustpilot (Freedom University)

Motore cloud che invita i clienti a lasciare una recensione **verificata** su Trustpilot,
festeggia le recensioni che arrivano e tiene vivo il contest interno. Gira su GitHub
Actions (repo **pubblico** → Actions gratis ∞). Lo stato/PII vive nel repo privato
`fu-recensioni-state` (nessun dato cliente in questo repo pubblico).

---

## Come funziona in 30 secondi

```
                       ┌─────────────────────────────────────────────┐
  CLIENTE COMPRA       │  invito ufficiale (POST → Klaviyo → BCC AFS  │
  (GHL stage "Vinto")──┤  Trustpilot) = recensione VERIFICATA         │
                       │                                             │
  TEAM porta cliente ──┤  ┌── REGISTRO UNICO invites_ledger.json ──┐  │
  (modulo Tally)       │  │  dedup cross-canale + budget 50/mese   │  │
                       │  └────────────────────────────────────────┘  │
                       └─────────────────────────────────────────────┘
  CLIENTE RECENSISCE ──► detector (IMAP) ──► festa su #general + contatore + classifica
```

Due porte d'ingresso, **un solo registro** che le governa. Il cliente è invitato **una
volta sola** da qualsiasi porta entri, e il tetto mensile del piano free (50 inviti
verificati) è contato in un posto solo → impossibile sforare.

---

## Componenti (workflow)

| Workflow | Quando | Cosa fa |
|---|---|---|
| **tick.yml** | ogni 10 min (cron + Make A/B ridondanti) | detector (festa) · drip · poller Tally · motore GHL · guardiano inviti · classifica lunedì · digest salute |
| pulse.yml | — (ora dentro il tick) | classifica settimanale on-demand |
| health.yml | on-demand | digest salute manuale (l'automatico è nel tick) |
| guardiano1/2.yml | cron sfasati | si sorvegliano a vicenda + risvegliano il tick se fermo |

I trigger del tick sono **ridondanti** (cron GitHub + Make `9346700` 10min + Make `9346829`
13min): se uno muore, gli altri coprono. È la lezione del buco 15–23/7 (dipendeva da un
trigger solo).

## Script

| Script | Ruolo |
|---|---|
| `ghl_won_source.py` | **canale acquisti**: legge i "Vinto" da GHL → invito. 5 freni (watermark, anti-bulk, qualità, dedup, budget). Parte in **DRY-RUN**. |
| `recensioni_trustpilot.py` | **canale team**: legge il modulo Tally → invito diretto (CRM-indipendente). |
| `recensioni_detector.py` | legge le email Trustpilot via IMAP → festa su #general + contatore. Se l'IMAP cade **allerta** (non più muto). |
| `recensioni_inviti.py` / `rcfg.py` | registro unico inviti + budget mensile. |
| `recensioni_pulse.py` | classifica settimanale (`--auto` nel tick). |
| `recensioni_health.py` | digest salute (`--auto` nel tick). Degrado ≠ crash. |
| `recensioni_drip.py` · `recensioni_milestone.py` · `recensioni_festa.py` | ripubblicazione graduale · traguardi · messaggio di festa. |

---

## ⚙️ Configurazione (repo → Settings → Secrets/Variables → Actions)

**Secrets** (già impostati): `GH_PAT`, `SLACK_FU_TOKEN`, `KLAVIYO_TOKEN`, `TALLY_TOKEN`,
`PIPEDRIVE_TOKEN`, `IMAP_HOST/USER/PASS`, `GHL_TOKEN_FU`, `GHL_LOCATION_FU`.

**Variables** (comportamento):
- `GHL_WON_LIVE` — vuoto = **dry-run** (default sicuro). `SI` = il motore GHL invia davvero.

---

## 🔴 Azioni aperte (richiedono Domenico)

1. **Password app Google per l'IMAP** — la casella `claudiocavalli@freedomuniversity.it`
   ha le credenziali scadute → il detector è cieco (nessuna festa, contatore fermo).
   Fix: myaccount.google.com → Sicurezza → Password per le app → aggiorna il secret `IMAP_PASS`.
2. **Accendere gli inviti automatici da vendita** — crea la variable `GHL_WON_LIVE = SI`
   quando vuoi che i "Vinto" ricevano l'invito in automatico. Finché è vuota, il motore
   mostra solo cosa farebbe (dry-run).
3. **Ruotare il webhook Klaviyo** — la URL è finita nella history di questo repo pubblico.
   Rigenerala in Make e aggiornala nel secret `KLAVIYO_WEBHOOK` (gli script la leggono da lì).

---

## Runbook rapido

- **Vedere lo stato ora** → Actions → *Recensioni health* → Run workflow → arriva nel DM.
- **Forzare un giro** → Actions → *Recensioni tick* → Run workflow.
- **Cambiare il tetto mensile** → variable/secret `TRUSTPILOT_BUDGET` (default 50).
- **Alzare le soglie anti-bulk** → `GHL_WON_MAX_BATCH` (default 15) / `TALLY_MAX_BATCH` (default 20).
- **Contest**: la classifica esce da sola il lunedì mattina su #general. L'attribuzione
  conta **solo** il modulo Tally (gli inviti automatici da vendita NON danno gettoni, per
  non gonfiare la gara).

Lo stato (registro inviti, watermark, seen, gettoni, contatore) è tutto in
`fu-recensioni-state/state/` e viene committato a ogni tick.
