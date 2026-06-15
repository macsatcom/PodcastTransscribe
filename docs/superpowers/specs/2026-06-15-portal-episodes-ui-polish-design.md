# Portal Episodes UI Polish — Design Spec

**Date:** 2026-06-15
**Status:** Approved

## Problem

Episodes-tabben fungerer funktionelt, men visual hierarchy er stadig tæt på generiske result cards. Brugeren ønsker en mere kompakt, skannbar "tight list" med summary altid synlig i max 3-4 linjer.

## Goal

Polish Episodes-tabben visuelt uden backend-ændringer:
- Tæt liste-layout med klar metadata-hierarki
- Podcast-badge og kompakt meta-linje
- Summary altid synlig, clampet til 4 linjer
- Mobilvenlig uden at bryde eksisterende Search/Insights layout

## Out of Scope

- Ingen API-ændringer
- Ingen ny filtrering/sortering
- Ingen ændring af Search/Insights adfærd
- Ingen ny template-fil

## UX Direction (Chosen)

Valgt retning: **Tight List**.

Hver episode vises som én kompakt klikbar række:
1. Toplinje: titel (venstre) + dato/varighed (højre)
2. Podcast-badge under titel
3. Summary preview under badge, altid synlig, clampet til max 4 linjer

## Content Rules

- Summary skal altid være synlig:
  - Primær kilde: `ep.summary_excerpt` (hvis tilgængelig)
  - Fallback: `ep.description` kort preview
  - Hvis begge mangler: fast placeholder `No summary available.`
- Line clamp: 4 linjer på desktop og mobil.

## Technical Design

**File:** `app/templates/portal_home.html`

### CSS additions

Tilføj små, lokale Episodes-klasser i eksisterende `<style>`:
- `.episodes-list`
- `.episode-row`
- `.episode-head`
- `.episode-title`
- `.episode-meta`
- `.episode-badge`
- `.episode-summary`
- `.line-clamp-4`

`line-clamp-4` implementeres med `-webkit-line-clamp` + `-webkit-box-orient` + `overflow:hidden`.

### Markup update

I Episodes-panelet erstattes nuværende generiske `result-card`-struktur med den nye tight-list struktur. Hele rækken forbliver klikbar (`<a href="/episodes/{id}">`).

### Data usage

Brug eksisterende episodeobjekt, men render summary robust:
- `ep.summary_excerpt || clip(ep.description) || 'No summary available.'`

`clip()` implementeres i Alpine (fx 220 tegn) og bruges kun til fallback-preview.

### Responsiveness

- Desktop: titel + meta på samme linje
- Smal skærm: meta brydes under titel automatisk

## Testing

- Kør integration-tests der dækker portal + episodes API:
  - `tests/integration/test_auth_portal.py`
  - `tests/integration/test_episodes_api.py`
- Kør fuld suite (`pytest -q`) før push.

## Estimated Scope

| File | Change |
|------|--------|
| `app/templates/portal_home.html` | ~60-100 linjer ændret/tilføjet |
