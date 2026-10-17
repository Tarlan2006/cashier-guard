# Cashier Guard — API connection settings

Mode: Operate. Ordinary extension of the current slate/rose system, not a visual identity change. The user confirmed on 17 October 2026 that Settings belongs in the existing top navigation.

## Direction contract

THESIS: Keep the video workspace focused on selecting a recording and reviewing actual results. Move credential editing to Settings → API Connection.

OWN-WORLD: Inherit DESIGN.md: centered 1280px shell, white panels on slate, rose action controls, existing system sans and labelled keyboard focus. Reuse the key input group, existing buttons and section introductions.

STORY: Open Settings, enter a key, show/hide if needed, explicitly Save or Delete. The saved value remains in the current tab's existing sessionStorage entry and authorizes the existing requests. Unsaved typing never replaces the saved key.

FIRST VIEWPORT: The existing top navigation gains Settings. Settings contains a compact API Connection form. The video workspace contains no credential field or key-storage explanation; once a file is chosen without a key, the launch area displays the user's exact message and an Open Settings link. Mobile keeps every navigation item labelled and visible.

FORM: No sidebar rebuild (user confirmed top menu). No credential storage migration, new auth mechanism, connectivity badge, demonstration launcher or substitute analysis. A live health/readiness gate remains required independently of the key. Existing restored demo records remain explicitly marked.

## Verification

Check saved and deleted sessionStorage state, masking, unsaved draft isolation, navigation with video preservation, actual X-API-Key authorization after returning, and correction of a rejected key for POST and restored GET. Inspect desktop and mobile captures with synthetic test credentials only.
