# Verbeterplan benzineprijs-forecaster

*Analyse d.d. 6 augustus 2026, op basis van de volledige codebase, de testsuite
(41/41 groen) en de GitHub Actions-logs van de afgelopen dag.*

> **Uitvoeringsstatus — sprint 1 en 2 verwerkt (6 augustus 2026).**
> Zie §7 onderaan voor wat er is gebouwd, wat er is geverifieerd en wat er
> per taak nog openstaat. Sprint 3 en 4 zijn nog niet begonnen.

---

## 1. Managementsamenvatting

**De tool is niet kapot — de keten eromheen wel.** De Python-code is van hoge
kwaliteit: de timing van CBS-publicaties wordt correct gemodelleerd, de
backtest is lek-vrij opgezet en alle 41 tests slagen. De echte backtest op
CBS-data laat een reële (bescheiden) meerwaarde zien: het GBM-model zit
13–16% onder de naïeve voorspelling, met ~78% dekking op de 80%-band.

Wat er wél steeds faalt, in volgorde van ernst:

1. **GitHub Pages publiceert niet.** Elke deployment — zowel via de oude
   deployment-API als via de nieuwe `gh-pages`-branchroute — blijft hangen op
   `deployment_in_progress` tot een timeout. De site is nooit live geweest.
   Dit is een platform-/configuratieprobleem, geen codeprobleem, en het is de
   directe oorzaak van vrijwel alle rode runs van vandaag.
2. **De adviesprijs-historie gaat verloren door een stapvolgorde-fout in
   `daily.yml`.** De gescrapete prijs wordt pas ná de forecast-build
   gecommit; faalt die build, dan is de dag definitief weg. De README noemt
   deze historie zelf "the main reason to deploy this sooner rather than
   later" — en `data/raw/gla_history.csv` bestaat op dit moment nog niet.
   Er is dus nog **nul dagen** historie opgebouwd.
3. **Kleinere betrouwbaarheidsrisico's** in CI (pushen zonder rebase,
   ongepinde dependencies, geen retry op flakey databronnen) die elk op
   zichzelf af en toe een rode run veroorzaken.

Het plan hieronder is georganiseerd in 5 epics en 4 sprints. Sprint 1 stopt
het dataverlies en krijgt de site live; daarna pas modelverbeteringen en
productuitbreiding. Per taak staat welk model (Opus 5.0 of Sonnet 5.0) de
uitvoering zou moeten doen en waarom — zie §6 voor het inzetprofiel.

---

## 2. Diagnose: waarom "faalt hij steeds" (met bewijs)

Uit de workflow-runs van 6 augustus 2026:

| Run | Workflow | Uitkomst | Oorzaak |
|---|---|---|---|
| 31109534112 (en ~8 eerdere) | Daily forecast | ❌ | `deploy-pages` pollt `deployment_in_progress` tot timeout na ~10 min |
| 31091602576 | Weekly backtest | ❌ | `ValueError: Found array with 0 sample(s)` in `StandardScaler` — oude codeversie zonder imputer; inmiddels gefixt en door tests afgedekt |
| 31110297203 | Daily forecast (na overstap op gh-pages-push) | ✅ | workflow zelf slaagt |
| 31110887125 | *pages build and deployment* (GitHubs eigen build van de `gh-pages`-branch) | ❌ | **zelfde** `deployment_in_progress`-timeout |

De laatste rij is de kern: de overstap van de deployment-API naar een
branch-push (PR #9) heeft het probleem niet opgelost, alleen verplaatst.
Beide routes eindigen in dezelfde hangende Pages-deployment. De site
(`https://josbez.github.io/benzine/`) serveert dan ook niets. De conclusie in
de README ("a stall in the deployment API cannot block it") is onjuist
gebleken: ook de branchroute loopt door dezelfde deployment-machinerie.

Waarschijnlijke oorzaken, in volgorde van te onderzoeken: een blijvend
vastgelopen deployment in de `github-pages`-environment (op te ruimen via de
REST-API of door Pages uit en weer aan te zetten), environment protection
rules op `github-pages`, of een Pages-configuratie die nog op "GitHub
Actions" als bron staat terwijl er nu vanaf een branch wordt gepubliceerd.

Daarnaast structureel: `daily.yml` verliest bij elke gefaalde build een dag
adviesprijs-historie (zie B-02), en pushes naar `main` vanuit twee workflows
kunnen elkaar afwijzen (B-03).

---

## 3. Codeanalyse

### 3.1 Wat sterk is (behouden!)

- **Timing-discipline.** `features.py` bouwt elke rij uitsluitend op wat op
  die dag kenbaar was; `backtest.py` traint alleen op targets die op het
  refit-moment gepubliceerd waren. De tests
  `test_anchor_is_never_from_the_future` en
  `test_training_targets_are_published_before_the_refit` pinnen dit vast.
  Dit is precies het punt waarop dit soort forecasters meestal stilletjes
  vals speelt, en hier is het goed.
- **Eerlijke evaluatie.** Naïeve benchmark, skill-metric, conformale
  kalibratie van de intervallen (`model.py`), synthetische data expliciet
  gemarkeerd tot in de UI.
- **Diagnostiek in de scraper.** `gla.diagnose()` maakt een 403, cookiewall
  en markup-wijziging onderscheidbaar vanuit een CI-log.
- **Testsuite.** 41 tests, gericht op de fouten die onzichtbaar zouden zijn
  in de output. Lokaal volledig groen.

### 3.2 Bevindingen

Prioriteit: **P0** = veroorzaakt nu falen of onomkeerbaar verlies,
**P1** = maakt resultaten stil slechter of CI breekbaar, **P2** = netheid.

| ID | Prio | Waar | Bevinding |
|---|---|---|---|
| B-01 | P0 | GitHub Pages | Elke Pages-deployment hangt op `deployment_in_progress` (beide routes). Site nooit live. Platform-/configuratieprobleem; vereist handmatige interventie of andere hosting. |
| B-02 | P0 | `.github/workflows/daily.yml` (stapvolgorde) | De adviesprijs wordt gescrapet (stap "Record today's advisory price"), maar pas gecommit ná "Build forecast". Faalt de build — en dat deed hij vandaag ~9×, — dan stopt de job en is de gescrapete prijs weg. Onherstelbaar dataverlies, elke dag opnieuw. Commit direct na de scrape, vóór alles wat kan falen. |
| B-03 | P1 | `daily.yml` + `backtest.yml` | `git push` naar `main` zonder `pull --rebase` en zonder retry. De twee workflows (en Dependabot) kunnen elkaar afwijzen; de maandagochtend-race daily×weekly is reëel. |
| B-04 | P1 | `requirements.txt` | Alleen ondergrenzen (`>=`). CI installeert elke dag de nieuwste pandas/sklearn; een breaking release maakt de build spontaan rood (de sklearn-crash van run 31091602576 was zo'n versie-gevoelige API: `keep_empty_features`). Pin exacte versies + laat Dependabot verhogen. |
| B-05 | P1 | `sources/market.py` | Geen retry/backoff op Yahoo/Stooq; één netwerk-hik = rode dagelijkse run = geen site-update én (door B-02) een verloren dag historie. Yahoo `range=max` elke dag opnieuw is bovendien onnodig zwaar en verhoogt de kans op blokkade. |
| B-06 | P1 | `daily.yml` | Scrape-falen geeft alleen een `::warning` in een log die niemand leest, terwijl elke gemiste dag onherstelbaar is. Maak er een zichtbaar signaal van (automatisch issue, of een aparte statusbadge). |
| B-07 | P1 | `features.py:148` (`_apply_gla_anchor`) | De GLA→CBS-offset wordt geschat als `anchor − gla`, d.w.z. een **verouderde** CBS-prijs (tot 9 dagen oud) tegen de adviesprijs van **vandaag**. In een trendende markt zit de trend van die dagen in de offset gebakken. De test merkt dit niet op omdat de synthetische GLA een constante opslag heeft. Vergelijk GLA(d) met CBS(d) van dezelfde dag zodra CBS die dag publiceert. |
| B-08 | P1 | `features.py` / `sources/market.py` | Marktclose van dag *t* wordt als feature van forecast-origin *t* gebruikt. RBOB settelt 's avonds; de dagelijkse run draait om 05:00 UTC en heeft dan alleen de close van *t−1*. De backtest is daardoor structureel iets optimistischer dan productie ooit kan zijn. Schuif de marktreeks één dag op (of geef hem een `available_from`) en her-run de backtest; verwacht dat de skill-cijfers iets dalen — dat is dan het eerlijke cijfer. |
| B-09 | P1 | `data/excise.yaml` | Schema begint pas april 2022; de accijnsverlaging van 1-4-2022 (~17 ct) is voor het model onzichtbaar en pre-2022 marges hebben een niveaufout. In het bestand zelf al benoemd als "the single cheapest accuracy improvement available". |
| B-10 | P2 | `backtest.py:108` | Blokken met te weinig trainingsdata worden stil overgeslagen; die origins verdwijnen onzichtbaar uit de score. Rapporteer het aantal overgeslagen origins in de metrics. |
| B-11 | P2 | `pipeline.py:41` | `gla.load()` staat buiten de `try` in `load_inputs`; een corrupte `gla_history.csv` breekt ook de synthetische fallback. |
| B-12 | P2 | `sources/cbs.py:47` | De parquet-cache verloopt nooit; lokaal draai je ongemerkt op oude CBS-data. Voeg een versheidscheck toe (bijv. max. 1 dag oud, anders herladen). |
| B-13 | P2 | `README.md` | De Pages-sectie beschrijft de branchroute als immuun voor de deployment-stall; dat is aantoonbaar niet zo (run 31110887125). Corrigeren zodra B-01 is opgelost, met de werkelijke oorzaak. |

---

## 4. Productanalyse

### 4.1 Techniek

De kernthese is goed: de pompprijs volgt de groothandel met dagen vertraging,
dus een 1–5-daagse forecast is grotendeels boekhouding van al gebeurde
bewegingen. De architectuur (statische site + één JSON + twee gratis
workflows) past bij de schaal en kost €0.

Sterk: leak-vrije panelbouw, conformale intervallen, nette fallback-lagen.
Zwak: de operationele keten is de achilleshiel (zie §2), en drie inhoudelijke
compromissen drukken de nauwkeurigheid: de RBOB-front-month-proxy met
rolbreuken (README erkent dit), het accijnsgat vóór 2022 (B-09) en de subtiele
markt-timing (B-08). Belangrijkste strategische kwetsbaarheid: **het product
staat of valt met de GLA-historie die alleen groeit als de dagelijkse run
werkt — en die historie is nu leeg.** Elke dag uitstel van sprint 1 is een
dag verloren datamoat.

Afhankelijkheidsrisico's om te benoemen: scraping van UnitedConsumers
(voorwaarden + fragiliteit), Yahoo Finance (onofficieel endpoint), en de
gratis GitHub Actions-schedule (wordt na 60 dagen inactiviteit uitgezet —
de dagelijkse commit houdt dit levend, mits de run slaagt).

### 4.2 UX / UI

Sterk: mobile-first en rustig; helder Nederlands zonder jargon; de fan-chart
communiceert onzekerheid eerlijk; de "Waar dit op gebaseerd is"-kaart legt in
drie regels uit wat het model doet; demodata krijgt een expliciete banner;
dark mode netjes via `color-scheme` en een thema-attribuut.

Verbeterpunten, op volgorde van impact:

1. **De hero kan misleiden.** Zolang de GLA-anchor niet actief is, toont de
   grootste tekst op de pagina een CBS-prijs van tot 9 dagen oud. De
   toelichting staat er klein onder, maar de bezoeker leest "€ 2,109 /l" als
   *de prijs van nu*. Draai het om zodra de anchor oud is: toon de verwachting
   voor vandaag/morgen als hero en degradeer de laatst gemeten prijs tot
   metadata.
2. **Er ontbreekt een handelingsadvies.** De vraag van de gebruiker is "moet
   ik vandaag tanken of kan het wachten?". Alle ingrediënten zitten al in
   `forecast.json` (mediaan + band per dag); één zin bovenaan ("Tanken kan
   beter vandaag: morgen naar verwachting +1,8 ct") maakt het product af.
3. **Falen is nu een dode pagina.** `fetch` faalt → "geen data" met een
   instructie om Python te draaien — voor een eindgebruiker betekenisloos.
   Toon de laatst bekende forecast (localStorage) met een "verouderd"-label.
4. Kleiner: de backtest-tabel ("Naïef", "Beter") vergt uitleg die nu pas in
   de voetnoot komt; het interval "80% kans" is hardcoded in copy terwijl de
   quantielen configureerbaar zijn; er is geen tabel-alternatief voor de
   chart (toegankelijkheid); geen social/OG-metadata of PWA-manifest voor
   herhaalbezoek vanaf het thuisscherm.

### 4.3 Haalbaarheid

- **Modelmatig: haalbaar, en al aangetoond.** Op echte CBS-data (laatste 5
  jaar, walk-forward): GBM 13–16% beter dan naïef, ECM ~9–10%. Dat is
  bescheiden maar echt, en het is vóórdat de twee grootste bekende
  verbeteringen (accijns-historie, EBOB i.p.v. RBOB) zijn gedaan. In centen:
  ~2,1 ct gemiddelde fout op 1 dag vooruit t.o.v. 2,4 ct naïef.
- **Operationeel: haalbaar, maar nu niet waargemaakt.** Alles wat faalt is
  oplosbaar zonder architectuurwijziging. Het kostenmodel (gratis) blijft
  overeind.
- **Als product: de waarde hangt op versheid.** Zonder werkende GLA-anchor
  is het "advies van vandaag" gebaseerd op een dagen oude prijs; mét
  GLA-anchor (na ~10 dagen overlap) wordt het een echt zelfde-dag-product.
  Daarom is de volgorde van dit plan: eerst de keten, dan het model, dan de
  features.
- **Uitbreidingen** (diesel is bijna gratis — de CBS-kolom wordt al
  meegeladen; per-station is een orde groter en pas zinvol als het landelijke
  product draait) staan bewust in de laatste epic.

---

## 5. Epics, sprints en taken

Sprintlengte: 1 week is realistisch; de taken zijn klein gehouden zodat één
taak = één PR = één reviewbare eenheid. **DoD voor elke taak:** tests groen,
en voor CI-taken één geslaagde `workflow_dispatch`-run als bewijs.

### Epic E1 — Site betrouwbaar live *(sprint 1)*

| Taak | Omschrijving | Uitvoerder | Acceptatiecriteria |
|---|---|---|---|
| E1-1 | **Pages ontstoppen (B-01).** Via de REST-API hangende deployments in de `github-pages`-environment opsommen en cancelen; Pages-bron verifiëren (branch `gh-pages`/root); zo nodig Pages uit- en weer aanzetten. Documenteer de gevonden oorzaak in de README (B-13). | **Opus 5.0** + repo-eigenaar (settings vereisen rechten) | `curl https://josbez.github.io/benzine/forecast.json` geeft 200 met de JSON van de laatste run |
| E1-2 | **Healthcheck na publicatie.** Extra stap in `daily.yml`: na de push naar `gh-pages` max. ~5 min pollen tot de live `forecast.json` de nieuwe `generated_at` draagt; anders faalt de run met een duidelijke melding. Geen stille "geslaagd maar site oud" meer. | Sonnet 5.0 | Kunstmatig oude site → run faalt op de healthcheck; normale run slaagt |
| E1-3 | **Hosting-fallback beslissen.** Kort onderzoek (½ dag, timebox): als E1-1 geen structurele oplossing geeft, `web/` óók naar Netlify of Cloudflare Pages publiceren. Bewust een beslistaak, geen bouwtaak. | Opus 5.0 (advies), mens beslist | Eén A4 met aanbeveling; alleen bouwen na akkoord |

### Epic E2 — Geen dag historie meer verliezen *(sprint 1)*

| Taak | Omschrijving | Uitvoerder | Acceptatiecriteria |
|---|---|---|---|
| E2-1 | **Stapvolgorde `daily.yml` (B-02).** Scrape + commit + push van `gla_history.csv` als eerste stappen (of aparte job), vóór de forecast-build. De build mag falen zonder de dag te verliezen. | Sonnet 5.0 | Simulatie: build-stap geforceerd laten falen → historie-commit staat toch op `main` |
| E2-2 | **Push-race oplossen (B-03).** In beide workflows: `git pull --rebase origin main` vóór de push + retry (3×, backoff). | Sonnet 5.0 | Race-simulatie (tussentijdse commit op main) → push slaagt alsnog |
| E2-3 | **Scrape-falen zichtbaar maken (B-06).** Bij een gefaalde snapshot automatisch een GitHub-issue openen (of bestaand issue van commentaar voorzien) i.p.v. alleen `::warning`. | Sonnet 5.0 | Geforceerde scrape-fout → issue verschijnt met de `diagnose()`-output |
| E2-4 | **GLA-scraper live valideren.** Eénmalig de echte pagina scrapen (lokaal/handmatig), en de vorm van de echte markup als extra testfixture vastleggen. De README markeert de scraper nu als "untested against the live page". | Opus 5.0 | Testfixture gebaseerd op echte pagina; `make snapshot` levert een plausibele prijs |

### Epic E3 — CI-keten robuust *(sprint 2)*

| Taak | Omschrijving | Uitvoerder | Acceptatiecriteria |
|---|---|---|---|
| E3-1 | **Dependencies pinnen (B-04).** Exacte versies in `requirements.txt` (of `pip-compile`-lock), Dependabot doet de verhogingen; de weekly workflow test die al. | Sonnet 5.0 | `pip install` reproduceerbaar; tests groen op gepinde set |
| E3-2 | **Retry/backoff marktbronnen (B-05).** 3 pogingen met exponentiële backoff + jitter per provider; Yahoo-window verkleinen tot incrementeel (cache aanvullen i.p.v. dagelijks `range=max`). | Sonnet 5.0 | Unit-tests met gemockte flaky provider; CI-run slaagt |
| E3-3 | **Tests in de dagelijkse run.** `pytest` (6 s) als stap vóór de build in `daily.yml`. | Sonnet 5.0 | Rode test blokkeert publicatie |
| E3-4 | **Hardening kleinvee (B-11, B-12).** `gla.load()` binnen de fallback-flow; CBS-cache met versheidscheck. | Sonnet 5.0 | Corrupte CSV → nette fout resp. fallback; oude cache wordt ververst |

### Epic E4 — Modelkwaliteit en eerlijke evaluatie *(sprint 3)*

| Taak | Omschrijving | Uitvoerder | Acceptatiecriteria |
|---|---|---|---|
| E4-1 | **Markt-timing rechttrekken (B-08).** Marktreeks één dag verschuiven of `available_from` geven; backtest her-runnen; nieuwe (waarschijnlijk iets lagere) cijfers committen en in de README duiden. | **Opus 5.0** | Test die vastlegt dat features op origin *t* alleen closes ≤ *t−1* gebruiken; metrics ververst |
| E4-2 | **GLA-offset op gelijke dagen (B-07).** Offset schatten uit paren (GLA(d), CBS(d)) zodra CBS dag d publiceert, met dezelfde no-lookahead-shift als nu. Bestaande tests uitbreiden met een trendende GLA-reeks die de huidige fout wél zou aantonen. | **Opus 5.0** | Nieuwe test faalt op de oude implementatie, slaagt op de nieuwe; `test_offset_uses_only_past_overlaps` blijft groen |
| E4-3 | **Accijns-historie 2006–2022 (B-09).** Tarieven uitsluitend uit de Belastingdienst-/wetstabellen overnemen, met bronvermelding per regel in `excise.yaml`. **Zonder bron: niet invullen** — een verzonnen tarief is erger dan het gedocumenteerde gat. | Opus 5.0 voor bronnenwerk, of mens; **niet** delegeren zonder bronplicht | Elke entry heeft een bron-URL in commentaar; backtest her-run toont effect |
| E4-4 | **Overgeslagen backtest-blokken rapporteren (B-10).** `n_skipped_origins` in de metrics en in de CLI-samenvatting. | Sonnet 5.0 | Metrics-JSON bevat het veld; test dekt het overslaan af |
| E4-5 | **RBOB-rolbreuken dempen.** Roll-adjusted reeks (back-adjust op rolmomenten) of een rolmaand-indicator als feature; effect meten in de backtest. | **Opus 5.0** | Vergelijkende backtest vóór/na in de PR-beschrijving; geen leak (test) |
| E4-6 | **Coverage-monitoring op echte data.** De weekly job logt de gerealiseerde 80%-dekking over het afgelopen jaar; wijkt die >5 pt af, dan een issue. | Sonnet 5.0 | Wekelijkse metrics bevatten realized coverage |

### Epic E5 — Productwaarde en UX *(sprint 4)*

| Taak | Omschrijving | Uitvoerder | Acceptatiecriteria |
|---|---|---|---|
| E5-1 | **Hero herzien bij stale anchor (§4.2.1).** Anchor > 2 dagen oud → verwachting voor vandaag als hero, gemeten prijs als metadata. Copy in dezelfde toon als de rest. | Sonnet 5.0 | Beide varianten met een test-`forecast.json` geverifieerd |
| E5-2 | **Tankadvies (§4.2.2).** Eén regel advies op basis van mediaan + band (drempel bv. ±1 ct), inclusief eerlijke "geen duidelijk signaal"-variant. Logica in `pipeline.py` (payload-veld), presentatie in `app.js`. | Sonnet 5.0, drempellogica reviewen door Opus 5.0 | Advies verschijnt alleen boven de drempel; kopij dekt drie gevallen (stijgt/daalt/vlak) |
| E5-3 | **Offline/fout-toestand (§4.2.3).** Laatste forecast in localStorage tonen met "verouderd"-label als fetch faalt. | Sonnet 5.0 | Netwerk uit → laatste data + label i.p.v. "geen data" |
| E5-4 | **Toegankelijkheid + metadata.** Visueel verborgen tabel als chart-alternatief; OG/social-tags; webmanifest voor thuisscherm. | Sonnet 5.0 | Lighthouse a11y ≥ 95; deelbare link toont nette preview |
| E5-5 | **Diesel toevoegen.** De CBS-bron levert de kolom al; GLA-pagina bevat de dieselprijs al (de scraper-fixture toont hem). Panel/model per brandstof parametriseren, UI-tab. | Sonnet 5.0 (mechanisch), panel-parametrisering eerst kort door Opus 5.0 laten schetsen | Twee brandstoffen end-to-end; tests per brandstof |
| E5-6 | *(later, apart besluit)* Per-station forecasting (CBS 81567NED). Bewust buiten dit plan: orde grotere scope, pas na bewezen landelijk product. | — | — |

### Sprintindeling samengevat

| Sprint | Doel | Taken |
|---|---|---|
| 1 | Site live, geen dataverlies meer | E1-1, E1-2, E1-3, E2-1, E2-2, E2-3, E2-4 |
| 2 | CI onverwoestbaar | E3-1 … E3-4 |
| 3 | Model eerlijk en beter | E4-1 … E4-6 |
| 4 | Product afmaken | E5-1 … E5-5 |

---

## 6. Inzetprofiel: Opus 5.0 vs. Sonnet 5.0

De verdeling hierboven volgt uit de sterktes en valkuilen van beide modellen —
en deze repo zelf is er een leerzame illustratie van.

### Opus 5.0

**Sterk in:** diepe oorzaakanalyse over meerdere lagen; subtiele invarianten
(informatietiming, leakage — precies het soort werk dat in deze codebase
uitstekend is gedaan); statistische zorgvuldigheid; het formuleren van
eerlijke beperkingen.

**Valkuilen — zichtbaar in dit project:**

- **Verfijning vóór fundament.** De conformale kalibratie en de
  scraper-diagnostiek zijn voortreffelijk, terwijl de stapvolgorde in een
  YAML-bestand (E2-1) elke dag onherstelbaar data weggooide. Opus optimaliseert
  graag het interessante deel van het probleem.
- **Overtuigend maar onjuist rationaliseren.** De README beargumenteert
  uitvoerig waarom de branchroute de Pages-stall zou omzeilen; de logs bewijzen
  het tegendeel. Een sterke redenatie is bij Opus geen bewijs — eis bij
  infra-claims een geverifieerde run als DoD.
- **Scope-groei en dure iteraties.** Laat Opus niet los op afgebakend
  mechanisch werk; het resultaat wordt groter dan gevraagd.

**Dus:** zet Opus in op E1-1 (diagnose), E4-1/E4-2/E4-5 (leakage-gevoelig
modelwerk), E2-4 (live validatie) en als reviewer van sprint 3. Geef ook Opus
altijd een falende-test-eerst-verplichting bij leakage-taken (zoals E4-2:
de nieuwe test moet op de oude code falen).

### Sonnet 5.0

**Sterk in:** afgebakende, goed gespecificeerde taken; YAML/CI-werk;
retry-patronen; frontend en copy; tests schrijven bij gegeven
acceptatiecriteria; snel en goedkoop, dus geschikt voor het volume van dit
plan (± 70% van de taken).

**Valkuilen:**

- **Patroonherkenning wint van context.** Risico dat Sonnet bij E1/E2 "de
  standaardoplossing" terugzet (bijv. opnieuw `actions/deploy-pages`, omdat
  dat de gangbare route is). Daarom staat bij die taken expliciet wat er *niet*
  mag veranderen; houd die verbodsbepalingen in de PR-beschrijving.
- **Te vroeg "klaar".** Sonnet rapporteert eerder succes op basis van een
  plausibele diff dan op basis van een bewezen run. Vandaar de harde DoD: elke
  CI-taak levert een link naar een geslaagde `workflow_dispatch`-run.
- **Subtiele cross-module-effecten.** De timing-invarianten in `features.py`/
  `backtest.py` zijn makkelijk per ongeluk te breken met een onschuldig ogende
  refactor. Sonnet mag die bestanden alleen aanraken binnen taken waar de
  bestaande leak-tests expliciet als vangnet benoemd zijn (E4-4), niet voor
  E4-1/E4-2.

### Werkafspraken

1. **Eén taak = één PR**, met de taak-ID in de titel en de acceptatiecriteria
   afgevinkt in de beschrijving.
2. **CI-taken bewijzen zichzelf** met een geslaagde run, niet met een diff.
3. **Leakage-taken zijn Opus-only** en beginnen met een test die op de huidige
   code faalt.
4. **Sonnet bouwt, Opus reviewt** in sprint 3; in sprint 1–2 volstaat de
   testsuite + run-bewijs als review.
5. **Niets invullen zonder bron** bij E4-3 — een gedocumenteerd gat is beter
   dan een verzonnen tarief (het bestaande commentaar in `excise.yaml` zegt
   dit al; het blijft de regel).

---

## 7. Uitvoeringsstatus

*Bijgewerkt 6 augustus 2026, na verwerking van sprint 1 en 2.*

### Sprint 1 — site betrouwbaar live, geen dag historie meer verliezen

| Taak | Status | Bewijs / toelichting |
|---|---|---|
| E1-1 Pages ontstoppen | ⛔ **geblokkeerd — actie repo-eigenaar** | Diagnose bevestigd op run `31110887125`: de push naar `gh-pages` triggert GitHubs eigen *pages build and deployment*, die intern `deploy-pages` draait en op precies dezelfde `deployment_in_progress` blijft hangen tot de timeout. Beide routes eindigen dus in dezelfde vastgelopen deployment. Dit is niet vanuit de workflow op te lossen; het stappenplan staat nu in de README (Pages-bron controleren, hangende deployment in de `github-pages`-environment cancelen, protection rules controleren, anders andere hosting). |
| E1-2 Healthcheck na publicatie | ✅ | `.github/scripts/verify_published.py` pollt de live `forecast.json` (cache-busting querystring) tot `generated_at` gelijk is aan de zojuist gebouwde waarde, max. 5 min. Laatste stap van `daily.yml`. **Zolang E1-1 openstaat gaat de dagelijkse run hierop rood** — dat is de bedoeling: een groene run die niets publiceert is precies waarom dit een dag onopgemerkt bleef. |
| E1-3 Hosting-fallback beslissen | ◻️ open | Beslistaak, wacht op de uitkomst van E1-1. Voorwerk staat in de README: Netlify/Cloudflare Pages, drie statische bestanden, geen bouwstap. |
| E2-1 Stapvolgorde `daily.yml` | ✅ | Scrape → commit+push van `gla_history.csv` staan nu vóór tests, build en publicatie. Alles wat daarna faalt kost geen adviesprijs meer. |
| E2-2 Push-race oplossen | ✅ | `.github/scripts/commit-and-push.sh`, gebruikt door beide workflows: rebase op `origin/main` + 3 pogingen met verdubbelende backoff. Lokaal geverifieerd met een echte race (tussentijdse commit op main): push wordt geweigerd, rebaset, slaagt op poging 2, beide bestanden overleven. Ook de faalroute getest: 3 pogingen, dan exit 1 met een `::error`-annotatie. |
| E2-3 Scrape-falen zichtbaar | ✅ | Bij een gefaalde snapshot opent de workflow een issue met label `scraper` en de volledige `diagnose()`-output; bestaat er al een open issue, dan komt er een commentaar bij in plaats van een tweede issue. |
| E2-4 GLA-scraper live valideren | ⛔ **geblokkeerd — netwerkbeleid** | De sessie waarin dit is uitgevoerd komt niet buiten het proxybeleid (`unitedconsumers.com` en `josbez.github.io` geven beide 403 op CONNECT), dus de echte pagina is niet op te halen. Blijft staan; de eerste geslaagde `make snapshot` in Actions is meteen het bewijs. |

### Sprint 2 — CI-keten robuust

| Taak | Status | Bewijs / toelichting |
|---|---|---|
| E3-1 Dependencies pinnen | ✅ | `requirements.txt` staat op exacte versies, alle geverifieerd met een groene suite (57 tests). `.github/dependabot.yml` verhoogt ze wekelijks, wetenschappelijke stack gegroepeerd. **Extra, want anders werkt het pinnen niet:** de repo had geen enkele workflow op `pull_request`, dus een Dependabot-PR werd door niets getest — `.github/workflows/tests.yml` doet dat nu (suite + offline end-to-end run + controle dat synthetische output ook als synthetisch gelabeld blijft). |
| E3-2 Retry/backoff marktbronnen | ✅ | 3 pogingen per provider, exponentiële backoff met jitter, daarna pas de volgende provider; een lege reeks telt als blokkade en gaat direct door (retryen helpt daar niet). Yahoo-window van `range=max` naar 6 maanden zodra er een cache is, met splice waarbij nieuwe rijen winnen op overlappende datums. `actions/cache` bewaart alleen de parquet-caches — nadrukkelijk niet `gla_history.csv`, want die staat in git en een teruggezette oude kopie zou een dag historie terugdraaien. |
| E3-3 Tests in de dagelijkse run | ✅ | `pytest` staat in `daily.yml` vóór de build (en ná de adviesprijs-commit, zodat een rode test geen dag historie kost). |
| E3-4 Hardening kleinvee | ✅ | B-11: `gla.load()` zit in `pipeline._advisory_history()`, dat degradeert naar een lege reeks — bewust *niet* in `gla.load()` zelf, want `record_today()` leest via diezelfde functie en zou de historie dan tot één regel afkappen. B-12: nieuwe `sources/cache.py` met een versheidsregel van 12 uur voor CBS én markt; mislukt de CBS-verversing, dan wordt de oude cache gebruikt met een luide melding in plaats van door te vallen naar synthetische data. |

### Testsuite

41 → **57 tests**, allemaal groen. Nieuw: retry-gedrag (inclusief dat de
backoff groeit en dat een lege reeks níét geretryd wordt), het splicen van de
marktcache en de top-up-route door `fetch()` heen, de versheidsregel, de
begrensde CBS-cache-fallback, en dat een kapotte adviesprijs-historie nog
steeds een forecast oplevert.

Buiten pytest om geverifieerd: de push-race (echte tweede commit op `main` →
rebase → geslaagd op poging 2) en de healthcheck (exit 0 bij een passende
`generated_at`, exit 1 met `::error` bij een verouderde site).

### Wat expliciet níét is gedaan

Sprint 3 (E4-1 t/m E4-6, modelkwaliteit) en sprint 4 (E5-1 t/m E5-5, UX) zijn
niet aangeraakt. Voor de twee zwaarste daarvan — de markt-timing (B-08) en de
GLA-offset (B-07) — geldt bovendien dat ze pas af zijn als de backtest opnieuw
is gedraaid en de nieuwe, waarschijnlijk iets lagere cijfers zijn gecommit. Dat
vereist live CBS- en marktdata, en dus een omgeving die daar wél bij kan.
