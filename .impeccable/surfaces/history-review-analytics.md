# Cashier Guard — history, human review and analytics

Mode: Operate. Ordinary extension of the current system in DESIGN.md and the user-supplied JSX reference. Keep the existing top navigation, slate canvas, white panels, rose controls and system sans. No new identity, demo launcher or header availability indicator.

## Direction contract

THESIS: Preserve each completed check and its evidence so a reviewer can return, record an explicit decision, and distinguish model findings from human confirmation.

OWN-WORLD: Reuse the 1280px shell, existing labelled navigation, section introductions, panels, native fields, buttons, keyboard focus and mobile stacking. Use text and tabular counts for status; chart bars describe real server aggregates, never invented performance or legal claims.

STORY: Upload four videos through the existing flow; find all four in History; open an older result without POST or inference; inspect its archived MP4 or remaining JPEGs; save one event's decision and optional comment; reload and restore; inspect live-only analytics and drill into an exact event type and period.

FIRST VIEWPORT: History presents name/date/status filters, then results with red/yellow/unreviewed counts, expiry dates and explicit Open/Delete actions. Analytics presents period selection, model totals, human decisions and exact top-three event counts. Mobile keeps labelled navigation and stacks the same controls, without horizontal page overflow. Human decision editing sits below the selected event's unchanged ML explanation.

TRUTH: Shared X-API-Key protects history, reviews and MP4; never place it in URLs. Exact contract type strings determine stable categories, without inferred merging. Demo, failed, processing and explicitly incomplete analyses are excluded from successful analytics. Count events rather than JPEGs. Viewing never confirms events or increases counts. Decisions and comments are stored separately from original ML JSON. Result/JPEG/review TTL defaults to 30 days, MP4 independently to 7 days; show actual issued expiry dates. Quota refuses new data instead of silently discarding valid history.

## Verification evidence

Backend tests exercise SQLite migrations, four live fixture checks and restart, immutable ML payloads, stable IDs, auth, cross-job rejection, deletion, quota, independent expiry and partial model responses. Browser tests use synthetic video with visibly marked demo outcomes; separate test-only SQLite fixtures verify live analytics, exact type grouping, pagination and deletion. No synthetic fixtures ship as production results.

Capture matrix: history list, saved human decision and analytics at desktop 1440px and mobile 390px. Scroll reset and two animation frames precede full-page captures; assert header top alignment and no horizontal page overflow. Archive player is intentionally dismissed using its existing control for decision captures so native media loading chrome cannot obscure the inspected form. No raster assets ship with this extension.

Finish review: ship at the inherited extension scope; all six captures valid, no material fixes. Documenter compared the finished components/CSS with DESIGN.md and design.json and preserved both files: no visual system change. The detector was unavailable because of the session's launcher engine mismatch, so the floor was reviewed manually. Backend suite: 212 tests. Frontend: 177 unit tests and production build. The four-video browser journey also verifies authenticated archive playback/seek, persisted decisions, restart, exact categories, pagination, deletion and no extra analysis POST.
