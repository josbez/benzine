---
name: Benzineprijs Forecaster
version: alpha
description: Rustige, data-eerlijke mobile-first UI voor een Nederlandse pompprijs-forecast. Kalme "data-journalistiek"-look, geen dashboard, geen hype.
colors:
  page: "#f9f9f7"
  surface: "#fcfcfb"
  text-primary: "#0b0b0b"
  text-secondary: "#52514e"
  text-muted: "#898781"
  grid-line: "#e1e0d9"
  axis: "#c3c2b7"
  border: "rgba(11, 11, 11, 0.10)"
  accent: "#2a78d6"
  price-increase: "#d03b3b"
  price-decrease: "#006300"
  warning: "#fab219"
typography:
  display-lg:
    fontFamily: system-ui
    fontSize: 52px
    fontWeight: "600"
    lineHeight: 55px
    letterSpacing: -0.03em
  display-unit:
    fontFamily: system-ui
    fontSize: 18px
    fontWeight: "500"
    lineHeight: 22px
  headline:
    fontFamily: system-ui
    fontSize: 17px
    fontWeight: "600"
    lineHeight: 22px
    letterSpacing: -0.01em
  label-caps:
    fontFamily: system-ui
    fontSize: 12px
    fontWeight: "600"
    lineHeight: 16px
    letterSpacing: 0.06em
  label-xs:
    fontFamily: system-ui
    fontSize: 11px
    fontWeight: "500"
    lineHeight: 14px
    letterSpacing: 0.04em
  body-md:
    fontFamily: system-ui
    fontSize: 13px
    fontWeight: "400"
    lineHeight: 20px
  body-sm:
    fontFamily: system-ui
    fontSize: 12px
    fontWeight: "400"
    lineHeight: 18px
  numeric-md:
    fontFamily: system-ui
    fontSize: 15px
    fontWeight: "600"
    lineHeight: 20px
    fontFeature: tnum
  numeric-sm:
    fontFamily: system-ui
    fontSize: 11px
    fontWeight: "400"
    lineHeight: 14px
    fontFeature: tnum
rounded:
  sm: 8px
  DEFAULT: 10px
  lg: 14px
  full: 9999px
spacing:
  unit: 4px
  container-max-width: 560px
  container-padding: 16px
  card-padding: 18px 16px
  card-gap: 14px
  section-gap: 20px
  row-gap: 12px
  grid-gap: 6px
components:
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "{spacing.card-padding}"
  card-label:
    textColor: "{colors.text-muted}"
    typography: "{typography.label-caps}"
  hero-price:
    textColor: "{colors.text-primary}"
    typography: "{typography.display-lg}"
  hero-unit:
    textColor: "{colors.text-secondary}"
    typography: "{typography.display-unit}"
  hero-meta:
    textColor: "{colors.text-muted}"
    typography: "{typography.body-md}"
  banner-warning:
    backgroundColor: "rgba(250, 178, 25, 0.14)"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.DEFAULT}"
    padding: 10px 12px
  day-cell:
    backgroundColor: "rgba(11, 11, 11, 0.035)"
    rounded: "{rounded.DEFAULT}"
    padding: 10px 2px
  day-cell-label:
    textColor: "{colors.text-muted}"
    typography: "{typography.label-xs}"
  day-cell-price:
    textColor: "{colors.text-primary}"
    typography: "{typography.numeric-md}"
  day-cell-delta-up:
    textColor: "{colors.price-increase}"
    typography: "{typography.numeric-sm}"
  day-cell-delta-down:
    textColor: "{colors.price-decrease}"
    typography: "{typography.numeric-sm}"
  driver-dot:
    backgroundColor: "{colors.accent}"
    rounded: "{rounded.full}"
    width: 8px
    height: 8px
  driver-title:
    textColor: "{colors.text-primary}"
    typography: "{typography.body-md}"
  driver-body:
    textColor: "{colors.text-secondary}"
    typography: "{typography.body-md}"
  table-header:
    textColor: "{colors.text-muted}"
    typography: "{typography.body-sm}"
  table-cell:
    textColor: "{colors.text-primary}"
    typography: "{typography.body-md}"
  chart-tooltip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: 7px 10px
  chart-band-outer:
    backgroundColor: "rgba(42, 120, 214, 0.10)"
  chart-band-inner:
    backgroundColor: "rgba(42, 120, 214, 0.16)"
  footer-note:
    textColor: "{colors.text-muted}"
    typography: "{typography.body-sm}"
---

## Brand & Style

Dit is geen "fintech-dashboard" en geen nieuwssite met olieprijs-nieuws
eromheen — het is één rustige pagina die één vraag beantwoordt: *wat gaat
de literprijs de komende dagen doen, en hoe zeker is dat?* De referentie is
een goed Nederlands data-journalistiek-artikel (denk NOS/NRC-uitlegkaart)
op een telefoonscherm: veel witruimte, één cijfer dat de aandacht krijgt,
en een grafiek die eerlijk een onzekerheidsband toont in plaats van een
overtuigende rechte lijn.

De toon is *nuchter, niet verkopend*. Geen iconen-overload, geen
kleurexplosie, geen badges die "AI-powered" of "slim" roepen. Vertrouwen
komt uit transparantie (een zichtbare skill-score, een banner zodra data
synthetisch is) en niet uit vormgeving die zekerheid suggereert die er niet
is. Als een ontwerpkeuze de indruk wekt dat het getal preciezer is dan het
model waarmaakt, is het fout — ongeacht hoe mooi het oogt.

Eén kolom, mobile-first, maximaal 560px breed ook op desktop: dit is
bewust geen responsive grid-dashboard, het blijft overal een lijst van
kaarten die je scrollt zoals een artikel.

## Colors

Basispalet is bijna monochroom — steenachtig wit/zwart met warme, niet
klinische grijstinten (`#f9f9f7`, `#52514e`, `#898781` — geen puur `#999`)
— met precies één accentkleur (`#2a78d6`, een gedempt blauw) voor lijnen,
stippen en interactieve highlights. Kleur wordt niet decoratief ingezet;
elke kleur buiten het grijsschema draagt betekenis.

| Rol | Licht | Donker |
|---|---|---|
| Pagina-achtergrond | `#f9f9f7` | `#0d0d0d` |
| Kaart-oppervlak | `#fcfcfb` | `#1a1a19` |
| Primaire tekst | `#0b0b0b` | `#ffffff` |
| Secundaire tekst | `#52514e` | `#c3c2b7` |
| Gedempte tekst / labels | `#898781` | `#898781` |
| Rasterlijnen (grafiek) | `#e1e0d9` | `#2c2c2a` |
| As / scheidingslijn | `#c3c2b7` | `#383835` |
| Rand (kaarten) | `rgba(11,11,11,.10)` | `rgba(255,255,255,.10)` |
| Accent (lijn, stippen, links) | `#2a78d6` | `#3987e5` |
| Prijsstijging (negatief voor de gebruiker) | `#d03b3b` | `#e66767` |
| Prijsdaling (positief voor de gebruiker) | `#006300` | `#0ca30c` |
| Waarschuwing (demodata-banner) | `#fab219` | `#fab219` |

Licht is het standaardthema; donker volgt automatisch uit
`prefers-color-scheme`, met dezelfde tokenstructuur — nooit losse,
onafhankelijk verzonnen donkere kleuren. Rood/groen wordt uitsluitend
gebruikt voor prijsrichting (stijgt/daalt), nooit voor iets anders (geen
rood voor "fout" en groen voor "succes" ergens anders op de pagina) —
anders vervaagt de betekenis van de enige twee semantische kleuren die de
app heeft.

## Typography

Systeemfont overal (`system-ui`) — bewust geen custom webfont geladen; dit
is een pagina van drie statische bestanden en moet dat ook aanvoelen qua
laadgedrag. Twee lettertype-registers:

- **Het cijfer.** De hero-prijs (52px/600, letterspacing −0.03em) is het
  enige element op de pagina dat groot mag zijn. Er is precies één "hero"
  per view — als een nieuw scherm een tweede element op dat formaat
  krijgt, is de hiërarchie kwijt.
- **Alles eromheen is klein en rustig.** Kaarttitels zijn 12px, uppercase,
  brede letterspacing (0.06em) — functioneren als een label, niet als een
  kop. Body-tekst (13px) en meta/voetnoot-tekst (12px) blijven laag in
  gewicht (400) zodat ze niet met de cijfers concurreren.

Cijfers die vergeleken worden (dagprijzen, deltawaarden, tabelrijen) staan
altijd op tabular figures (`fontFeature: tnum`) zodat kolommen niet
"dansen" — dit is een harde eis, geen stijlvoorkeur, omdat de pagina
draait om het vergelijken van getallen onder elkaar.

## Layout & Spacing

Eén kolom, gecentreerd, `max-width: 560px` — ook op grote schermen wordt
dit niet breder, het wordt hooguit meer omringd door lege ruimte. Basisraster
van 4px. Content is opgebouwd uit losse kaarten (`rounded.lg`, 18px/16px
padding, 14px tussenruimte) die elk exact één vraag beantwoorden: laatste
prijs, komende 5 dagen, dagoverzicht, uitleg, modelscore.

Binnen een kaart is de hiërarchie altijd: klein grijs label →
inhoud → optionele kleine toelichtingsregel eronder. Deze volgorde wordt
niet omgedraaid, ook niet in nieuwe kaarten (bijv. een toekomstig
tankadvies-blok volgt dezelfde structuur: label → advies-zin → optionele
nuance-zin).

De 5-dagenoverzicht-grid is altijd exact 5 gelijke kolommen met 6px gap —
dit weerspiegelt de harde modelgrens (nooit meer dan 5 dagen vooruit); een
scherm dat per ongeluk een 6e of 7e kolom toont spreekt de productthese
tegen.

## Elevation & Depth

Deze UI is plat, niet glazig. Diepte ontstaat uit een dun, laag-contrast
randje (`border`, 10% opaciteit) op kaarten en een subtiel
achtergrondverschil tussen kaart en pagina — niet uit schaduwen, blur of
gradients. De enige plek met een echte schaduw is de grafiek-tooltip
(`0 4px 14px rgba(0,0,0,.13)`), omdat die zwevend boven de grafiek moet
lezen; verder heeft niets op de pagina een drop-shadow.

Lagen, van achter naar voor:
1. Pagina-achtergrond (`page`)
2. Kaart-oppervlak (`surface`), rand maar geen schaduw
3. Onzekerheidsband in de grafiek (accentkleur op 10%/16% opaciteit — de
   brede 80%-band lichter dan de smalle 50%-band, nooit andersom)
4. Lijnen, stippen, tooltip

## Shapes

Zachte, consequente afronding, geen scherpe hoeken en geen overdreven
pil-vormen. Twee niveaus volstaan: `10px` voor kleine elementen (banner,
dagcel, tooltip-achtige compacte blokken) en `14px` voor kaarten — kaarten
zijn altijd de meest afgeronde container op de pagina. Cirkels (`full`)
zijn gereserveerd voor betekenisdragende punten: de kleine stip voor elke
"waar dit op gebaseerd is"-regel, en de eindmarkering op de forecast-lijn
in de grafiek. Geen decoratieve cirkels of iconen daarbuiten.

## Components

**Hero.** Eén grote prijs + eenheid + klein label erboven + kleine
metaregel eronder (bron · versheid · datum). Bij een verouderd anker (>2
dagen) moet een toekomstige variant van dit component de *verwachting*
i.p.v. de gemeten prijs tonen als hero — zelfde typografie, andere waarde,
zodat het niet als een nieuw soort element aanvoelt.

**Banner (waarschuwing).** Enige plek waar de warme geel-tint gebruikt
wordt; altijd bovenaan, altijd met een korte vetgedrukte kop gevolgd door
een uitleg-zin. Wordt hergebruikt voor elke toekomstige waarschuwingsstaat
(bijv. "verouderde data" bij een offline-fout) — geen nieuwe bannerstijl
per situatie.

**Dagcel (5×-grid).** Weekdag-label (klein, uppercase, grijs) → prijs
(tabular, 15px/600) → richting-pijl met gekleurde delta → bandbreedte
(kleinst, grijs). Rood/groen alleen op de delta-regel.

**Driver-rij.** Kleine accentstip + korte vette titel + grijze
uitlegregel, in een verticale lijst. Dit is het "uitleg"-patroon van de
hele app en moet niet vervangen worden door iconen-kaarten of een
accordeon — de kracht zit in dat het gewoon leesbare zinnen zijn.

**Tabel (modelscore).** Rechts uitgelijnde cijferkolommen, dunne
onderrand tussen rijen, geen zebra-striping, geen kadrant — een sobere
"boekhoud"-tabel, passend bij de eerlijke, ongepolijste presentatie van
een matig-maar-reëel skill-percentage.

**Fan-chart.** Eén ononderbroken lijn voor gemeten historie, dezelfde
lijn gestippeld voor de forecast-mediaan, met een verticale "nu"-lijn op
het ankerpunt. Twee geneste banden (80% breed/licht, 50% smal/donkerder)
in de accentkleur — nooit meer dan twee band-niveaus, dat wordt visuele
ruis. Puntlabels/tooltip volgen bij aanraken/hoveren, geen permanente
datalabels op elk punt.

## Do's and Don'ts

- **Doe:** houd per view precies één hero-getal; alles anders is
  ondersteunend.
- **Doe:** gebruik rood/groen uitsluitend voor prijsrichting; gebruik
  grijstinten voor al het overige onderscheid.
- **Doe:** toon onzekerheid altijd als band of bandbreedte, nooit als één
  puntgetal zonder marge — ook niet in nieuwe schermen (bijv. een
  tankadvies-regel citeert het bereik, niet alleen de mediaan).
- **Doe:** laat een waarschuwingsstaat (synthetische data, verouderde
  cache, offline) er altijd uitzien als de bestaande gele banner — nooit
  een modal, toast of rode foutpagina.
- **Vermijd:** decoratieve iconen, emoji, illustraties of foto's — dit is
  een cijfer- en tekstpagina, geen consumentenmerk-marketingpagina.
- **Vermijd:** gradients, glasmorfisme, drop-shadows op kaarten, of
  felle/verzadigde merkkleuren — dat hoort bij een ander soort product en
  ondermijnt de "nuchtere data" belofte.
- **Vermijd:** meer dan 5 kolommen/dagen waar dan ook — de horizon van 5
  dagen is een productgrens, geen toevallige lay-outkeuze.
- **Vermijd:** een tweede accentkleur toevoegen voor "net iets anders" —
  breid liever het grijsschema uit dan de kleurenset.
