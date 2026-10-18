# Cashier Guard — batch uploads, review queue and report

Mode: Operate. Ordinary feature extension of the user-pinned slate/white/rose system in DESIGN.md. Keep top navigation, system sans, labelled native controls, keyboard focus and mobile stacking. No alternate design direction, header backend indicator or demo launcher.

THESIS: Let a reviewer manage several recordings, cancel one on the server, work through undecided events and export an honest record of current evidence and decisions.

OWN-WORLD: Reuse current shell and panel/field/button tokens. A batch is a simple file list before the unchanged player/results. The queue inherits the history filters/list grammar and adds a genuine saved thumbnail and progress. Result tools add PDF, editable tags and an expandable decision log. Navigation padding adapts to eight labelled destinations without clipping.

STORY: Choose four → label → send at most two at once → cancel one accepted job → wait for remaining three → find four history records by tag → open a pending event at its timestamp → save a decision/comment → change it and inspect audit → download PDF → reload/restart and restore. Opening/Next performs no decision mutation or extra analysis. A failed save leaves a recoverable tab draft.

FIRST VIEWPORT: File selection produces a compact list of actual names, sizes, states and Remove/Cancel actions. A clear Start button sends waiting files. Queue begins with period/exact type/tag filters then pending count and saved event rows. Mobile stacks controls and keeps every nav label. PDF and journal stay with the current result, including history-opened results.

TRUTH: Same X-API-Key and existing SQLite events/history/analytics; no second history/review system. New cancellation is durable and blocks late results. Source/model assessment is immutable; human changes append to a journal atomically. Demo records stay visibly marked and excluded from live analytics. Actual rule data only; PDF states missing video/frame/rule and does not check remote source availability. Cyrillic fonts are embedded, page text wraps and frame captions remain with images.

LIFETIME: Existing result/JPEG/review TTL and independent MP4 TTL unchanged. Tags, audit and submission keys cascade with results. PDFs are generated on demand without a stored backend copy. Drafts live in sessionStorage for at most 24h / result expiry, capped at 50. Batch stores IDs/metadata, never local File/JPEG.

QUALITY BAR: Inherit current DESIGN.md's system-sans 16px fields, slate/white panels, rose action/focus, native forms and written status rule. New task states must be explicit and keyboard accessible. No illustrative stats or fabricated legal conclusions.

Verification matrix: batch / queue / decision+PDF+log at 1440 desktop and 390 mobile. Captures top-reset + 2RAF, assert header Y=0/no page overflow; native player is dismissed using its shipped control in form captures. Browser fixtures visibly demo; live count/migration/auth/late-ML/child-process tests are deterministic test fixtures, not model accuracy evidence. PDF checked by text extraction and raster rendering. No new shipping raster assets.

Finish evidence (18 October 2026): reviewer disposition ship for the inherited UI scope, no material fixes; six valid desktop/mobile captures. Detector returned [] once. Documenter preserved DESIGN.md/design.json; the 7px 9px navigation fit adjustment remains local. Backend 224 tests passed; frontend 184 unit tests and production build passed. Full browser run passed 28/30; its two obsolete drop-zone label locators were updated and the focused four-scenario rerun passed 4/4, including the full four-video/cancel/tags/review/audit/PDF/restart path. Native media was hidden through its existing control for decision captures. PDF pages were rendered and inspected; text/image/page assertions include a long Cyrillic fixture. These are deterministic integration/UX fixtures, not real model-accuracy evidence.
