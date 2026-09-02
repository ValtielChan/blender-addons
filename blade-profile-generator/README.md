# Blade Profile Generator

Génère une lame d'épée à partir d'un profil de largeur : des jalons (position, largeur) le long de la lame, interpolés linéairement, avec la pointe automatiquement ramenée à 0. Gère aussi l'émouture (tranchant) et la gorge (fuller) sur les deux faces.

## Utilisation

View3D > Sidebar (N) > onglet **Blade**.

- **Length / Thickness** : longueur totale et épaisseur (constante) de la lame.
- **Width Profile** : liste de jalons `(position, largeur)`. Exemple : à 0 cm → 4,5 cm, à 20 cm → 4,4 cm, à 60 cm → 3,8 cm. La largeur est interpolée linéairement entre les jalons.
- La pointe (à `Length`) est toujours à largeur 0 — pas besoin de jalon final.
- Sans jalon à la position 0, la largeur du premier jalon est prolongée jusqu'à la base.
- **Live Update** : régénère à chaque changement de paramètre.

### Émouture (Edge Grind)

- **Grind Width** : largeur de l'émouture **à la base**, mesurée depuis le tranchant vers l'intérieur. Le biseau va de la pleine épaisseur à 0 au tranchant (lame affûtée). L'émouture est proportionnelle : le méplat central reste une fraction constante de la largeur locale de la lame, donc l'émouture suit le rétrécissement du profil. `0` = chant rectangulaire non affûté.
- **Join At** : distance depuis la garde où l'émouture rejoint le centre. Le méplat proportionnel est en plus refermé progressivement jusqu'à 0 à ce point, puis la section est un losange plein jusqu'à la pointe. `0` = le méplat suit la largeur jusqu'au bout et la jonction se fait à la pointe.

### Fuller (gorge)

- **Start / Length** : d'où part la gorge et sur quelle longueur.
- **Width / Depth** : largeur (centrée) et profondeur par face. Creusée systématiquement sur les deux faces, profondeur bornée sous la demi-épaisseur.
- **Fade** : longueur de la sortie arrondie aux deux extrémités.
- **Segments** : résolution de l'arc.
- La section de la gorge est un arc de cercle (rayon d'outil constant déduit de largeur/profondeur). Aux extrémités, la profondeur diminue et la largeur de coupe suit le même arc — comme une fraise ronde qu'on relève — d'où un contour de sortie arrondi. Les faces de l'arc sont lissées (shade smooth), le reste à facettes.
- Si la gorge est plus large que le méplat restant, elle est bornée au méplat ; l'émouture s'arrête au bord de la gorge.

La lame est générée le long de +Z (largeur sur X, épaisseur sur Y), origine à la base. Deux jalons à la même position créent un décroché net (utile pour un ricasso).

## Notes

- L'épaisseur reste constante jusqu'à la pointe (la pointe est une arête, pas un point).

Blender 4.5.0+

---

## Aperçu

![Lame générée](../docs/media/blade-profile-generator/hero.png)

Sortie de gorge et ligne d'émouture :

![Détail](../docs/media/blade-profile-generator/detail.png)

Profondeur de gorge, largeur d'émouture, profil de largeur :

![Gorge](../docs/media/blade-profile-generator/fuller.gif)
![Émouture](../docs/media/blade-profile-generator/grind.gif)
![Profil](../docs/media/blade-profile-generator/profile.gif)

[Guide illustré complet](../docs/GUIDE.md#6-blade-profile-generator)
