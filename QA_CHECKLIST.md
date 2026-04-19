# Baseball DFS Sims — QA Checklist

> Last updated: 2026-04-16
> Run this checklist before every Netlify deploy. Items marked [CRITICAL] block deploy.

---

## 1. Build & Deploy Prerequisites

- [ ] `npm run build` completes without errors [CRITICAL]
- [ ] No TypeScript/ESLint warnings in build output
- [ ] Backend `fly deploy` succeeds and `/health` returns OK [CRITICAL]
- [ ] Backend syntax check passes: `python3 -c "import py_compile; py_compile.compile('services/simulator.py', doraise=True); py_compile.compile('api/simulator.py', doraise=True)"`

---

## 2. Global State & Persistence

### App Context
- [ ] User selection (5 fake users) persists on refresh
- [ ] Site (DK/FD) persists on refresh
- [ ] Selected date persists on refresh
- [ ] Selected slate persists and validates on date/site change
- [ ] Builds persist per user+date+slate key
- [ ] Current build index persists per user+date+slate key
- [ ] Uploaded contests persist per user+date+slate key
- [ ] Corrupted localStorage handled gracefully (doesn't crash)

### Header Bar
- [ ] Date picker restricts to valid range
- [ ] Slate dropdown populates for selected date+site
- [ ] Slate shows game count and [H] badge for historical
- [ ] Build dropdown shows all builds with lineup counts
- [ ] "New Build" button creates empty build
- [ ] Site switcher triggers slate reload
- [ ] User selector shows all 5 users with color indicators

---

## 3. Dashboard

- [ ] Welcome card shows current user name and color
- [ ] Session summary shows: slate name, build name, lineup count, contest count
- [ ] Lineup count green if > 0, gray if 0
- [ ] Contest count blue if > 0, gray if 0
- [ ] "How It Works" step links navigate to correct pages
- [ ] Quick-link cards navigate to correct pages

---

## 4. Projections

### Data Loading
- [ ] Loading spinner on initial load [CRITICAL]
- [ ] Error alert if API fails
- [ ] "Historical slate" amber alert when applicable
- [ ] "No players match" message for empty filter results

### Hitters Tab
- [ ] Search filter (case-insensitive, partial match)
- [ ] Position filter (ALL, C, 1B, 2B, 3B, SS, OF)
- [ ] Team filter dropdown
- [ ] Salary range slider filters correctly
- [ ] Min projection slider filters correctly
- [ ] All filters work in combination
- [ ] Columns sortable (click header toggles asc/desc)
- [ ] Status badges: green=confirmed, amber=expected, blue=projected
- [ ] Player exclusion (click salary cell) works
- [ ] Excluded players shown at bottom of table
- [ ] Min/Max exposure % inline editing works (0-100 validation)

### Pitchers Tab
- [ ] Same filter/sort/exclusion behavior as hitters
- [ ] Correct pitcher-specific columns (ERA, K/9, K Prop)
- [ ] Opener status badges: orange "PO" tag for projected openers, blue "PLR" for probable long relievers

### Teams Tab
- [ ] Teams sorted by implied total descending
- [ ] Stack min/max inputs (3/4/5-stack) accept 0-100%
- [ ] Stack exposure values persist to context
- [ ] Team roster expands showing SP + batting order

---

## 5. Lineup Builder

### Controls
- [ ] Lineup count input (1-500) syncs with slider
- [ ] Variance slider (0-100%) updates display
- [ ] Projection skew (Safe/Balanced/Upside) toggles
- [ ] Min salary slider adjusts correctly per site
- [ ] "Build N Lineups" button starts build [CRITICAL]
- [ ] "Cancel Build" stops in-progress build
- [ ] Build disabled if lineup count is 0
- [ ] Error alert if build fails

### Results
- [ ] Generated lineups display with count
- [ ] Avg Salary and Avg Proj shown in header
- [ ] Tab toggle: "Lineups" (default) / "Player Exposure"
- [ ] Lineups tab: top 15 exposure summary with "View all →" link
- [ ] Player Exposure tab: all players with editable min/max limits
- [ ] Player Exposure tab: actual exposure % with color-coded bars (red=over max, amber=under min)
- [ ] Player Exposure tab: search filter by name/team
- [ ] Player Exposure tab: Pitchers/Hitters/All filter toggle
- [ ] Exposure calculation counts each player once per lineup (Set dedup for dual SP slots)
- [ ] Lineup cards show salary, projection, full player list
- [ ] Lineup cards collapse/expand (first expanded by default)
- [ ] Lineup lock toggle (lock icon) on each lineup card
- [ ] Locked lineups preserved on rebuild; only unlocked slots rebuilt
- [ ] Locked count indicator shown above lineup list
- [ ] Build button shows "(N locked)" when lineups are locked
- [ ] Locks respected over exposure limits when conflicting
- [ ] Clear lineups also clears all locks
- [ ] Lineups saved to current build in context [CRITICAL]

### Exposure Enforcement
- [ ] Min/max exposure from Projections tab sent to optimizer as `exposure_overrides` [CRITICAL]
- [ ] Setting max exposure to 60% actually limits lineup output to ~60%
- [ ] Exposure limits only relaxed when not enough valid lineups can be generated
- [ ] Large lineup pools (100-500) generate successfully without timeout

### Cross-Page
- [ ] Exposure limits from Projections tab carry over to optimizer
- [ ] Exposure edits on Lineup Builder sync back to Projections (bidirectional via context)
- [ ] Player exposures persist per user+date+slate (localStorage key: dfs-exposures-...)
- [ ] Stack exposures from Teams tab carry over to optimizer

---

## 6. Contest Import

### CSV Upload
- [ ] Drop zone accepts .csv files only
- [ ] Drag-and-drop works
- [ ] Click-to-browse works
- [ ] Shows spinner during upload
- [ ] Success: lists all contests with fee, field size, entries, prize pool
- [ ] Skipped rows alert (amber) if any rows invalid
- [ ] Error alert (red) if file format wrong [CRITICAL]
- [ ] "Proceed to Build Lineups" navigates correctly
- [ ] "Go to Simulator" navigates correctly
- [ ] "Import Another" resets upload state
- [ ] Contests saved to context (persist per user+slate) [CRITICAL]

### Manual Contest ID
- [ ] Text input for contest ID
- [ ] Number input for entries (1-150)
- [ ] Import button creates contest entry

---

## 7. Game Center

### Game Cards
- [ ] Away @ Home team display
- [ ] Game time shown
- [ ] Vegas: O/U, spread, implied totals
- [ ] Weather: temp, wind, precipitation
- [ ] Wind compass: direction arrow, speed label, color (out=green, in=red, cross=amber)
- [ ] Dome indicator hides wind compass
- [ ] Lineup confirmation badges per team

### Lineups
- [ ] Starting pitcher: name, handedness badge, salary
- [ ] Opener status badges shown next to pitcher/batter names (PO=amber, PLR=blue)
- [ ] Batting order: slot 1-9, position, name, handedness, salary
- [ ] Status badge: Confirmed/Expected/Projected
- [ ] "Lineup not yet posted" if no data

### Live Features
- [ ] Live score badge (LIVE red with pulse, or FINAL)
- [ ] Scores update on auto-refresh
- [ ] Slate filter toggle ("Slate Only" / "All Games")
- [ ] Manual refresh button

### Auto-refresh
- [ ] Lineups refresh every 2 minutes
- [ ] Live scores refresh 30s (live games) / 60s (otherwise)

---

## 8. My Contests

### Contest Cards
- [ ] Contest name, ID, last updated
- [ ] Stats: entry fee, field size, prize pool, entries, at risk, top prize
- [ ] Lineup assignment status (green=all, amber=partial, red=none)
- [ ] View Entries expands entry list

### Late Swap
- [ ] "Check Swaps" button triggers swap check
- [ ] Results: per-entry swap suggestions (out→in players)
- [ ] "No swaps needed" green checkmark if clean
- [ ] Close button hides results

### Quick Sim
- [ ] "Re-Run Sim" button triggers simulation
- [ ] Results: Avg ROI, Cash Rate, Win Rate
- [ ] Per-lineup breakdown table
- [ ] Close button hides results

### Live Tracking
- [ ] Leaderboard section (rank, entry, score, payout)
- [ ] Ownership section (top players by %)
- [ ] Stack analysis section
- [ ] Auto-refresh when sections are open (60s)

---

## 9. Simulator [CRITICAL FLOW]

### Setup Panel
- [ ] Lineup count from current build displayed
- [ ] Alert if no lineups built
- [ ] Portfolio summary: contests, entries, investment, prize pools
- [ ] Contest list with entry count + fee
- [ ] Sim count slider (1K-50K) persists to localStorage
- [ ] Pool Strategy toggle (Ownership/Archetype) persists
- [ ] Pool Variance slider (0-100%) persists
- [ ] "Allow duplicate lineups across contests" toggle (default: off) persists
- [ ] Manual contest config shown if no DK entries uploaded

### Running Simulation
- [ ] "Simulate All N Contests" button starts sim [CRITICAL]
- [ ] "Cancel Simulation" stops sim
- [ ] Progress bar advances linearly to ~90%, then slows
- [ ] Progress bar roughly tracks actual completion time
- [ ] Animated emoji + DFS joke text changes with progress
- [ ] Sim completes and results render [CRITICAL]

### Portfolio Summary
- [ ] Avg ROI (green/red based on sign)
- [ ] Investment total
- [ ] Expected Profit (green/red)
- [ ] Cash Rate %
- [ ] Top 10% rate
- [ ] Contest/entry/sim counts shown

### Per-Contest Results
- [ ] Contest card: name, entries, fee, field size
- [ ] Collapsed: shows avg ROI + cash rate (uses assigned_overall metrics)
- [ ] Expanded: Avg ROI, Cash Rate, Win Rate, Top 10% [CRITICAL]
- [ ] Contest metrics reflect only assigned lineups, not all candidates
- [ ] ROI Distribution chart renders with color-coded bars
- [ ] Entry Assignments table: Entry ID, LU#, player pills, ROI
- [ ] Entry edit mode: dropdown to reassign lineup
- [ ] Lineup Results table: sortable by all columns
- [ ] Lineup expand: shows full roster with pos/name/team tags

### Lineup Assignment Rules [CRITICAL]
- [ ] No duplicate lineups within the same contest — ever
- [ ] With "Allow duplicates" off: each lineup used in at most one contest
- [ ] With "Allow duplicates" on: lineups can repeat across contests but not within
- [ ] Higher-stakes contests get first pick of lineups
- [ ] If n_entries > n_lineups, only top-N entries get assigned (no cycling)

### Sim Engine v1: Contest-Aware Field Sharpness
- [ ] Field sharpness derived from contest attributes (max_entries, game_type, field_size, entry_fee)
- [ ] Cash/H2H contests produce sharper fields (more optimizers, fewer casuals)
- [ ] High entry fee contests produce sharper fields
- [ ] Single-entry contests produce sharper fields than 150-max-entry GPPs
- [ ] Ownership strategy uses contest-aware variance (sharp=low noise, soft=high noise)
- [ ] Archetype strategy uses contest-aware mix (sharp=more optimizers/sharps, soft=more casuals)

### Metric Definitions (verify values are reasonable)
- [ ] **Avg ROI**: avg (payout - fee) / fee * 100 across all sims
- [ ] **Cash Rate**: % of sims where entry finishes in the money
- [ ] **Win Rate**: % of sims where entry finishes #1
- [ ] **Top 10%**: % of sims where entry finishes in top 10% of field
- [ ] All lineups show different values (not all identical) [CRITICAL]

### Export
- [ ] "Export All to DK" downloads CSV
- [ ] CSV format: Entry ID, Contest Name, Contest ID, Entry Fee, roster slots
- [ ] Player format: "PlayerName (DK_ID)"

### Persistence
- [ ] Sim results persist on page refresh [CRITICAL]
- [ ] Results keyed to user+date+slate+build
- [ ] Switching builds loads correct sim results
- [ ] Entry assignments saved to backend

---

## 10. Backtesting

- [ ] Shows "Coming Soon" overlay
- [ ] All form elements disabled
- [ ] Layout visible but grayed out

---

## 11. Cross-Page Workflows

### E2E Simulation Flow [CRITICAL]
1. [ ] Select date → slate loads
2. [ ] View Projections → set exposures
3. [ ] Build Lineups → lineups generated
4. [ ] Import Contests → contests parsed
5. [ ] Run Simulation → results display
6. [ ] Export to DK → CSV downloads

### Multi-Build Isolation
- [ ] Create Build 2 → generate different lineups
- [ ] Switch builds → correct lineups shown
- [ ] Sim results per build are independent
- [ ] Switch back → original build data intact

### Multi-User Isolation
- [ ] User 1 data doesn't leak to User 2
- [ ] Switch users → different builds/contests/results
- [ ] Switch back → original user data intact

### Date/Site Change Cascade
- [ ] Change date → slates reload → projections reload
- [ ] Change site → slates reload → projections reload
- [ ] Previous data for old date/slate untouched in storage

---

## 12. Error & Edge Cases

### Empty States
- [ ] No slates for date: appropriate message
- [ ] No projections: historical slate message
- [ ] No contests uploaded: manual config shown in simulator
- [ ] No games: empty state message
- [ ] No lineups: alert in simulator

### API Failures
- [ ] Network error: friendly message displayed
- [ ] 4xx errors: error text shown
- [ ] 5xx errors: generic error message
- [ ] Cancelled requests (AbortError): silently ignored

### localStorage
- [ ] Full storage: writes fail silently
- [ ] Corrupted data: falls back to defaults
- [ ] Missing keys: uses defaults

---

## 13. localStorage Keys Reference

| Key Pattern | Content |
|---|---|
| `dfs-user-id` | Current user ID |
| `dfs-site` | DK or FD |
| `dfs-selected-date` | YYYY-MM-DD |
| `dfs-selected-slate` | Slate object JSON |
| `dfs-builds-{userId}-{date}-{slateId}` | Builds array |
| `dfs-build-idx-{userId}-{date}-{slateId}` | Current build index |
| `dfs-contests-{userId}-{date}-{slateId}` | Contests array |
| `dfs-sim-results-{userId}-{date}-{slateId}-b{buildId}` | Sim results + assignments |
| `dfs-exposures-{userId}-{date}-{slateId}` | Player exposure limits (min/max) |
| `dfs-sim-count` | Sim count setting |
| `dfs-pool-variance` | Pool variance % |
| `dfs-pool-strategy` | ownership or archetype |
| `dfs-allow-dup-lineups` | Allow duplicate lineups across contests |

---

## 14. CI/CD Pipeline Reference

> Automated via GitHub Actions. Workflows live in `.github/workflows/`.

### How It Works

```
staging branch          main branch
    |                       |
    |  push/PR             merge from staging
    v                       v
 [test.yml]            [deploy-production.yml]
    |                       |
    | (tests pass)         deploys backend to Fly.io
    v                      builds frontend artifact
 [deploy-staging.yml]      tags release (v2026.04.19.X)
    |
    | deploys backend to Fly.io
    | builds frontend artifact
    v
  Download artifact → drag into Netlify (manual step)
```

### Secrets Required (GitHub > Repo Settings > Secrets > Actions)

| Secret | How to get it |
|---|---|
| `FLY_API_TOKEN` | Run `fly tokens create deploy` in terminal |

### After a Staging Deploy

1. Go to Actions tab on GitHub
2. Find the completed "Deploy Staging" run
3. Download the `frontend-staging-build` artifact
4. Unzip and drag the folder into Netlify staging site

### After a Production Deploy

1. Same as staging but download `frontend-production-build`
2. Drag into Netlify production site
3. A git tag is auto-created (e.g., `v2026.04.19.3`)
