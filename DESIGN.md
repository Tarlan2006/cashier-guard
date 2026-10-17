---
name: Cashier Guard
description: Light slate and rose workspace for reviewing cash-desk video evidence.
colors:
  accent: "#db2777"
  accent-hover: "#be185d"
  accent-soft: "#fdf2f8"
  canvas: "#f8fafc"
  surface: "#fff"
  ink: "#0f172a"
  body: "#1e293b"
  muted: "#64748b"
  line: "#e2e8f0"
  control-line: "#cbd5e1"
  neutral-ink: "#475569"
  neutral-bg: "#f1f5f9"
  strong-ink: "#9f1239"
  strong-bg: "#fff1f2"
  review-ink: "#92400e"
  review-bg: "#fffbeb"
  clear-ink: "#065f46"
  clear-bg: "#ecfdf5"
typography:
  headline:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "25px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.025em"
  panel-title:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "15px"
    fontWeight: 750
    letterSpacing: "-0.015em"
  explanation:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.8
  supporting:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "13px"
    lineHeight: 1.8
  button:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "12px"
    fontWeight: 650
    lineHeight: 1.5
  input:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
rounded:
  badge: "6px"
  navigation-item: "8px"
  control: "10px"
  inset: "12px"
  panel: "16px"
spacing:
  compact: "8px"
  control: "12px"
  inset: "16px"
  panel: "20px"
  desktop-gutter: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.line}"
    textColor: "{colors.neutral-ink}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "#334155"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  button-dark:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.input}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  navigation-selected:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.accent-hover}"
    rounded: "{rounded.navigation-item}"
    padding: "7px 12px"
  assessment-strong:
    backgroundColor: "{colors.strong-bg}"
    textColor: "{colors.strong-ink}"
    rounded: "{rounded.badge}"
    padding: "3px 6px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "20px"
---

# Design System: Cashier Guard

## Overview

**Creative North Star: "User-supplied light review console"**

The implemented interface follows the user's complete JSX reference: a cool slate canvas, white rounded work surfaces, rose primary actions and a dark navy video surface. The Cashier Guard name and existing evidence workflow remain. This records the shipped CSS cascade rather than the reference's demo content.

Compact controls and fine dividers keep the workspace dense without giving status color the same meaning as the brand accent. The header uses horizontal section navigation; local video and returned evidence are the visual content. The previous green rail and Manrope identity are superseded by the user's approved reference.

**Key Characteristics:**
- Cool slate surroundings and softly elevated white panels.
- Rose actions, a rose-gradient Eye mark and dark video surfaces.
- Written assessment labels with distinct red, amber and green semantics.
- Responsive horizontal-header shell with stacked work areas on mobile.

## Colors

### Primary
Rose identifies primary actions, selected navigation, links, timecode actions, keyboard focus and the brand wordmark accent. The Eye mark uses a restrained diagonal rose gradient. Pale rose supports rule references and selected affordances.

### Secondary
Red, amber and green identify strong evidence, human review and clear assessments respectively. Neutral slate identifies incomplete or unknown states. These are labelled semantic states, not interchangeable brand accents.

### Neutral
Cool slate canvas surrounds white panels. Deep slate carries headings and doubles as the dark media/API surface; muted slate carries supporting copy. Fine pale slate borders separate controls and cards.

**The Written Status Rule.** Every assessment color accompanies a written label and an icon; never infer a conclusion from color alone.

## Typography

The source uses the system sans-serif stack requested by the supplied `font-sans` reference. There is no separately loaded display font. The root size is 16px; actual component roles are explicit in the frontmatter. Platform rendering can vary.

The page headline steps to 23px on mobile. Panel headings step to 14px; section-introduction headings use 21px. Summary titles are 17px/1.6, stepping to 16px on mobile. Explanatory copy is generally 13–14px with generous leading. Main analysis action text is 14px; the key input stays 16px. Timestamps and file metadata use tabular numerals. Small metadata captions (11–12px) do not establish a body-text standard. API JSON uses the browser monospace treatment.

## Layout

The sticky top header and main region share a centered 1280px maximum width. Desktop horizontal gutters are 24px. The main region starts with a breadcrumb, compact task heading and upload toolbar; availability or a completed assessment occupies a separate row above the workspace. The desktop workspace uses a 7:5 grid with a 20px gap. Panels use 20px padding. Upload and results remain in normal document flow.

At 1024px the header may wrap and the workspace shifts to a 1.15:1 ratio. At 760px the header navigation becomes a two-column grid, main gutters become 16px, work panels stack with an 18px gap, and panel padding becomes 17px. Breadcrumb text truncates when necessary. Long filenames truncate in the toolbar while detailed file information remains in the upload area. Secondary sections use the same shell: sources, actual JSON and processing architecture. Switching sections preserves the current local video.

## Elevation & Depth

Fine borders, tonal surfaces and very small ambient shadows define ordinary panels. The sticky white header is slightly translucent with a 14px backdrop blur. The Eye mark has a small rose shadow. The modal frame viewer uses pronounced depth and a blurred dark backdrop; it is the elevated inspection surface.

### Shadow Vocabulary
- **Panel separation** (`0 1px 2px #0f172a04`): toolbar and primary work panels.
- **Selected navigation** (`0 1px 2px #0f172a08`): white current-section item.
- **Brand mark** (`0 3px 8px #db277720`): rose Eye square.
- **Evidence dialog** (`0 16px 60px #0f172a40`): modal frame inspection.

## Shapes

Work panels, summary banners and the frame dialog use the broad panel radius. Fields and buttons use tighter control corners; navigation items and small semantic badges are tighter again. The upload target is a rounded dark rectangle with a dashed outline. Video and evidence containers clip actual media without inventing imagery. Circular stage/status markers remain native to the processing and timeline components.

## Components

### Buttons
Primary rose controls have white text, a 38px minimum desktop height and 42px minimum mobile height. Standard padding and typography are recorded in the frontmatter. The full-width analysis action is at least 44px high and appears after a file is selected. Secondary controls are white with a fine border; the JSON action is dark slate. Hover changes background over 150ms ease-out. Disabled primary controls use neutral colors; disabled secondary controls reduce opacity.

### Inputs / Fields
The key field has a fine control border, control radius, 16px entry text and a visibility icon. Its grouped focus outline is 2px pale rose with a 2px offset. Other interactive elements have a 3px rose keyboard outline with a 4px offset. Upload uses the dark dashed target, with a lighter navy fill and pink border on hover or drag. The selected file and its actual preview replace the empty upload content.

### Navigation
Labelled icon buttons sit in a pale slate rounded track. The current section is white with deep rose text, a border and subtle shadow; hover adds a slate fill. Mobile uses a two-column grid rather than removing labels. `aria-current` identifies the active section.

### Chips
Assessment badges use labelled red, amber, green or neutral tonal pairs, a small radius and inline SVG icon. They are semantic annotations. Current-event selection uses matching assessment color. Legacy demo records retain explicit written demo markers; no demo-launcher or connectivity badge belongs in the header.

### Cards / Containers
White panels use the shared broad radius, fine border and restrained depth. The upload toolbar is a shallow horizontal panel. Result lists use bordered inset cards, selected assessment tones and compact timecodes. Evidence uses a two-column image grid, with a single image spanning the available width. Rule references use pale rose fill and an outline. The source/API/architecture sections reuse these surfaces; API output sits on dark slate.

### Video timeline and evidence inspection
Native video remains muted and inline. Millisecond timecode buttons, keyboard range input and labelled event markers select the same event. Evidence-image controls open the native modal frame viewer, with fit/2× inspection, scrolling and explicit close. Focus stays inside the modal and returns to the opening control. The dialog is at most 1100px/94vw, changing to 96vw on mobile; media inspection stays within the viewport.

### Processing and motion
Processing uses the existing 1.3s linear spinner and 2.2s scan with `cubic-bezier(0.16, 1, 0.3, 1)`. Controls use brief background feedback. Reduced-motion preference effectively disables CSS motion and chooses automatic JavaScript scrolling. It does not suppress explicitly requested video playback. State changes retain live announcements and alert semantics.

## Do's and Don'ts

### Do:
- **Do** use the rose action palette and cool slate/white surfaces from the implemented reference.
- **Do** retain written assessment labels, explicit demo markers for restored records, visible focus and reduced-motion behavior.
- **Do** align the header and main content to the same container and preserve readable stacked mobile panels.
- **Do** use actual local video and returned evidence, including tabular timecodes.

### Don't:
- **Don't** communicate an assessment through color alone or turn an error into a clear verdict.
- **Don't** restore the removed header health indicator or separate demo-launch controls.
- **Don't** import synthetic evidence, invented statistics or fabricated legal claims from the visual reference.
- **Don't** treat 11px metadata as the default size for explanatory copy.
