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
    fontSize: "15px"
    fontWeight: 750
    letterSpacing: "-0.02em"
  state-title:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "17px"
    fontWeight: 650
  body:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "11px"
    fontWeight: 450
    lineHeight: 1.8
  label:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "11px"
    fontWeight: 650
  button:
    fontFamily: '"Manrope Variable", sans-serif'
    fontSize: "12px"
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
  panel: "23px"
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
    width: "32px"
    height: "32px"
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
    padding: "23px"
---

# Design System: Cashier Guard

## Overview

**Creative North Star: "Calm daytime review desk"**

This describes the implemented Operate scaffold: deep green navigation, warm near-white surroundings, white work panels, and restrained status colors. It is a code-led direction recorded after implementation, not an approved concept seed or image comp.

The interface is compact and task-focused. Evidence, status, and controls share locally bundled Manrope and consistent Lucide SVG icons. Demo and possible-event notices remain explicit; color supports their written meaning.

**Key Characteristics:**
- Deep green navigation with quiet white work surfaces.
- Compact typography, fine borders, and gently rounded controls.
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

The hierarchy is compact: page headline, panel title, state title, body, and control label. The frontmatter gives desktop roles; body paragraphs vary between 11px and 13px, with line-height from 1.6 to 1.9 by density. Panel titles return to 15px on mobile. The page headline steps to 31px at 1200px and 28px at 720px. Mobile key entry uses 16px text. Timestamps and file metadata use tabular numerals.

## Layout

The desktop shell uses a sticky full-height 244px navigation rail, a 76px topbar, and a centered main region capped at 1436px. Main padding is 40px vertically at the top and 44px horizontally. Two work areas use a 0.92:1.12 column ratio and 22px gap; panel padding is 23px.

At 1200px the rail narrows to 210px, main gutters to 28px, panel padding to 20px, and columns approach equality. At 980px navigation becomes a 76px icon rail. At 720px it becomes a 61px top strip, work areas stack in document order, main gutters are 20px, and panel padding is 21px. The explanatory grid also becomes one column. At 1600px extra vertical space enlarges the empty work areas. These are observed breakpoints, not an invented spacing scale.

## Elevation & Depth

Panels use fine borders and tonal separation rather than shadows. The selected scenario segment alone uses a shallow shadow (`0 1px 3px #263a2412`). Keyboard focus uses a green outline: 3px with 4px offset globally, 2px with 2px offset around the key field and scenario selection.

**The Flat Panel Rule.** Separate work panels with surface color and a fine border; reserve the existing shallow shadow for the selected scenario segment.

## Shapes

Panels have the broadest corners; controls use tighter corners and evidence containers sit between them. Upload targets use a dashed border. Circular geometry belongs to status markers, stage numbers, and the empty-state illustration. Evidence and video containers clip media while retaining its aspect ratio.

## Components

### Buttons
Primary actions use green and white, secondary actions use white with a neutral border, text actions are green and underline on hover, and icon actions use a quiet hover fill. Standard buttons have a 43px minimum height, increasing to 46px on mobile. Background transitions last 150ms with ease-out. Disabled primary buttons use the explicit muted palette; disabled secondary and icon buttons reduce opacity.

### Chips
The demo tag is a small outlined status annotation inside the amber notice; it is hidden at 1200px and below while the written notice remains visible. It is not an interactive filter.

### Cards / Containers
White work panels share the panel radius, line border, and responsive padding. Results contain a verdict, selectable event rows, actual evidence images, timecode actions, and a separated rule reference. Timestamp actions seek the uploaded video.

### Inputs / Fields
The key field uses a thin neutral border and grouped focus outline, with a 32px visibility button. The scenario control uses native radios beneath two segmented labels; the selected segment is white with a shallow shadow. Upload is a large keyboard-accessible dashed target whose hover and drag states share a pale green fill and stronger border.

### Navigation
Navigation uses a green rail with a lighter selected item and visible hover feedback. Labels collapse at the tablet breakpoint and the shell becomes a compact top strip on mobile. Keep accessible names when visible labels disappear.

### Processing and motion
Processing shows server stages, a 1.3s linear spinner, and a 2.2s scan with `cubic-bezier(0.16, 1, 0.3, 1)`. Reduced-motion preference disables CSS motion; JavaScript scrolling chooses automatic rather than smooth behavior through `scrollBehavior()`.

## Do's and Don'ts

### Do:
- **Do** preserve explicit demo and human-review language in status treatments.
- **Do** retain visible keyboard focus and reduced-motion behavior.
- **Do** use tabular numerals for timestamps and file metadata.

### Don't:
- **Don't** communicate a verdict through color alone.
- **Don't** replace actual evidence frames with decorative imagery.
- **Don't** infer a general display-text style from the smallest metadata captions.
