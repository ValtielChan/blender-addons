# Stair Generator

Génère un escalier plein, manifold et optimisé (quads partout sauf les deux flancs en n-gons, aucun sommet dupliqué, aucune face interne).

- Auteur : Muware
- Version : 1.0.0
- Blender : 4.5.0+
- Catégorie : Add Mesh
- Emplacement : View3D > Sidebar (N) > Stairs
- Fichier : `stair_generator.py`
- Provenance : Blender 4.5

## Utilisation

Les paramètres sont stockés **sur l'objet**, pas sur la scène : chaque escalier garde ses propres réglages.

- Aucun escalier sélectionné → le panneau ne propose que **New Staircase** (créé au curseur 3D, puis sélectionné et actif).
- Un escalier sélectionné → le panneau édite celui-là, et lui seul.
- Régénérer conserve la position, la rotation, l'échelle, le parentage et les modifiers : on peut placer d'abord, ajuster ensuite.
- Shift+D duplique un escalier qui reste éditable indépendamment.

## Paramètres

- **Hauteur totale** et **largeur** de l'escalier.
- **Marches** : pilotées par hauteur de marche cible (le nombre de marches est arrondi pour tomber juste) ou par nombre direct.
- **Profondeur** : giron direct ou déduit de l'angle de pente.
- Panneau *Result* : valeurs réelles construites (nombre de marches, contremarche, giron, angle, longueur) + vérification de confort Blondel (2h + g = 60–64 cm).

Aucune borne arbitraire : seules les valeurs géométriquement absurdes sont interdites (dimensions nulles ou négatives, angle à 0° ou 90°).

## Installation
Edit > Preferences > Add-ons > Install, sélectionner `stair_generator.py`, puis activer.

---

## Aperçu

![Escalier généré](../docs/media/stair-generator/hero.png)

Angle de pente et hauteur de marche, en direct :

![Angle](../docs/media/stair-generator/angle.gif)
![Marches](../docs/media/stair-generator/steps.gif)

Topologie : 15 marches = 64 sommets, 34 faces dont 32 quads.

![Topologie](../docs/media/stair-generator/topology.png)

[Guide illustré complet](../docs/GUIDE.md#1-stair-generator)
