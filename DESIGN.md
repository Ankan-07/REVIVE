---
name: Revenue Rescue Engine (REVIVE)
description: Autonomous AI agent revenue recovery system dashboard
colors:
  primary: "#4f46e5"
  neutral-bg: "#020617"
  panel-bg: "#0f172a"
  border: "#1e293b"
  text-primary: "#f1f5f9"
  text-secondary: "#94a3b8"
  success: "#34d399"
  warning: "#fbbf24"
  danger: "#fb7185"
typography:
  display:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
  body:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
  label:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
rounded:
  md: "6px"
  lg: "8px"
  xl: "12px"
  2xl: "16px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  tab-active:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "6px 16px"
  tab-inactive:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.md}"
    padding: "6px 16px"
  badge-success:
    backgroundColor: "rgba(52, 211, 153, 0.1)"
    textColor: "{colors.success}"
    rounded: "{rounded.md}"
    padding: "4px 10px"
---

# Design System: Revenue Rescue Engine (REVIVE)

## Overview

**Creative North Star: "The Tactical Command Center"**

The interface is an action-oriented, urgent, and utility-focused environment. It leans on high contrast against a deep slate background to surface critical anomalies and financial risk instantly. The aesthetic philosophy is purely functional—every pixel must justify its existence by either surfacing data or enabling an intervention. Extraneous decoration is rejected in favor of raw data density and crisp readability.

**Key Characteristics:**
- Deep slate environment with high-contrast data points.
- Flat and structural, relying on borders rather than shadows for separation.
- Status-driven color palette (emerald, amber, rose) applied sparingly but forcefully.
- Urgent but analytical tone.

## Colors

The palette is anchored in deep slate to reduce eye strain during extended monitoring, with highly saturated functional colors reserved strictly for status and actions.

### Primary
- **Tactical Indigo** (#4f46e5): Used exclusively for active navigation states, primary buttons, and system-level actions.

### Neutral
- **Deep Slate Base** (#020617): The foundational background color.
- **Panel Slate** (#0f172a): Used for secondary surfaces, cards, and distinct content areas.
- **Border Slate** (#1e293b): Used to structurally separate elements without relying on elevation.
- **Text Primary** (#f1f5f9): High-contrast white/slate for primary data and headers.
- **Text Secondary** (#94a3b8): Muted slate for metadata, labels, and secondary information.

### Status (Secondary)
- **Status Success** (#34d399): Health checks passing, revenue recovered.
- **Status Warning** (#fbbf24): Risks identified, pending actions.
- **Status Danger** (#fb7185): Failures, system downtime, critical revenue loss.

### Named Rules
**The Status Exclusivity Rule.** Emerald, Amber, and Rose are reserved strictly for system state and financial outcomes. They must never be used for decoration or general branding.

## Typography

**Display Font:** System UI (Inter/San Francisco/Roboto)
**Body Font:** System UI (Inter/San Francisco/Roboto)
**Label/Mono Font:** System UI

**Character:** Utilitarian, fast, and neutral. The typography steps out of the way to let the data speak.

### Hierarchy
- **Display** (700, 1.125rem): Top-level dashboard headers and primary metrics.
- **Body** (400, 0.875rem): Standard table data, paragraphs, and descriptions.
- **Label** (500, 0.75rem, uppercase where necessary): Metadata, badges, and secondary table headers.

## Layout

The layout prioritizes data density and horizontal rhythm. 
- Global padding relies on standard `24px` (`p-6`) for page containers.
- Content is organized into discrete panels separated by strict `1px` borders.
- Navigation is sticky to ensure operators always have access to top-level contexts.

## Elevation & Depth

The system uses a strictly flat and structural approach. Shadows are heavily minimized.

### Named Rules
**The Border Over Shadow Rule.** Panels and cards are defined by a `1px` border (Border Slate, #1e293b) rather than a box-shadow. Elevation is expressed through subtle background lightness shifts (from Base to Panel Slate), not vertical lift.

## Shapes

Corners are intentionally crisp but softened just enough to feel modern. 
- Small interactive elements (buttons, tabs, badges) use `rounded-md` (6px).
- Containers and major panels use `rounded-xl` (12px) to `rounded-2xl` (16px).
- Harsh 90-degree angles are avoided, but circular borders are rejected for data elements.

## Components

### Navigation Tabs
- **Shape:** 6px radius (`rounded-md`).
- **Active:** Tactical Indigo background with bright white text.
- **Inactive:** Transparent background with Text Secondary, transitioning on hover.

### Status Badges
- **Shape:** 6px radius (`rounded-md`).
- **Style:** 10% opacity background of the status color, with a 20% opacity border of the same color, and full-opacity text (e.g. Success badge uses emerald tones).
- **Typography:** Label hierarchy, often accompanied by a small 14px icon.

### Panels & Cards
- **Corner Style:** 12px to 16px radius (`rounded-xl` or `2xl`).
- **Background:** Panel Slate (#0f172a), often with a slight backdrop blur if overlaid.
- **Border:** 1px solid Border Slate (#1e293b).
- **Shadow Strategy:** Flat. Zero shadow.

## Do's and Don'ts

### Do:
- **Do** use strict `1px` borders (`border-slate-800`) to separate dense data fields.
- **Do** rely on the Text Secondary color (`#94a3b8`) to de-emphasize less critical metadata.
- **Do** keep components flat.

### Don't:
- **Don't** use drop shadows to separate cards from the background.
- **Don't** use the primary Indigo color for success states; reserve it for navigation and primary actions.
- **Don't** mix multiple fonts. Stick strictly to the system sans-serif stack.
