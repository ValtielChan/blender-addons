# Stair Generator

Generates a solid, manifold, optimized staircase (quads everywhere except the two side n-gons,
no duplicate vertices, no interior faces).

- Author: Valtiel
- Version: 1.0.0
- Blender: 4.5.0+
- Category: Add Mesh
- Location: View3D > Sidebar (N) > **Stairs**
- File: `stair_generator.py`
- Origin: Blender 4.5

## Usage

Settings are stored **on the object**, not on the scene: every staircase keeps its own.

- No staircase selected → the panel only offers **New Staircase** (created at the 3D cursor,
  then selected and made active).
- A staircase selected → the panel edits that one, and only that one.
- Regenerating preserves location, rotation, scale, parenting and modifiers: place first,
  adjust later.
- Shift+D duplicates a staircase that stays independently editable.

## Parameters

- **Total height** and **width** of the staircase.
- **Steps**: driven either by a target riser height (the step count is rounded so it lands
  exactly) or by a direct step count.
- **Depth**: tread depth given directly, or derived from the slope angle.
- *Result* panel: the values actually built (step count, riser, going, angle, length) plus a
  Blondel comfort check (2h + g = 60–64 cm).

No arbitrary limits: only geometrically absurd values are rejected (zero or negative
dimensions, an angle of 0° or 90°).

## Installation

Edit > Preferences > Add-ons > Install, pick `stair_generator.py`, then enable it.

---

## Preview

<p align="center">
  <img src="../docs/media/stair-generator/angle.gif" width="49%" alt="Slope angle">
  <img src="../docs/media/stair-generator/steps.gif" width="49%" alt="Riser height">
</p>
<p align="center">
  <img src="../docs/media/stair-generator/hero.png" width="32%" alt="Generated staircase">
  <img src="../docs/media/stair-generator/topology.png" width="32%" alt="Topology">
  <img src="../docs/media/stair-generator/panel.png" width="32%" alt="Panel">
</p>

15 steps = 64 vertices, 34 faces, 32 of them quads.

[Full illustrated guide](../docs/GUIDE.md#1-stair-generator)
