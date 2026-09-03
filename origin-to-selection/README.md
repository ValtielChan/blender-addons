# Origin to Selection

A Blender extension that puts the active object's origin (pivot point) at the center of the
current edit-mode selection, without moving the geometry. One shortcut replaces the manual
cursor + snap + origin-to-cursor sequence.

- Maintainer: Fabien
- Version: 1.0.0
- Blender: 4.2.0+ (tested on 5.1)
- Type: extension (add-on), `blender_manifest.toml`
- Category: Mesh

## Shortcut

`Ctrl + Alt + C` in mesh edit mode.

The operator is also available from the right-click menu in the 3D view (edit-mode context
menu), under "Origin to Selection".

## Usage

1. Enter edit mode on a mesh.
2. Select one or more vertices, edges or faces.
3. Press `Ctrl + Alt + C`.

The object origin moves to the center of the selection. The geometry does not move, and the 3D
cursor is restored to where it was.

## What the operator does internally

Saves the 3D cursor, snaps the cursor to the selection, switches to object mode with the active
object isolated, runs `origin_set` on the cursor, returns to edit mode, then restores both the
cursor and the selection.

## Installation

In Blender 5.1: Edit > Preferences > Add-ons > arrow at the top right > Install from Disk, then
pick `origin-to-selection.zip`. Enable the extension if it is not already.

## Changing the shortcut

Edit > Preferences > Keymap, search for "Origin to Selection", or right-click the context-menu
entry > Assign Shortcut / Change Shortcut.

---

## Preview

<p align="center">
  <img src="../docs/media/origin-to-selection/demo.gif" width="49%" alt="Demo">
  <img src="../docs/media/origin-to-selection/compare.png" width="49%" alt="Before / after">
</p>

On the left the origin sits at the object center; after `Ctrl+Alt+C` it sits on the selected
face, and everything that follows pivots around that point.

[Full illustrated guide](../docs/GUIDE.md#7-origin-to-selection)
