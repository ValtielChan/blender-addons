# Curve Railing Generator

Génère une barrière (rambarde + barreaux) le long d'un tracé, avec une tessellation **adaptative à la courbure** : de la géométrie dans les virages, presque rien sur les parties droites.

Deux façons de tracer, détectées automatiquement d'après le type de spline :

- **Points de contrôle** (courbe POLY, ou Bézier à poignées Vector) — le mode recommandé pour une rambarde. Tu poses juste des points « la rampe va de là à là, puis change de direction », et chaque angle est arrondi tout seul par un **arc de cercle** du rayon demandé. Aucune poignée, aucun poids à gérer.
- **Courbe de Bézier** — pour les tracés vraiment courbes (circuit, rampe hélicoïdale). La courbe est échantillonnée dense puis simplifiée par déviation angulaire.

- Auteur : Muware
- Version : 1.2.0
- Blender : 4.5.0+
- Catégorie : Add Mesh
- Emplacement : View3D > Sidebar (N) > Railing
- Fichier : `curve_railing_generator.py`

## Utilisation

1. Panneau *Railing* > **New Railing Path** : crée un tracé à 2 points au curseur 3D + sa barrière, et te dépose en Edit Mode sur le tracé, dernier point sélectionné.
2. **E** pour extruder le point suivant, autant de fois que nécessaire. Chaque angle s'arrondit automatiquement.
3. Régler les paramètres dans le panneau, ça se régénère en direct.

Le panneau reste utilisable pendant l'édition du tracé : sélectionner la courbe affiche les réglages de sa barrière. Bouton **Edit Path** pour y retourner depuis la barrière.

**Freeze** coupe le lien avec le générateur : le mesh est conservé tel quel, il cesse de suivre son tracé et l'add-on ne le reconnaît plus. C'est un aller simple (Ctrl+Z pour revenir en arrière), les paramètres sont perdus. Le tracé n'est pas supprimé — s'il ne sert plus à rien, le message d'info te le signale et tu le supprimes toi-même.

Pour partir d'une courbe existante : la sélectionner, puis **From Active Curve**.

La courbe donne la **ligne de base** (au sol) : la rambarde est posée à `Height` au-dessus, les barreaux montent du sol jusqu'à l'axe de la rambarde.

Les paramètres sont stockés **sur l'objet** : chaque barrière garde ses propres réglages, et Shift+D donne une copie éditable indépendamment.

Avec **Live Update** actif, la barrière se régénère aussi bien sur changement de paramètre que pendant l'édition de la courbe : déplacer un point de contrôle en Edit Mode met la barrière à jour en direct (handler `depsgraph_update_post`). Le bouton **Rebuild** reste là pour forcer une reconstruction.

## Paramètres

**Rambarde** — hauteur de l'axe, rayon du tube, résolution radiale, et nombre de lisses horizontales (`Rails` > 1 ajoute des lisses réparties entre le sol et la hauteur).

**Barreaux** — espacement cible (ajusté pour tomber juste sur la longueur de la courbe), rayon, résolution radiale, et `Sink` pour les enfoncer sous le sol.

**Optimization** — le cœur de l'add-on :
- `Max Deviation` : le budget angulaire d'une section de rambarde. C'est le seul réglage qui compte vraiment : plus bas = virages plus lisses et plus de triangles.
- `Corner Radius` (mode points de contrôle) : rayon de l'arc qui arrondit chaque angle. Réduit automatiquement sur un angle dont les segments voisins sont trop courts, pour que deux congés ne se chevauchent jamais. À 0, les angles restent vifs.
- `Max Section` (mode courbe) : longueur maxi d'une section en ligne droite. Ne sert qu'à empêcher une ligne parfaitement droite de devenir une seule arête gigantesque.

Le second réglage affiché dépend du mode détecté — l'autre serait inerte.

**Result** — triangles, sommets, et le nombre de sections retenues sur le nombre de points échantillonnés (le taux de compression).

Ordres de grandeur mesurés :

| Tracé | Sections | Triangles |
|---|---|---|
| L en angle droit, angles vifs (`Corner Radius` 0) | 4 | 320 |
| Idem, congés 0.6 m à 8° | 28 | 684 |
| Idem à 3° | 64 | 1260 |
| Bézier « long droit + virage 90° », adaptatif 8° | 16 | 472 |
| Le même Bézier à résolution uniforme équivalente | 161 | 2792 |

## Détails d'implémentation

- Mode points de contrôle : chaque angle devient un **vrai arc de cercle** (pas une approximation de Bézier), découpé en `ceil(angle / Max Deviation)` segments. Le congé produit donc directement la bonne densité, il n'y a pas d'étape de simplification derrière qui la dégraderait.
- Mode courbe : échantillonnage dense (64 points par segment de Bézier) puis simplification en accumulant l'angle de rotation — le résultat ne dépend pas de la densité d'échantillonnage, seulement de la géométrie réelle.
- Repère « up fixe » pour le balayage du tube (pas de transport parallèle) : pas de vrille accumulée, et une rambarde est de toute façon toujours à l'endroit.
- Tubes en quads lissés, bouchons en n-gons plats : le flat/smooth par face suffit, pas besoin d'auto-smooth ni de modifier.
- Splines cycliques gérées (rambarde fermée, sans bouchons).
- Le mesh est réécrit en place (`clear_geometry` + `from_pydata`) plutôt que remplacé : pas de création/suppression de datablock depuis un handler depsgraph, et c'est plus rapide.
- La courbe est lue depuis sa copie évaluée, donc les modifiers de la courbe et l'état d'Edit Mode sont pris en compte (repli sur les données d'origine si la courbe a un bevel, car elle s'évalue alors en mesh).
- Les splines NURBS sont traitées comme des points de contrôle (congés), pas évaluées en tant que NURBS.

## Installation
Edit > Preferences > Add-ons > Install, sélectionner `curve_railing_generator.py`, puis activer.

---

## Aperçu

![Rambarde générée](../docs/media/curve-railing-generator/hero.png)

`Max Deviation` de 20° à 2° — la densité va dans le congé, pas dans les lignes droites :

![Max Deviation](../docs/media/curve-railing-generator/deviation.gif)

`Corner Radius` de 0 à 1,6 m :

![Corner Radius](../docs/media/curve-railing-generator/corner.gif)

[Guide illustré complet](../docs/GUIDE.md#2-curve-railing-generator)
