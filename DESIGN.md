---
name: Cashier Guard
description: Calm daytime workspace for reviewing cash-desk recordings.
colors:
  green: "#245d4e"
  green-hover: "#194736"
  navigation: "#173d36"
  navigation-selected: "#31564a"
  ink: "#232c29"
  muted: "#69716b"
  canvas: "#f5f6f3"
  surface: "#fff"
  line: "#e2e6df"
  focus: "#7cae96"
  demo-background: "#f4ebda"
  demo-text: "#785320"
  attention-background: "#faf1df"
  attention-text: "#81581e"
  clear-background: "#edf5e9"
  clear-text: "#305d3c"
  error: "#983c2b"
  disabled-background: "#dce4d9"
  disabled-text: "#5c6b58"
typography:
  headline:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "34px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.035em"
  title:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "17px"
    fontWeight: 750
    letterSpacing: "-0.02em"
  state-title:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "17px"
    fontWeight: 650
  body:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "15px"
    fontWeight: 450
    lineHeight: 1.7
  label:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "14px"
    fontWeight: 650
  button:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "14px"
    fontWeight: 650
rounded:
  badge: "4px"
  inset: "5px"
  control: "7px"
  content: "8px"
  upload: "9px"
  panel: "14px"
spacing:
  icon: "6px"
  compact: "10px"
  control: "12px"
  inset: "16px"
  mobile-gutter: "20px"
  workspace-gap: "22px"
  panel: "20px"
  section: "24px"
  desktop-gutter: "44px"
components:
  button-primary:
    backgroundColor: "{colors.green}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "11px 16px"
  button-primary-hover:
    backgroundColor: "{colors.green-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.disabled-background}"
    textColor: "{colors.disabled-text}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "11px 16px"
  button-text:
    textColor: "{colors.green}"
    padding: "3px 0"
  button-icon:
    rounded: "{rounded.inset}"
    width: "36px"
    height: "36px"
  input:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  navigation-selected:
    backgroundColor: "{colors.navigation-selected}"
    textColor: "{colors.surface}"
    rounded: "{rounded.content}"
    padding: "13px 15px"
  demo-tag:
    textColor: "{colors.demo-text}"
    rounded: "{rounded.badge}"
    padding: "4px 6px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "20px"
---

# Design System: Cashier Guard

## Overview

**Creative North Star: "Calm daytime review desk"**

This records the implemented review workspace: deep green navigation, warm near-white surroundings, white work panels, and restrained status colors. Values come from the current App, components, hooks and final CSS cascade. No approved concept image or screenshot approval is implied.

The input area is compact while evidence and explanatory text remain readable. Evidence, status, and controls share locally bundled Manrope and consistent Lucide SVG icons. Current-job recovery, explicit demo scenarios and recoverable failures are part of the same page; color supports written meaning.

**Key Characteristics:**
- Deep green navigation with quiet white work surfaces.
- Readable explanation text, fine borders, and gently rounded controls.
- Written status labels and actual video evidence.

## Colors

### Primary
Green marks actions, selected events, links, and timestamps. Deep navigation green anchors the surrounding shell; its lighter selected tone identifies the current destination.

### Secondary
Amber tones distinguish demo notices and possible events. Pale green identifies a clear result; rust red identifies errors. These are semantic status treatments, not decorative accents.

### Neutral
Ink carries primary copy, muted gray-green carries supporting copy, and the warm canvas separates white panels. Fine neutral lines divide work areas and evidence rows. The frontmatter records the recurring palette; isolated illustration tints remain implementation details.

**The Written Status Rule.** Pair status color with a written label and the corresponding icon or indicator.

## Typography

**Body and heading font:** locally bundled Manrope Variable, with sans-serif fallback. No separate display face is used.

The frontmatter gives desktop roles: 34px page headline, 17px panel title, 15px body and 14px labels/buttons. Evidence descriptions use 16px/1.75; introductory, processing and failure explanations generally use 15px, increasing to 16px on mobile. Supporting metadata is generally 12–13px. Key entry is 16px on all sizes; the scenario select is 14px on desktop and 16px on mobile. Panel titles remain 17px. The page headline steps to 31px at 1200px and 28px at 720px. Timestamps and file metadata use tabular numerals; `MM:SS.mmm` preserves fractional seconds. Small legacy captions are not the body-text standard.

## Layout

The desktop shell uses a sticky full-height 244px navigation rail, a 64px topbar, and a centered main region capped at 1436px. Main padding is 24px at the top and 44px horizontally. Two work areas use a 0.92:1.12 column ratio and 22px gap; panel padding is 20px. The upload target has a 164px minimum height. The 46px primary action sits immediately below the upload-panel heading, in normal document flow with an 18px bottom margin, 16px bottom padding and a separating border. It does not overlay the video or timeline. This makes the initial action easy to find without shrinking explanatory text.

At 1200px the rail narrows to 210px, main gutters to 28px, and columns approach equality with a 16px gap. At 980px navigation becomes a 76px icon rail and the gap is 18px. At 720px it becomes a 61px top strip with a 48px topbar; work areas stack in document order with a 20px gap. Mobile main gutters/top padding and panel padding are 20px; the upload target is at least 180px high. The explanatory grid becomes one column. Current final overrides keep compact sizing even above 1600px; the earlier large-screen rules do not determine the shipped layout.

## Elevation & Depth

Work panels use fine borders and tonal separation. The evidence dialog alone uses a strong elevation shadow (`0 16px 60px #071d2d45`) and a dark green backdrop (`#10231ecc`). Keyboard focus uses a green outline: 3px with 4px offset globally, 2px with 2px offset around the key field, and 3px with 3px offset on the scenario select. Evidence-image buttons use a 4px inset outline. Legacy segmented-control CSS remains in the stylesheet but no longer corresponds to a rendered control.

**The Flat Panel Rule.** Separate work panels with surface color and a fine border; reserve pronounced elevation and the backdrop for modal evidence viewing.

## Shapes

Panels have the broadest corners; controls use tighter corners and evidence containers sit between them. Upload targets use a dashed border. Circular geometry belongs to status markers, stage numbers, and the empty-state illustration. Evidence and video containers clip media while retaining its aspect ratio.

## Components

### Buttons
Primary actions use green and white, secondary actions use white with a neutral border, text actions are green and underline on hover, and icon actions use a quiet hover fill. Standard buttons have a 43px minimum height, increasing to 46px on mobile; the main analysis action is 46px throughout. Button text is 14px. Icon targets are at least 36px and the mobile dialog close target is 44px. Background transitions last 150ms with ease-out. Disabled primary buttons use the explicit muted palette; disabled secondary and icon buttons reduce opacity.

### Chips
The demo tag is a small outlined status annotation inside the amber notice; it is hidden at 1200px and below while the written notice remains visible. It is not an interactive filter.

### Cards / Containers
White work panels share the 14px panel radius, line border, and 20px padding. Results contain a written verdict, selectable event rows, 1–3 evidence images, millisecond timecode actions and a separated rule reference. Long event names and file names wrap. Demo sources are explicitly fictional and are not rendered as authoritative external links. Completed results can be downloaded as JSON and show their expiry time; expandable stage timings remain secondary information.

### Inputs / Fields
The key field uses a thin neutral border and grouped focus outline, with a visibility button at least 36px wide. Auth failure restores editability and focuses the key field. Demo scenarios use a labelled native select with nine options: one event, no events, multiple events, three frames, long text, fictional source, slow processing, ML error and invalid ML response. The select is at least 44px high. Upload is a keyboard-accessible dashed button whose hover and drag states share a pale green fill and stronger border.

### Current check and recovery

The tab stores the current `job_id` and entered key in sessionStorage; the backend persists statuses and evidence in SQLite. There are no accounts or full history. On reload the result panel shows restoration, then the saved state. A separate restored-file panel explains that the local File/Object URL is gone and offers file reattachment without another analysis. Filename and size checks assist selection but do not verify file contents. Results expire after one hour by default; the backend cleans them periodically. A restart fails unfinished jobs with an explicit restart error and keeps completed results. Readiness and backend connectivity have separate messages. Auth, missing-job, network/timeout and processing errors offer appropriate recovery actions; an error never becomes a clear verdict.

### Video timeline and evidence dialog

The native video player is muted and inline. A keyboard-operable range input uses a 0.001-second step, with numbered event markers and a separate wrapping list of event buttons. Selection seeks the local video and updates the selected event. Context playback starts up to three seconds before the selected event and stops up to three seconds after it, clipped to the video boundaries. Seeking requires a reattached local file and a browser-supported codec; evidence viewing remains available independently.

Each evidence-image button opens a native modal dialog. It shows the frame time, fit/2× controls, a scrollable image viewport and a close button. Opening explicitly focuses the close button; a Tab/Shift+Tab wrap keeps keyboard navigation inside the dialog. Escape and close dismiss it and return focus to the opening control. Width is at most 1100px/94vw, changing to 96vw on mobile; the viewport is capped at 68dvh or 60dvh on mobile. Zoom changes image width to 200% for inspection, without animated scaling.

### Navigation
Navigation uses a green rail with a lighter selected item and visible hover feedback. Labels collapse at the tablet breakpoint and the shell becomes a compact top strip on mobile. Keep accessible names when visible labels disappear.

### Processing and motion
Processing shows server stages, a 1.3s linear spinner, and a 2.2s scan with `cubic-bezier(0.16, 1, 0.3, 1)`. Status text is announced through a polite live region; failures use alerts. Reduced-motion preference disables CSS animations/transitions, and JavaScript scrolling chooses automatic rather than smooth behavior through `scrollBehavior()`. Reduced motion does not disable user-requested video playback.

## Do's and Don'ts

### Do:
- **Do** preserve explicit demo and human-review language in status treatments.
- **Do** retain visible keyboard focus and reduced-motion behavior.
- **Do** use tabular numerals for timestamps and file metadata.
- **Do** keep restoration, file reattachment, expiry and error recovery understandable on the same page.

### Don't:
- **Don't** communicate a verdict through color alone.
- **Don't** replace actual evidence frames with decorative imagery.
- **Don't** infer a general display-text style from the smallest metadata captions.
- **Don't** equate a reachable ML port with verified inference, or imply public deployment from configuration files.
