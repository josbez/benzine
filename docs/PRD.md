# PRD — Benzineprijs Forecaster

*Opgesteld 7 augustus 2026, op basis van de codebase (`src/`, `web/`), de
README, `docs/verbeterplan.md` en de laatste backtest-cijfers
(`data/backtest_metrics.json`).*

## 1. Samenvatting

Een gratis, reclamevrije mobiele webapp die een 1–5 dagen vooruitblik geeft
op de landelijke gemiddelde pompprijs van Euro 95 in Nederland, met een
onzekerheidsband in plaats van één getal. Het product bestaat uit een
Python-pijplijn die dagelijks marktdata verwerkt tot een statisch
`forecast.json`-bestand, en een front end zonder dependencies die dat
bestand toont. Geen server, geen account, geen tracking — kosten €0.

De kernthese: de pompprijs volgt de groothandelsmarkt met een vertraging
van dagen. Een korte-termijnforecast is daarom grotendeels boekhouding op
al bekende informatie ("wanneer bereikt een reeds gebeurde
groothandelsbeweging de pomp"), niet een poging om de olieprijs te
voorspellen.

## 2. Probleem en doelgroep

**Probleem.** Consumenten en kleine wagenparkbeheerders zien de pompprijs
dagelijks fluctueren zonder enig zicht op de eerstvolgende dagen, en nemen
tank-timingbeslissingen op onderbuikgevoel of op nieuwskoppen over de
olieprijs — die met de pompprijs van morgen weinig te maken hebben.

**Doelgroep.**
- Automobilisten die willen weten "kan ik wachten met tanken, of moet het
  vandaag" — de primaire, nog niet volledig bediende use case (zie §6,
  E5-2).
- Nieuwsgierige/analytische gebruikers die de onderbouwing willen zien
  (groothandelsprijs, wisselkoers, accijns) in plaats van alleen een getal.

**Niet de doelgroep (nu).** Zakelijke wagenparkplanning op stationsniveau,
professionele trading, of iets dat meer dan de landelijke Euro 95-prijs
nodig heeft — expliciet uitgesteld naar latere epics (§8).

## 3. Productthese en afbakening

| Wat het is | Wat het niet is |
|---|---|
| Een lag-model: "welke al bekende groothandelsbeweging heeft de pomp nog niet bereikt" | Een olieprijsvoorspelling |
| 1–5 dagen vooruit, met bewust harde horizon-grens | Een lange-termijnprognose |
| Landelijk gemiddelde | Prijs per tankstation |
| Kwantielen (10/25/50/75/90) — een waaier | Eén puntvoorspelling |
| Verandering t.o.v. laatst bekende prijs, gebenchmarkt tegen "geen verandering" | Een absolute prijsclaim zonder ijkpunt |

Deze afbakening is fundamenteel, niet tijdelijk: voorbij ~5 dagen is de
"doorwerkings-pijplijn" leeggelopen en voorspel je feitelijk de olieprijs
zelf, wat het model expliciet niet claimt te kunnen.

## 4. Hoe het werkt (technisch, kort)

```
Brent + EUR/USD → EBOB/RBOB Rotterdam → adviesprijs → pompprijs
     (dag 0)            (dag 0)         (dag +1..+5)   (dag +2..+14)
```

- **Trainingslabel:** CBS 80416ned, de officiële landelijke pompprijs —
  gepubliceerd met tot 9 dagen vertraging (donderdags, t/m voorgaande
  maandag).
- **Live-anker:** UnitedConsumers "gemiddelde landelijke adviesprijs"
  (GLA), dagelijks gepubliceerd, geen publiek archief — de pijplijn bouwt
  dit archief zelf op (`data/raw/gla_history.csv`).
- **Leidende indicator:** groothandelsmarkt (RBOB/Brent-proxy, EUR/USD) via
  Yahoo Finance met Stooq als fallback.
- **Bekende toekomstige schok:** accijnswijzigingen worden als exacte,
  vooraf bekende stap meegegeven (`data/excise.yaml`), niet geschat.
- **Modellen:** `naive` (benchmark), `ecm` (foutcorrectie met asymmetrische
  doorwerking — stijgingen sneller dan dalingen, het "rockets and
  feathers"-effect), `gbm` (gradient boosting, levert de kwantielen).
- **Discipline tegen datalekken:** elke rij in het panel is gestempeld met
  wat op die datum daadwerkelijk kenbaar was; de backtest traint alleen op
  labels die op het refit-moment al gepubliceerd waren. Dit wordt door
  specifieke tests afgedwongen, niet alleen door documentatie.
- **Publicatie:** GitHub Actions bouwt 3×/dag (03:00, 12:00, 17:00 NL-tijd)
  en publiceert `web/` naar een `gh-pages`-branch; een aparte wekelijkse
  workflow ververst de backtest-score.

## 5. Huidige productstatus (7 augustus 2026)

De modelkern is bewezen; de operationele keten rond het model is dat nog
niet volledig. Dit is een essentieel onderscheid voor prioritering:

| Onderdeel | Status |
|---|---|
| Model (ECM/GBM), leak-vrije backtest | ✅ Werkt, cijfers hieronder |
| Timing-invarianten (features/backtest) | ✅ Getest en afgedwongen |
| CI-robuustheid (retries, gepinde deps, push-race, tests-in-CI) | ✅ Sprint 2 afgerond |
| Adviesprijs-historie opbouwen zonder dataverlies | ✅ Stapvolgorde gefixed |
| **Live GLA-anker (scraper)** | ⛔ **Werkt niet** — de pagina levert de prijs client-side gerenderd aan; de tekstparser ziet nul prijs-tokens. Historie staat daardoor nog op 0 dagen. |
| **Publicatie naar GitHub Pages** | ⛔ **Onbevestigd of structureel opgelost** — deployments hingen vast op `deployment_in_progress`; laatste bekende run na een GitHub-storing slaagde, maar de oorzaak is niet 100% vastgesteld. Een healthcheck faalt de run nu expliciet als de site niet daadwerkelijk bijwerkt (in plaats van dit stil te laten gebeuren). |
| Tankadvies, stale-anchor-hero, offline-status, toegankelijkheid | ◻️ Nog niet gebouwd (sprint 4) |

**Consequentie:** het product levert vandaag een correcte forecast op basis
van de CBS-prijs (tot 9 dagen oud) als anker, niet op de vrijwel-live
adviesprijs. Zolang dat zo is, is de headline-prijs op de pagina ouder dan
een bezoeker verwacht — een expliciet UX-risico dat al is vastgelegd
(§4.2.1 in het verbeterplan) maar nog niet opgelost.

## 6. Modelkwaliteit (echte cijfers, geen synthetische data)

Walk-forward backtest over de laatste 5 jaar CBS-data, 1827 identieke
origins, skill = reductie in MAE t.o.v. "geen verandering":

| Horizon (dagen) | Naïef MAE (ct) | GBM skill | ECM skill |
|---|---|---|---|
| 1 | 2,41 | ~13–16% | ~9–10% |
| 5 | 3,36 | – | – |

(Volledige tabel per horizon in `data/backtest_metrics.json`.) 80%-interval
dekt in de praktijk ~77–78%, dus lichtjes te smal — bekend en nog niet
gekalibreerd op echte data.

**Wat dit betekent:** het model is aantoonbaar beter dan "morgen is het
hetzelfde als vandaag", met een bescheiden maar reële marge, en dat is
vóórdat de twee grootste nog openstaande modelverbeteringen (accijnshistorie
vóór 2022, EBOB in plaats van de RBOB-front-month-proxy met
rolbreuken) zijn doorgevoerd.

## 7. Gebruikersscenario's

1. **"Moet ik nu tanken of kan het wachten?"** — de kernvraag, nog niet
   direct beantwoord in de UI (ingrediënten zitten al in `forecast.json`;
   ontbrekende stap is één samenvattende regel — zie E5-2).
2. **"Wat zit hierachter?"** — beantwoord via de kaart "Waar dit op
   gebaseerd is" en de skill-tabel; transparant over synthetische
   demodata via een banner wanneer live bronnen niet beschikbaar zijn.
3. **"Ik kijk dit terugkerend op mijn telefoon"** — mobile-first bediend,
   maar nog geen PWA-manifest/homescreen-icoon (E5-4).

## 8. Requirements

### 8.1 Functioneel — bestaand (in productie/getest)

- FR1. Toon laatst bekende prijs + herkomst (CBS of adviesprijs) met
  versheid in dagen.
- FR2. Toon 1–5 dagen forecast als lijn + 80%-band, plus per-dag kwantielen.
- FR3. Toon de onderbouwende factoren (groothandel, wisselkoers, accijns)
  in begrijpelijke taal.
- FR4. Toon historische modelnauwkeurigheid (skill vs. naïef) transparant,
  inclusief bij tegenvallende cijfers.
- FR5. Markeer expliciet wanneer de forecast op synthetische in plaats van
  live data draait.
- FR6. Bouw en behoud een eigen archief van de dagelijkse adviesprijs,
  zonder ooit een dag te verliezen door een falende build.
- FR7. Faal zichtbaar (rode CI-run) in plaats van stil een verouderde of
  synthetische forecast te publiceren als "echt".

### 8.2 Functioneel — vastgesteld nodig, nog niet gebouwd

- FR8. **Tankadvies.** Eén regel samenvattend advies ("tanken kan beter
  vandaag: morgen naar verwachting +1,8 ct"), met een eerlijke
  "geen duidelijk signaal"-variant onder de drempel. *Hoogste
  productwaarde-impact van de openstaande taken.*
- FR9. **Stale-anchor-hero.** Zodra het CBS-anker meer dan ~2 dagen oud is,
  de forecast voor vandaag/morgen prominent tonen in plaats van de oude
  gemeten prijs als grootste getal op de pagina.
- FR10. **Offline/foutstatus.** Bij een mislukte fetch de laatst bekende
  forecast (localStorage) tonen met een "verouderd"-label, in plaats van
  een dode foutmelding.
- FR11. **Werkend live GLA-anker.** De scraper moet de dagprijs van de
  daadwerkelijke pagina kunnen lezen (nu client-side gerenderd, dus
  onzichtbaar voor de huidige parser); zonder dit blijft het product op
  een CBS-vertraging van tot 9 dagen hangen voor de "actuele" prijs.
- FR12. **Diesel.** CBS levert de kolom al, GLA-pagina toont de dieselprijs
  al — relatief goedkope uitbreiding zodra het Euro 95-product staat.

### 8.3 Non-functioneel

- NFR1. **Kosten €0** — statische site + gratis CI, bewust behouden als
  architectuurbeperking, niet als toevallige keuze.
- NFR2. **Geen stille datacorruptie.** Elke invariant die het model eerlijk
  houdt (geen lookahead, gepubliceerde labels alleen) wordt afgedwongen
  door een test, niet alleen door documentatie of code review.
- NFR3. **Falen is zichtbaar.** Een gefaalde scrape, een gefaalde publicatie
  of een niet-bijgewerkte site moet een rode run of een issue opleveren —
  nooit een groene run die niets deed.
- NFR4. **Toegankelijkheid.** Tabel-alternatief voor de grafiek, Lighthouse
  a11y-score ≥ 95 (nog te bereiken, zie E5-4).
- NFR5. **Reproduceerbare builds.** Gepinde dependency-versies,
  Dependabot-verhogingen alleen via een groene testrun.

## 9. Succesmetrics

| Metric | Doel | Huidige stand |
|---|---|---|
| Skill vs. naïef, horizon 1 | > 10% | ~13–16% (GBM, echte data) |
| 80%-interval dekking | 78–82% | ~77% (op synthetische data; her-kalibreren op echte data nog te doen) |
| Publicatie-uptime (site draagt de laatste `generated_at`) | Elke daily-run bevestigd live binnen 5 min | Niet structureel bevestigd — belangrijkste openstaande operationele risico |
| Dagen adviesprijs-historie opgebouwd | Groeit met 1/dag zonder gaten | 0 — scraper levert nog geen prijzen op |
| CI-betrouwbaarheid (daily.yml groen excl. Pages-afhankelijke stap) | Hoog | Sprint 2-werk (retries, gepinde deps) afgerond en getest |

De datamoat-metric ("dagen historie") is strategisch de belangrijkste: de
adviesprijs heeft geen publiek archief, dus elke dag zonder werkende
scraper is permanent verloren data, niet in te halen.

## 10. Risico's en afhankelijkheden

- **Scraping-afhankelijkheid van UnitedConsumers** (voorwaarden +
  fragiliteit + nu: client-side rendering die de huidige parser niet
  aankan).
- **Yahoo Finance/Stooq als onofficiële marktdata-bronnen** — gemitigeerd
  met retries, backoff en een tweede provider, maar geen contractuele
  garantie.
- **Gratis GitHub Actions-schedule** wordt uitgeschakeld na 60 dagen
  inactiviteit — zelfvoorzienend zolang de dagelijkse commit blijft lukken.
- **RBOB-front-month-proxy** heeft een structurele knik bij elke contractrol
  (zomer/winterblend); dit maakt rolmaanden het model's zwakste periodes,
  erkend maar nog niet verholpen.
- **Accijnstabel begint pas april 2022**, dus de verlaging van 1-4-2022 en
  alle daarvoor liggende periodes zijn voor het model onzichtbaar. Expliciet
  beleid: dit gat blijft open totdat het met een geverifieerde bron
  (Belastingdienst/wettabel) gevuld kan worden — een verzonnen tarief is
  hier expliciet ongewenst.
- **Publicatieketen naar GitHub Pages** is de enige harde blocker tussen "de
  pijplijn werkt" en "gebruikers zien iets" — zie §5.

## 11. Roadmap (uit `docs/verbeterplan.md`, samengevat)

| Sprint | Doel | Status |
|---|---|---|
| 1 — Site betrouwbaar live, geen historieverlies | Pages ontstoppen, stapvolgorde `daily.yml`, push-race fix, scrape-falen zichtbaar, live scraper-validatie | Grotendeels ✅, Pages-oorzaak (⛔) en scraper-fix (🔶 gediagnosticeerd) nog open |
| 2 — CI onverwoestbaar | Gepinde dependencies, retry/backoff marktbronnen, tests in daily run, hardening | ✅ Afgerond, 57/57 tests groen |
| 3 — Modelkwaliteit en eerlijke evaluatie | Markt-timing rechttrekken, GLA-offset op gelijke dagen, accijnshistorie 2006–2022, RBOB-rolbreuken dempen | ◻️ Nog niet gestart |
| 4 — Productwaarde en UX | Tankadvies, stale-anchor-hero, offline-status, toegankelijkheid, diesel | ◻️ Nog niet gestart |

**Aanbevolen volgorde vanaf nu:** eerst FR11 (werkende scraper) en de
Pages-publicatie hard bevestigen — zonder die twee accumuleert het product
geen datamoat en ziet niemand het resultaat, ongeacht hoe goed sprint 3/4
zijn. Daarna FR8 (tankadvies) omdat alle onderliggende data er al is en het
de kernvraag van de gebruiker rechtstreeks beantwoordt tegen lage
bouwkosten.

## 12. Expliciet buiten scope (nu)

- Prijs per individueel tankstation (vereist CBS 81567NED +
  stationsniveau-kortingsstructuur — bewust een aparte, latere beslissing
  gezien de orde-grotere scope).
- Andere landen/valuta.
- Gebruikersaccounts, notificaties, personalisatie.
- Trading- of professionele inkoopbeslissingen — het product is expliciet
  een consumentenhulpmiddel, geen prijsvoorspeller voor financiële
  besluitvorming.
