# Origin to Selection

Extension Blender qui place l'origine (point de pivot) de l'objet actif au centre de la sélection courante en mode édition, sans déplacer la géométrie. Un seul raccourci remplace l'enchaînement manuel curseur + snap + origin to cursor.

- Maintainer : Fabien
- Version : 1.0.0
- Blender : 4.2.0+ (testé pour 5.1)
- Type : extension (add-on), `blender_manifest.toml`
- Catégorie : Mesh

## Raccourci

`Ctrl + Alt + C` en mode édition mesh.

L'opérateur est aussi accessible par clic droit dans la vue 3D (menu contextuel du mode édition), sous "Origin to Selection".

## Utilisation

1. Passer en mode édition sur un mesh.
2. Sélectionner un ou plusieurs sommets, arêtes ou faces.
3. Presser `Ctrl + Alt + C`.

L'origine de l'objet se place au centre de la sélection. La géométrie ne bouge pas, et le curseur 3D est restauré à sa position d'origine.

## Ce que fait l'opérateur en interne

Sauvegarde du curseur 3D, snap du curseur sur la sélection, passage en mode objet en isolant l'objet actif, `origin_set` sur le curseur, retour en mode édition, restauration du curseur et de la sélection.

## Installation

Dans Blender 5.1 : Edit > Preferences > Add-ons > flèche en haut à droite > Install from Disk, puis sélectionner `origin-to-selection.zip`. Activer l'extension si elle ne l'est pas déjà.

## Changer le raccourci

Edit > Preferences > Keymap, chercher "Origin to Selection", ou clic droit sur l'entrée du menu contextuel > Assign Shortcut / Change Shortcut.

---

## Aperçu

À gauche l'origine au centre de l'objet, à droite après `Ctrl+Alt+C` : elle est sur la face
sélectionnée, et tout ce qui suit pivote autour de ce point.

![Avant / après](../docs/media/origin-to-selection/compare.png)

![Démonstration](../docs/media/origin-to-selection/demo.gif)

[Guide illustré complet](../docs/GUIDE.md#8-origin-to-selection)
