# Frontend — copytrade.pm dashboard

React + Vite + TypeScript. Dense, terminal-grade dashboard for the copy-trade
bot. Talks to the FastAPI backend over `/api` (proxied in dev).

## Run

```bash
# 1. Start the backend first (see ../backend/README or ../README.md)
# 2. Then:
npm install
npm run dev            # http://localhost:5173  (proxies /api → :8000)
```

`npm run build` type-checks (`tsc -b`) and bundles. `npm run preview` serves the
build.

## Design system

The look is defined once in [`src/styles/tokens.css`](src/styles/tokens.css) and
consumed everywhere via CSS Modules — no utility framework, no inline color.

- **Neutral base, semantic color only.** Green = profit, red = loss, yellow =
  warning, blue = interactive/info. Nothing is colored for decoration.
- **Typography carries hierarchy.** Tabular figures on every number
  (`.tnum` / `.mono`); large figures command attention, secondary text recedes.
- **4px spacing scale, two radii, hairline borders** — no shadows for structure.
- **Restrained motion** (160–220ms fades/moves), one calm status pulse.

## Structure

```
src/
  styles/        tokens.css (the system) + global.css (reset)
  lib/           api client, typed models, formatters, query hooks, follow store
  components/
    ui/          Button, Badge, StatTile, Value, BarMeter, SegmentedControl,
                 StatusDot, EmptyState, Icon (inline SVG set)
    layout/      AppShell, Sidebar, TopBar, PageHeader, Page
  features/
    discover/    leaderboard + expandable open-book (the flagship view)
    following/   traders you copy
    book/        your positions (Phase 2)
    activity/    audit log (Phase 2)
    settings/    risk limits + the live-trading gate
```

## Data & "live" feel

`@tanstack/react-query` polls `/api/snapshot` (30s) and `/api/status` (15s). The
connection dot and mode badge reflect real backend state. Empty states are
honest — surfaces that depend on a later backend phase say so rather than showing
placeholder data.
