WELL INVENTORY TOOLBOX - OPTIMIZED PLACEMENT

In ArcGIS Pro, close the tool pane, refresh WellInventory.pyt in Catalog (or
remove and add it again), then reopen Build Well Sticks to load new parameters.

DEFAULTS
Boundary setback: 140 feet.
Minimum retained stick length: 1,000 feet (editable screening assumption).
Existing-well clearance multiplier: 0.5 times each DSU's bench spacing.
Maximum overlap: 5 percent of the FINAL stick length.
Lane offset samples: 20, plus the original centered layout. Set to 1 for centered
only. More samples improve search resolution but increase runtime.
Output: Gdb/WellInventory.gdb/WellSticksOptimized. Choose a new name on later runs.

Input defaults remain DSUs and Well_Constraints in Well_Inventory_Template.gdb.
Layer selections and definition queries are honored. Clear well selections to
include all constraints. All generated data must stay inside this workspace.
Existing outputs and LTD_Output are never overwritten or copied.

SPATIAL RULES
Select a projected working coordinate system suitable for the DSU locations.
AZIMUTH is clockwise from GRID north: 0=north, 90=east. Output uses that system.
Input spacing, DSU_Length, setbacks and minimum lengths are international feet
(0.3048 meters), converted to map units. Different datums use ArcGIS's first
ranked available transformation, reported in messages for review.

DSU_ID must be populated and unique. DSU_Length caps the lateral length.
All *_Spacing fields are discovered; B_1BS_Spacing maps to 1BS. Null means no
inventory in that DSU/bench. Nonpositive/nonfinite spacing is an input error.
GUGG_BENCH is authoritative, matched after trimming spaces and uppercasing.
Only the same bench constrains a stick. Missing well benches trigger a warning.
The 140-foot boundary inset applies to outside boundaries and polygon holes.

PLACEMENT AND OVERLAP
New lanes remain separated by the FULL bench spacing. The clearance multiplier
only changes the distance to EXISTING wells, including those outside the DSU.
For example, 880-foot spacing and multiplier 0.5 create 440-foot well corridors.
These are round-ended 2D buffers around the full input well geometries.

Overlap means the length of a candidate inside the UNION of same-bench well
corridors, divided by that candidate's final length. It is not the percent of an
existing well within the DSU, not polygon area, and not just exact line-on-line
coincidence. Overlapping buffers count once. All relevant wells count together.
The allowance concerns horizontal geometry only; no separate angle filter or
vertical clearance analysis is applied. An intersection can qualify if its
corridor overlap length satisfies the percentage limit.

A 10,000-foot stick permits at most 500 feet of corridor overlap at 5 percent;
a 2,000-foot stick permits only 100 feet. Round buffer caps also contribute.
Set overlap to 0 for no positive-length corridor overlap (within XY tolerance).
This is an inventory-screening setting, not a determination of drilling safety.

For each sampled lane layout:
1. Clip lanes to the inset polygon without bridging holes/disconnected areas.
2. Cap each segment at DSU_Length, shortening equally at both ends.
3. Keep the capped stick if total corridor overlap is within the allowance.
4. Otherwise retain its single longest continuous conflict-free portion.
5. Omit anything below the minimum length.

The best layout maximizes total retained lateral footage, then stick count,
then minimizes overlap. Stable ties prefer the centered/earlier layout.
This is a sampled offset search, not a guaranteed global optimum. Trimming does
not consume the remaining overlap allowance to extend the retained portion.
No additional end-to-end sticks are packed into unused length. DSUs are handled
independently; overlapping DSUs and spacing between new sticks in different
DSUs are not reconciled.

OUTPUT
DSU attributes, BENCH, GUGG_Bench, Spacing, WPS and TCA_Name come from inputs.
WELL_ID is generated; IDs can change when inputs or parameters change.
INFILL_* and VDEP_* stay null. BufferDist, DrainDist and VR5_UNIT_ID remain null
until their later business rules are defined. Shape_Length uses output map units.
Geometry is 2D; Z and M are not invented.

Review fields added by this revision:
ClearanceFt: actual existing-well clearance distance.
OverlapFt / OverlapPct: measured corridor overlap of the final stick.
OverlapLimitPct: run's permitted overlap percentage.
StickLengthFt: final stick length in feet.
ConstraintTrimmed: 1 if trimmed to avoid a well corridor, otherwise 0.
LaneOffsetFt: signed offset from the inset centroid along the lane normal.

VALIDATION
Fourteen numerical tests cover spacing, phases, bench mapping, union overlap,
percentage thresholds, complete conflicts and minimum-length trimming.
A read-only OGR reconstruction of WCAXY for DSUs 093/094/095 checks containment,
maximum/minimum lengths and overlap. It estimates 5/5/5 sticks with defaults;
DSU 093 includes a short approximately 1,263-foot stick. Increase minimum length
if this does not qualify as useful inventory.
End-to-end ArcPy execution of this revision is still unverified: the development
shell previously could not initialize the ArcGIS license. Test selected DSUs in
licensed ArcGIS Pro, review messages and map geometry, then expand the run.

Esri geometry API reference:
https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/polyline.htm
