# Centrifugal pump: source and changes to the CAD model

The pump is the GrabCAD model "Single stage centrifugal pump" by D. Rehere (2018): https://grabcad.com/library/single-stage-centrifugal-pump-3 (CATIA V5 export `final assembly.stp`, 6 Nov 2018). The GrabCAD terms of use (§6.2) allow other users' uploads only for their own non-commercial, internal use, so this repository does not include the STEP file. It includes the product file `centrifugal_pump_product.json`: parts, contact matrix, fastener groups, connections and transitions of the reworked model, enough to build the knowledge graph without the CAD file.

To run the pipeline from CAD, download the model from GrabCAD, apply the changes below, and save it as `centrifugal_pump.stp` in this folder.

## Changes (reworked model against the GrabCAD file)

Measured part by part with Open CASCADE: volume, position and shape of each of the 25 parts, and the shared volume of every pair of parts. Coordinates in mm; y is the shaft axis, +y points towards the suction nozzle. 16 parts are unchanged: the gasket, the suction nozzle, the six M20 and four M12 bolts, both bearings, the coupling and bearing end cap 1.

**Overlaps removed.** In the GrabCAD file ten pairs of parts share volume. In the reworked model no pair shares more than 0.01 mm³.

| Pair in the GrabCAD file | Shared volume | Change |
|---|---:|---|
| volute casing cover / volute casing | 186,198 mm³ | spigot of the cover turned down from Ø280 to Ø265 over 36 mm |
| volute casing cover / gasket | 32,103 mm³ | same change |
| each M20 bolt / volute casing (6 pairs) | 4,449 mm³ each | six holes for the M20 bolts in the volute casing |
| shaft / impeller | 14,789 mm³ | shaft shoulder reduced from Ø50 to Ø20 over 8.97 mm at the impeller seat |
| bearing housing / bearing 40x50 | 1,209 mm³ | bore of the bearing housing widened from Ø80.0 to Ø80.4 |

**Gaps at the contact threshold closed.** Two pairs are exactly 0.5 mm apart in the GrabCAD file. The pipeline counts a contact below 0.5 mm, so these pairs do not count as contacts there. In the reworked model they touch.

| Pair | Change |
|---|---|
| stuffing box gland halves / shaft | bore of the gland halves from Ø51 to Ø50 |
| bearing 59x70 / bearing housing | bore of the bearing housing from Ø101 to Ø100 |

**Impeller and cap nut.**
- The impeller touches the volute casing in the GrabCAD file. In the reworked model it is moved 0.6 mm towards the suction side and is 0.6 mm away from the volute casing. It is also turned by about 8° about the shaft axis; this has no effect, the vanes repeat every 45°.
- The cap nut sits 2.97 mm in front of the impeller hub in the GrabCAD file. In the reworked model it rests against the hub: it is 2.37 mm further towards the drive side, with a deeper thread bore, and the thread end of the shaft is 8 mm shorter.

**Other changes.**
- Bearing housing: bore on the casing side widened from Ø160 to Ø185 over 25 mm (the gland halves have an outer diameter of 160 mm).
- Bearing end cap 2: a ring of 2.1 mm (331 mm³) removed on the housing side.
- Volute casing cover: holes of the M12 bolts reworked; the bolts touch the cover in the GrabCAD file and are 0.05 mm away in the reworked model.

**Part names.**

| GrabCAD file | Reworked model |
|---|---|
| BEARING HOUSING | Bearing Housing |
| stuffing box gland upper (both halves) | Stuffing Box Gland Half_1, Stuffing Box Gland Half_2 |
| shaft | Shaft |
| volute casing | Volute Casing |
| impeller | Impeller |
| m20 capnut | M20 Cap Nut |
| volute casing gasket | Volute Casing Gasket |
| volute casing cover | Volute Casing Cover |
| suction nozzel | Suction Nozzle |
| m20 *2.5 (six) | M20x2.5 Hex Bolt_1 to _6 |
| m 12 flange (four) | M12 Flange Bolt_1 to _4 |
| bearing size 40 50 | Bearing 40x50 |
| bearing size 59 70 | Bearing 59x70 |
| Bearing housing end cap 2 | Bearing End Cap 2 |
| Bearing house end cap | Bearing End Cap 1 |
| coupling | Coupling |

## Result

With these changes the pipeline finds 48 contacts. With the ten bolts in two groups and the cap nut as a part, held by the rule that shaft and impeller stay together while it is in place, it generates 40 connections, 102 assembly states and 340 transitions.
