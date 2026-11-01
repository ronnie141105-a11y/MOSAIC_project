# ASTRA — TSN TMA Profile: Build Plan & Instructions

**Audience:** this document is written for whoever (human or AI agent) implements
the work — not for the end user. It assumes access to the ASTRA repository and
the three source files listed in section 1. Follow the steps in order; each
step names its deliverable and how to check it before moving on.

## Start here (do this before anything in section 1+)

This plan was written from the source charts alone — **not** from reading the
ASTRA repo in detail. Before writing any code or data file, spend one pass
reviewing the actual project so the assumptions below get corrected against
reality rather than layered on top of a guess. Specifically open and read:

1. `README.md` — pipeline overview and module map.
2. `docs/architecture.md` and `docs/Developer_Handover.md` — data-flow detail
   and known limitations; check whether anything there already anticipates
   multi-airspace support (it may not, but check before assuming you're
   building this from nothing).
3. `astra/utils/config.py` (`ASTRAConfig`) — confirm how sector/route paths
   are currently wired in, since section 4.6 below assumes this is where a
   `--profile` selection would plug in.
4. Whatever currently defines routes/waypoints for the FIR (likely under
   `scenarios/builder/` and/or `astra/dashboard/geo/`) — open an actual
   example file and see its real schema. Section 3 below proposes a schema
   from scratch; if an existing route/waypoint schema is close enough, extend
   it instead of introducing a second, incompatible one.
5. `astra/trajectory/` — specifically whatever builds a flyable path from a
   route definition today (constant-velocity vs "route-aware" per the
   README). This is the code section 4.2/4.5 below will need to change.
6. `main.py` — how it currently picks sectors/scenario data on startup, since
   section 4.6 assumes a flag can be added here.
7. `tests/` — find the existing route/trajectory tests so the new TSN data
   can be exercised the same way, and so nothing here breaks the existing
   FIR test suite.

If anything in sections 1–7 of this plan conflicts with what's actually in
the repo (a field name, a file location, an assumption about how routes are
loaded), **follow the repo, not this document** — update the plan section
in question with a one-line note on what changed and why, then continue.
Don't silently diverge from the written plan without leaving a trace of why.

Source materials for this task (charts + waypoint spreadsheet) are bundled
alongside this plan in `source_materials/` — see section 1 below for what
each file is.

---

## 0. Decision already made — do not re-litigate

- **Do not modify or remove the existing Ho Chi Minh FIR data.** It stays as-is
  under whatever path it currently lives in (`scenarios/`, `astra/dashboard/geo/`,
  demo scenarios `nominal` / `crosstrack` / `arrival45`).
- TSN TMA is a **new, separate airspace profile**, loaded by name, not a
  replacement. The six pipeline engines (`trajectory`, `hotspot`, `complexity`,
  `tracking`, `forecast`, `resolution`) are airspace-agnostic already — they
  consume whatever sectors/routes/config a profile hands them. Do not add any
  FIR- or TSN-specific branching inside those engines. If an engine needs a new
  *capability* (e.g. "honor a holding pattern"), add it as a general feature,
  not a TSN-only special case.
- Scope for this pass: **RWY 25L/25R configuration only** (no RWY 07 charts
  exist yet). **SID + STAR only** — no approach/missed-approach modeling this
  pass.

## 1. Source files (ground truth — do not invent data not present here)

All files below are in `source_materials/` next to this plan.

| File | Contents |
|---|---|
| `10430.pdf` | Area chart (TMA Tan Son Nhat) — sector geometry, FIR/TMA/CTR boundaries, en-route waypoints/routes context |
| `10520.pdf` | Conventional SID, RWY 25L/R — 12 named departures with full text procedures |
| `83847.pdf` | RNAV SID — ANTRI 2D, LANHI 2D + shared "Initial Climb" inset |
| `83854.pdf` | RNAV SID — KADUM 2D, SAPEN 2D, BACHU 2D, MISAN 2D, ENPAS 2D, XOBAV 2D + shared "Initial Climb" inset |
| `56080.pdf` | STAR — ELSAS 2H, BITIS 2H, VICAL 3H, SAPEN 2H |
| `56084.pdf` | STAR — DALAP 2H |
| `56090.pdf` | STAR — DALAP 2J |
| `Danh_Sach_Lo_Diem_Waypoints_WGS84.xlsx` | 149 waypoints, WGS-84, DMS coordinates — named fixes, `RW07L/R`/`RW25L/R` thresholds, and unnamed `TS###` sequence fixes used as leg turn points on the RNAV charts |
| `10453.pdf` | ILS Y RWY 25R approach — **out of scope this pass**, keep on hand for the next one |

Do not source waypoint coordinates from anywhere except the Excel file. Do not
source procedure logic from anywhere except the matching chart PDF. If a name
appears on a chart but not in the Excel (or vice versa), flag it — don't guess
a coordinate or a leg.

## 2. Directory layout to create

```
scenarios/profiles/
  hcm_fir/            <- existing data, move here unchanged, no content edits
  tsn_tma/
    waypoints.json
    sids/
      ac_1r.json ... (12 conventional, see 3.2)
      antri_2d.json, lanhi_2d.json
      kadum_2d.json, sapen_2d.json, bachu_2d.json, misan_2d.json, enpas_2d.json, xobav_2d.json
    stars/
      elsas_2h.json, bitis_2h.json, vical_3h.json, sapen_2h.json
      dalap_2h.json
      dalap_2j.json
    tma_boundary.json
    profile.json      <- manifest tying the above together (see 3.5)
```

If `hcm_fir` data doesn't currently live in a path that matches this layout,
create `hcm_fir/` as a thin wrapper/symlink-equivalent that points at the
existing files rather than duplicating them — the goal is a consistent
`--profile <name>` interface, not a data migration.

## 3. Data extraction — step by step

### 3.1 Waypoints (`waypoints.json`)

- Parse the Excel, convert every DMS coordinate (`DDMMSS.sssN`, `DDDMMSS.sssE`)
  to decimal degrees. Keep both forms if useful for debugging, but the schema
  field consumed by code should be decimal degrees.
- Schema per entry:
  ```json
  {"name": "SAPEN", "lat": 11.020000, "lon": 106.183333, "type": "named_fix"}
  ```
  Set `"type"` to `"runway_threshold"` for `RW07L`, `RW07R`, `RW25L`, `RW25R`,
  and `"sequence_fix"` for anything matching `TS\d+`. Everything else is
  `"named_fix"`.
- Output: all 149 entries. No filtering, no dropping "unused" points — a point
  not used by a SID/STAR this pass may be needed by the approach chart next
  pass.
- **Check before continuing:** count must be 149. Spot-check at least 5 named
  fixes (e.g. `SAPEN`, `DALAP`, `ANTRI`, `BITIS`, `ELSAS`) against their
  position on the chart images by eye — do they sit where the chart shows them
  relative to TSH VOR/DME (10°49'06"N 106°39'02"E)?

### 3.2 Conventional SIDs (`10520.pdf` → 12 files)

Each of AC1R, BAOMY1R, DONXD1R, BITIS1R, BACHU1R, ENPAS1R, LANHI1R, XOBAV1R,
KADUM1R, MISAN1R, SAPEN1R, VTV1R has a **numbered text procedure** on the
chart (not just a plotted line) — transcribe it directly, e.g.:

> BACHU ONE ROMEO DEPARTURE (BACHU 1R): after departure, maintain RWY heading
> to D4.3 TSH, turn left to intercept R-251 TSH at D13.8 TSH to BACHU.

Schema per SID file:
```json
{
  "id": "BACHU1R",
  "kind": "sid",
  "runway": ["25L", "25R"],
  "coordination_required": false,
  "legs": [
    {"instruction": "maintain runway heading", "until": {"type": "dme", "fix": "TSH", "distance_nm": 4.3}},
    {"instruction": "turn left, intercept radial", "radial": 251, "from_fix": "TSH", "until": {"type": "dme", "fix": "TSH", "distance_nm": 13.8}},
    {"instruction": "direct", "to_fix": "BACHU"}
  ],
  "terminates_at": "BACHU"
}
```
Set `"coordination_required": true` only for **DONXD1R** and **KADUM1R** (the
chart explicitly gates these on coordination with Regional Air Command Centre
III — re-check the usage-condition note on the chart, don't assume which ones).
This schema is deliberately closer to the chart's own text than to lat/lon —
converting radial/DME instructions into an actual flyable polyline is a
separate downstream step (5.2), not part of extraction. Don't collapse that
conversion into this step; keep the transcription faithful and literal first.

### 3.3 RNAV SIDs (`83847.pdf`, `83854.pdf` → 8 files)

These differ from the conventional SIDs: each is a **plotted RNAV path**
through named/sequence fixes, not a text procedure, and each pair of charts
shares one "Initial Climb" inset that is common to *all* routes on that chart
before they diverge.

- Model the initial-climb segment as its own leg list, referenced by every SID
  that shares it (don't duplicate it into every file — put it once and have
  each SID file point at it, e.g. `"initial_climb_ref": "tsn_initial_climb_83854"`).
- Each named route (e.g. `KADUM 2D`) is then: initial climb → ordered list of
  `TS###`/named fixes → terminus. Capture per-leg altitude constraints exactly
  as printed (e.g. `TS454 AT 2150`, a hard altitude; `MAX 4250` on a route
  segment box, a ceiling not a hard level — encode these as different
  constraint types, don't flatten both into one "altitude" field).
- Capture the climb-gradient notes from each chart's callout box (e.g. "MNM
  6.2% until 3050 then resume 3.3%" for ANTRI 2D/LANHI 2D; "MNM 4.6% until
  3050 then resume 3.3%" plus runway-specific PDG values for the other chart)
  as a `climb_gradient` object on the SID, not discarded as a comment.
- `coordination_required: true` for **ANTRI 2D** and **KADUM 2D** only —
  confirm against each chart's usage-condition box, they're stated
  independently on the two charts.

### 3.4 STARs (`56080.pdf`, `56084.pdf`, `56090.pdf` → 6 files)

STARs run inbound (opposite direction convention from SIDs — first leg is
furthest from the airport, last leg terminates at a holding fix or IAF-handoff
point). For each STAR capture:

- Ordered fix sequence with, at each fix that has one, an **altitude
  constraint** (`AT 2150` = cross at exactly; a plain number under a fix like
  `3650` next to `MAX`/`HP` box = holding-pattern ceiling, not a crossing
  restriction — keep these distinct fields) and a **speed constraint** where
  printed (e.g. `MAX 425 km/h`, `MAX 460 km/h` — these vary per leg, don't
  apply one global speed to the whole STAR).
- The **holding pattern** at the STAR's terminus fix: inbound course, max
  holding altitude, max speed — as its own `holding_pattern` object, not
  folded into the leg list.
- The **generic IAS step-down block** printed on `56080.pdf`/`56084.pdf`/
  `56090.pdf` (190–200 kt on base leg or ≤25 NM from threshold; 160–180 kt
  established on final approach course; 150–160 kt at 5 NM from threshold) —
  this applies to *all* STARs into this runway, not just the ones on that
  specific chart page. Store it once, e.g. in `profile.json`, and reference it
  from every STAR rather than repeating it 6 times.
- `coordination_required: true` for **all six** STARs in this pass — every
  one of the three charts states its listed STARs require prior coordination
  with Regional Air Command Centre III. Verify this per chart rather than
  assuming it carries over, since the wording differs slightly per chart.

### 3.5 TMA boundary and profile manifest

- Extract the TMA polygon boundary from `10430.pdf` (the area chart) — this is
  the actual TMA/CTR boundary, **not** the 46 km MSA circle shown on the
  SID/STAR charts, which is a minimum-safe-altitude aid, not an airspace
  boundary. Confirm which is which before encoding — they are easy to
  conflate since both are drawn as circles/arcs near the aerodrome.
- `profile.json` ties everything together:
  ```json
  {
    "id": "tsn_tma",
    "runway_config": ["25L", "25R"],
    "waypoints": "waypoints.json",
    "sids": ["sids/ac_1r.json", "..."],
    "stars": ["stars/elsas_2h.json", "..."],
    "tma_boundary": "tma_boundary.json",
    "shared": {
      "star_ias_stepdown": { "...": "the block from 3.4" },
      "initial_climb_segments": { "tsn_initial_climb_83847": [...], "tsn_initial_climb_83854": [...] }
    }
  }
  ```

## 4. Schema/engine changes needed (do this after 3, not before)

The route model must support what section 3 captures. Concretely:

1. **Directionality** — add a `direction` field (`"outbound"` for SID,
   `"inbound"` for STAR) so the trajectory engine doesn't treat a SID as
   flyable in reverse or vice versa.
2. **Per-fix constraints** — replace "route = list of coordinates" with
   "route = list of legs, each with an optional altitude constraint (hard /
   ceiling / floor) and optional speed constraint." This is the single biggest
   structural change — touches whatever currently builds a flyable path from
   a route file (likely in `astra/trajectory` and `scenarios/builder`).
3. **Holding patterns** — a new shape type (inbound course + fix + max
   altitude + max speed), consumed by the trajectory engine as a loop rather
   than a terminating leg.
4. **Coordination-required flag** — a boolean the scenario builder can filter
   on (e.g. "exclude coordination-required routes" for a baseline scenario),
   not something the trajectory/complexity engines need to know about at all.
5. **Shared sub-segments** (initial climb) — the route loader needs to resolve
   a `"initial_climb_ref"` into the actual leg list before handing it to the
   trajectory engine; the engine itself should just see one continuous leg
   list, it shouldn't know sharing exists.
6. **`--profile` selection** — `main.py` and the dashboard's scenario loader
   take a profile name and load `profile.json` from
   `scenarios/profiles/<name>/`, replacing whatever currently hardcodes the
   FIR sector/route paths.

## 5. Build order and checkpoints

1. `waypoints.json` — check: 149 entries, spot-checked (3.1).
2. **One** conventional SID end-to-end (`BACHU1R`, arbitrary but simple pick)
   — check: file matches the chart text exactly, someone who didn't read the
   chart could re-derive the flown path from the JSON alone.
3. **One** RNAV SID end-to-end (`SAPEN2D`, includes the shared initial-climb
   test case) — check: initial-climb reference resolves, altitude/speed
   constraints match the chart, climb-gradient note captured.
4. **One** STAR end-to-end (`SAPEN2H`, pairs naturally with SAPEN2D) — check:
   direction is inbound, holding pattern present, IAS step-down referenced
   not duplicated.
5. Schema/engine changes from section 4, built against just these 3 procedures
   — check: a scenario with one departing aircraft on SAPEN2D and one arriving
   aircraft on SAPEN2H runs through the full pipeline (trajectory → hotspot →
   complexity → tracking → forecast → resolution) without errors and produces
   sane output.
6. Only once step 5 passes: transcribe the remaining 10 conventional SIDs, 7
   RNAV SIDs, and 5 STARs the same way.
7. TMA boundary + `profile.json` + `--profile` wiring.
8. Full regression: existing `hcm_fir` demo scenarios (`nominal`, `crosstrack`,
   `arrival45`) still run unchanged with `--profile hcm_fir` (or the default,
   if that's how it's wired) — this profile change must be provably
   zero-impact on existing behavior.

## 6. Explicit non-goals this pass

- No RWY 07 configuration (no source charts).
- No approach/missed-approach modeling (`10453.pdf` stays unused this pass).
- No changes to `hcm_fir` data or scenarios.
- No new complexity/forecast/resolution *logic* — this is a data-and-schema
  pass. If building this out surfaces a genuine engine gap beyond what's
  listed in section 4, stop and flag it rather than improvising a fix.

## 7. Open items to confirm with the requester before/while building

- Whether `TSC01`–`TSC04` (4 unnamed entries in the waypoint list, distinct
  from the `TS###` sequence fixes) are used by any of these procedures or
  belong to the approach chart instead — they don't appear on the SID/STAR
  charts reviewed so far.
- Whether "25L" vs "25R" ever changes which SID/STAR legs apply (some
  conventional SID text says "RWY 25L/R" generically; the RNAV climb-gradient
  box gives separate PDG values per runway) — confirm both runways truly share
  one procedure set with only the gradient numbers differing, versus needing
  two full sets of files.
