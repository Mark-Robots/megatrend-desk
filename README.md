# Megatrend Desk

Sistema di **sector rotation** integrato: dashboard Azioni + ETF in un'unica app.

🔗 **Live**: https://mark-robots.github.io/megatrend-desk/  
📱 **APK Android**: tramite PWABuilder

## Dashboard incluse

| Dashboard | URL | Descrizione |
|---|---|---|
| **Azioni** (home, PWA) | [`/`](./) | Sistema azioni con backtest dal 2018 — Balanced e Aggressive |
| **ETF** | [`/cliente.html`](./cliente.html) | Sistema ETF settoriale con segnali RRG |

Navigazione interna via i pulsanti **"↻ Passa a..."** in alto.

## Aggiornamento automatico

GitHub Actions ogni **venerdì 16:00 ITA**:
1. Scarica dati Yahoo Finance
2. Genera `data/sector_data.json` (ETF) + `data/stocks_data.json` (Azioni)
3. Commit + push

## Disclaimer

Sistema personale di supporto operativo. Non costituisce consulenza finanziaria personalizzata.

---

© MarkRobots · Dati Yahoo Finance
