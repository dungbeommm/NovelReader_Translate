---
name: NovelReader
description: A monochrome workspace for Chinese–Vietnamese translation and audio.
colors:
  bg: "#080b0d"
  panel: "#0e1215"
  panel-hover: "#181d22"
  raised: "#151a1f"
  raised-hover: "#22282e"
  alt: "#11161a"
  border: "#30373e"
  border-subtle: "#252c32"
  text: "#f2f3f5"
  text-muted: "#a9b0b8"
  accent: "#f2f3f5"
  accent-hover: "#ffffff"
  accent-soft: "#20262b"
  accent-border: "#626c76"
  primary-bg: "#f4f5f6"
  primary-ink: "#111417"
  selection: "#20262c"
  danger: "#ffb1b8"
  danger-soft: "#3b131b"
  warning: "#eac682"
  warning-soft: "#302719"
  light-bg: "#f1f2f3"
  light-panel: "#ffffff"
  light-panel-hover: "#eceef0"
  light-raised: "#f4f5f6"
  light-raised-hover: "#e7e9ec"
  light-alt: "#f8f9fa"
  light-border: "#cbd0d6"
  light-border-subtle: "#dfe2e6"
  light-text: "#161b20"
  light-text-muted: "#555f6b"
  light-accent: "#252d35"
  light-accent-hover: "#101417"
  light-accent-soft: "#e6e9ed"
  light-accent-border: "#858e98"
  light-primary-bg: "#161b20"
  light-primary-ink: "#ffffff"
  light-selection: "#e9ecf0"
  light-danger: "#a9182c"
  light-danger-soft: "#ffedf0"
  light-warning: "#815400"
  light-warning-soft: "#fff6dc"
typography:
  headline:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.4
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "14px"
    lineHeight: 1.55
  label:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
  data:
    fontFamily: "'JetBrains Mono', Consolas, monospace"
    fontSize: "11px"
    lineHeight: 1.8
rounded:
  control: "8px"
  panel: "12px"
  chapter: "7px"
  count: "20px"
spacing:
  compact: "8px"
  field: "12px"
  group: "16px"
  panel: "18px"
  page: "24px"
  tool: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary-bg}"
    textColor: "{colors.primary-ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-destructive:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
  count:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.count}"
    padding: "4px 10px"
  navigation-active:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  chapter-selected:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.chapter}"
    padding: "8px"
---

# Design System: NovelReader

## Overview

**Creative North Star: "Bàn dịch truyện"**

A dark, task-focused translation workspace. The user-supplied reference establishes near-black surfaces, fine gray borders, bright text and white primary actions across every page. Density serves practical work: restrained headings, compact labels and clear groups keep long chapter lists and configuration readable.

The default is dark. A monochrome light companion preserves the same hierarchy and component geometry. The previous green theme is retired. This document records the implemented system; the surface brief owns the translation page's specific composition.

**Key Characteristics:**

- Near-black canvas with subtly separated charcoal surfaces.
- White primary actions; red destructive actions and errors.
- Inter for interface text; JetBrains Mono for data and logs.
- Thin borders, gently rounded controls and contextual disclosure.

## Colors

The palette is neutral and low-saturation. Frontmatter records the actual dark and light values; `web/static/workspace.css` applies them through semantic CSS variables and is loaded after the base styles.

### Primary

The bright primary surface and dark primary ink identify actions such as starting a translation and exporting a file. The light theme reverses this relationship with a dark action surface and white ink. Accent also supplies focus outlines, checkboxes and progress fill.

### Neutral

Canvas, panel, raised and alternate surfaces distinguish nesting without broad decorative contrast. Main text carries task content; muted text carries help, metadata and secondary navigation. Standard borders define controls; subtle borders divide containers. Selection is a distinct neutral surface, reinforced by an outline where needed.

Danger and danger-soft are the red foreground/surface pair for deletion and errors. Warning and warning-soft support cautionary status; neither becomes an application accent. Light-prefixed tokens mirror the same roles under the light theme.

**The Monochrome Rule.** Keep navigation, progress and routine actions neutral in both themes. Do not reintroduce the retired green palette.

## Typography

Inter is the workhorse interface family, with system sans fallbacks. JetBrains Mono, with Consolas and monospace fallbacks, is reserved for chapter numbers, numeric telemetry and event logs. There is no separate decorative display face.

The frontmatter headline role captures the source title. Other page and reader headings use nearby sizes and weights; section titles use the title role. Body copy remains compact, labels step down for supporting information, and the main shell uses tabular numerals. Reader prose has a user-adjustable size, initially (17px), and spacious line height (1.95).

**The Data Type Rule.** Use mono to distinguish data and logs; retain sans for navigation, forms and explanatory copy.

## Layout

The shared desktop shell has a navigation rail (216px), an optional collapsed rail (72px), and a header (60px). Content occupies the remaining viewport. Pages scroll inside the workspace instead of extending the entire shell.

Reusable panels group related controls, typically with panel spacing and gaps (16–18px). The translation studio has an observed content maximum (1700px); full-page tools use a narrower maximum (1120px). Tool forms and reader views retain the same shell and materials. Advanced controls open within their relevant group.

The studio's three-column arrangement becomes two columns at widths (901–1350px). At (900px) and below, navigation becomes a drawer (248px), and configuration and progress precede the chapter list. At (600px) and below, the studio stacks configuration, progress and chapters vertically, and secondary form grids also stack. Compact page padding and wrapping action rows protect field width.

## Elevation & Depth

Depth comes primarily from tonal layers and thin borders. Buttons and main panels have no resting shadow; tool pages remove the old modal-style shadow. Dialog backdrops dim the shell. Floating notices retain a small shadow (`0 8px 24px #0004`); existing overlay cards may retain stronger shadows. Do not spread overlay elevation to routine panels.

## Shapes

Controls have gently curved corners using the control radius; panels use the larger panel radius. Chapter rows have their own compact radius. Count badges are capsules. Thin borders (1px) keep groups legible without heavy frames. The source upload target uses a dashed border to distinguish the drop affordance. Icons are restrained outline SVGs, generally (18px) in navigation.

## Components

### Buttons

Primary buttons use the high-contrast primary surface/ink pair. Secondary buttons use raised surfaces and standard borders. Destructive buttons pair red text with a soft red surface. Standard controls have a minimum height (40px); compact actions and the main start action use their observed local sizes. Hover raises secondary surfaces and brightens borders; primary hover reduces opacity (.88). Disabled buttons reduce opacity (.45).

### Inputs / Fields

Inputs, selects and textareas use the canvas surface, standard border and control radius. Fields have a minimum height (40px) and concise muted placeholders. Select options follow the panel palette. Focus-visible uses an accent outline (2px) with an offset (3px), rather than a glow. Checkboxes, radios and range controls inherit the neutral accent.

### Cards / Containers

Panels use the panel surface, subtle borders and panel radius. Setup groups, progress and chapter containers share this treatment. Nested help uses alternate surfaces and quieter text. Disclosure summaries stay plainly clickable; expanded content remains part of the enclosing group.

### Navigation

Navigation uses compact labels, outline icons and muted inactive text. Hover adds a raised surface. The active item uses selection fill and a standard border with bright text. The collapsed desktop rail retains icon access; the mobile drawer includes a dismissing scrim.

### Count Badges

Count capsules use a raised fill, subtle border and compact sans text. Counts remain readable metadata rather than accent-colored decorations.

### Chapter Rows and Progress

Chapter rows align number, title and status. The selected row combines a raised fill with a bright outline. Status circles distinguish pending, completed and active work, while error text uses danger. Do not rely on color alone.

The progress bar has a neutral track and accent fill. Event logs pair muted timestamps with actual received task updates; the idle log presents an explicit empty message. Do not add decorative or fabricated activity.

## Do's and Don'ts

### Do:

- **Do** reuse the shared semantic variables in both themes.
- **Do** use white primary actions in dark mode and the reversed light-mode pair.
- **Do** preserve visible focus outlines and text labels for status.
- **Do** keep advanced controls near the task they configure.
- **Do** use real progress and event data, with honest empty states.

### Don't:

- **Don't** restore green navigation, progress or action styling.
- **Don't** use mono as the general interface font.
- **Don't** add gradients or routine card shadows to this flat workspace.
- **Don't** introduce a separate palette for a tool page or dialog.

