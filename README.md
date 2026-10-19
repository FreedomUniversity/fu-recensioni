# fu-recensioni — Sistema Recensioni Trustpilot (Freedom University)

> ⚠️ **Repo PUBBLICO.** Nessun dato cliente, nessun indirizzo, nessun token qui dentro.
> Lo stato e i PII vivono nel repo privato `fu-recensioni-state`.

**Ultimo aggiornamento: 19/10/2026.** Fino a oggi questo file descriveva una catena che
nel codice non esisteva più da luglio (Pipedrive, Klaviyo): ha mandato fuori strada per
ore chi cercava l'interruttore giusto. **Se tocchi qualcosa, aggiorna questo file nello
stesso commit.**

---

## La regola che spiega tutto

> **Una recensione è VERIFICATA solo se il cliente ci arriva dalla mail ufficiale di
> Trustpilot.**

E Trustpilot quella mail la manda solo se riceve copia della nostra. Quindi: mandiamo al
cliente una mail normale mettendo in **BCC l'indirizzo AFS**. Trustpilot legge la copia,
spedisce **lui** l'invito ufficiale, il cliente recensisce da li → ✅ **verificata**.

Se gli mandi il link su WhatsApp o in una mail qualsiasi, la recensione esce
**"spontanea"**: vale molto meno e non ha la spunta.

🔑 L'indirizzo AFS **non sta nel codice** (questo repo è pubblico e chi lo conosce può far
spedire inviti a nome di Freedom University a chiunque). Vive in un segreto:
`TRUSTPILOT_AFS_BCC` nelle Actions, `~/.config/trustpilot-afs-bcc` in locale.

---

## La catena, oggi

```
una PERSONA compila il modulo Tally       ← qui si decide chi merita l'invito
      form.freedomuniversity.it/recensione
              ↓
recensioni_trustpilot.py     (nel tick su GitHub Actions, ogni 10 min)
              ↓
invio.manda_invito(email, nome)
              ↓
GHL: upsert contatto + POST /conversations/messages   (emailBcc = AFS)
              ↓
Trustpilot riceve la copia e manda il SUO invito ufficiale
              ↓
        ✅ recensione VERIFICATA
```

**Non esiste nessun canale automatico.** L'invito parte perché una persona ha scritto nome
e mail di un cliente in un modulo, e ci ha messo la firma: il campo *«chi ha procurato
questa recensione»* alimenta la classifica del contest.

---

## Cosa NON c'è più, e perché

| Pezzo | Fine | Perché |
|---|---|---|
| **Pipedrive** | 24/7/2026 | Non è più il CRM. Il poller è stato rifondato CRM-indipendente. |
| **Klaviyo** | 19/10/2026 | Non lo usiamo più. E il suo `add to list` tornava **«riuscito» anche a flow spento**: l'invito risultava mandato, il registro lo marcava per sempre (il dedup vale a vita) e la mail non partiva. Un «200 che mente» che bruciava la richiesta in silenzio. In più l'API Klaviyo **non ha un metodo** per rimettere «live» il messaggio dentro un flow: la catena restava in ostaggio di un clic nell'interfaccia che nessuno sapeva di dover fare. |
| **Canale GHL «Vinto»** (`ghl_won_source.py`) | 19/10/2026 | Pescava da solo le opportunità vinte e mandava **8 inviti al giorno non richiesti**: 86 dal 24/9 al 15/10, recessi e insoddisfatti compresi. Da li arrivavano le recensioni negative. **Chiuso nel codice**, non spento da una variabile — una variabile la rimette su `SI` chiunque, anche un redeploy. |

---

## I freni (nati tutti da un danno vero, non da teoria)

- **Dedup a vita** — registro unico `invites_ledger.json`: una persona riceve l'invito
  **una volta sola**, da qualsiasi canale.
- **Anti-bulk** — più di `MAX_BATCH` richieste in un giro: non manda, allerta. Salvavita
  contro un import massivo.
- **Budget 50/mese** — tetto del piano free; `recensioni_inviti.py` avvisa a 45.
- **Mai un falso «inviato»** — se GHL non risponde, l'invito resta **in coda** e si
  ritenta. Un invito segnato come mandato ma mai partito è peggio di un errore.
- **Niente BCC → niente invio** — meglio non mandare che bruciare la richiesta per una
  recensione che uscirebbe spontanea.
- **Freno a mano universale** — in `rcfg.py`, che tutti gli script importano: se esiste
  `SPENTO` nel repo, o `~/.config/recensioni-SPENTO`, o `RECENSIONI_SPENTO=1`, **non
  esegue nessuno**. Viaggia col codice: arriva a ogni clone e sopravvive a un redeploy.

---

## Come si verifica che una mail sia DAVVERO uscita

Un `201 «Email queued successfully»` **non è una consegna**.

```bash
python3 stato_invito.py cliente@esempio.it
#   stato consegna : delivered       ← delivered / opened / bounced / failed
#   BCC Trustpilot : SI ✅           ← senza questo la recensione sarebbe spontanea
```

⚠️ Due trappole dell'API GHL, scritte qui per non farci sbattere il prossimo:
l'`emailMessageId` **non** è l'id del messaggio di conversazione (sta in
`meta.email.messageIds[0]`, l'altro dà `HTTP 400`); e
`conversations/search?contactId=` **non risponde** — resta appeso fino al timeout. Si
cerca per `query=<email>` e si filtra sul contatto.

---

## Prove

```bash
python3 test_invio.py    # 11 prove, senza rete: nessuna mail parte
python3 test_pulse.py    # finestra e anti-doppione della classifica
```

---

## Dove gira

| Cosa | Dove | Quando |
|---|---|---|
| tick (detector · drip · poller Tally · guardia budget · pulse · health) | GitHub Actions `tick.yml` | ogni 10 min |
| guardiani 1 e 2 | GitHub Actions | sorvegliano il tick e si sorvegliano a vicenda |
| scorta cross-piattaforma | Mac `recensioni_fallback.py` · gemello sul VPS | solo se il cloud tace > 30 min |

⚠️ **Le scorte sono il punto che sfugge.** Nascono per coprire GitHub quando è giù, e
**«spento di proposito» e «giù» sono indistinguibili dall'esterno**. Il 19/10 il gemello
sul VPS ha ripreso il testimone 20 minuti dopo uno spegnimento volontario e ha rieseguito
tutto per sei ore e mezza. Se fermi il sistema, **conta prima i gemelli** — o meglio,
metti il freno nel codice che tutti importano, non su ogni lanciatore: i lanciatori si
scoprono uno alla volta, il codice è uno solo.

---

## File, uno per riga

| File | Cosa fa |
|---|---|
| `recensioni_trustpilot.py` | legge il modulo Tally e consegna le richieste |
| `invio.py` | **manda la mail via GHL col BCC AFS** — è qui che nasce la verifica |
| `stato_invito.py` | dice se una mail è davvero uscita (delivered/opened/bounced) |
| `recensioni_detector.py` | legge via IMAP le notifiche Trustpilot → recensioni arrivate |
| `recensioni_drip.py` | pubblica le recensioni nuove |
| `recensioni_inviti.py` | conta gli inviti del mese, avvisa prima del tetto di 50 |
| `recensioni_pulse.py` | classifica settimanale su Slack (lunedì mattina) |
| `recensioni_health.py` | digest giornaliero di salute |
| `recensioni_guardiano.py` | sorveglia tick e gemello, auto-ripara |
| `recensioni_classifica.py` · `recensioni_festa.py` · `recensioni_milestone.py` | contest e annunci |
| `ghl_won_source.py` | ⛔ **chiuso il 19/10** — esce subito, non manda nulla |
| `klaviyo_subscribe.py` | ⛔ **fuori dal giro il 19/10** — esce subito |
| `test_invio.py` · `test_pulse.py` | prove senza rete |
