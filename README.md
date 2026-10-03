# Automate ArcGIS Pro Line Geometry

ArcPy Python toolbox for generating bench-specific well inventory sticks inside DSU polygons.

## Use in ArcGIS Pro

1. Clone or download this repository.
2. Place input data in `Gdb/Well_Inventory_Template.gdb`, or select your own input feature classes in the tool.
3. In Catalog, add `Py/WellInventory.pyt` and open **Build Well Sticks**.
4. Choose a projected coordinate system appropriate for the data. Azimuth uses grid north.
5. Review the parameters and run. Choose a new output feature class name for each run.

The default inputs are `DSUs` and `Well_Constraints`. The default output is `Gdb/WellInventory.gdb/WellSticksOptimized`. Output must remain under the directory containing this repository's `Py` folder. Geodatabases and other source data are not included.

## Default placement rules

- 140-foot boundary setback; maximum length from `DSU_Length`.
- Discover bench-specific `*_Spacing` fields; null spacing skips that DSU/bench.
- Match existing wells by `GUGG_BENCH`.
- Keep full bench spacing between lanes; existing-well clearance defaults to half-spacing.
- Allow up to 5% of the final stick length inside the union of same-bench clearance buffers.
- Trim larger conflicts to the longest clear portion; minimum stick length defaults to 1,000 feet.
- Compare the centered layout with 20 sampled lane offsets, favoring total retained footage.
- Leave infill and VDEP attributes null. Do not read or copy LTD reference features.

All distances supplied as attributes or parameters are feet. See [the full instructions](Py/WellInventoryReadme.txt) for assumptions, output review fields, and limitations.

## Files and validation

- `Py/WellInventory.pyt`: toolbox and generation logic.
- `Py/WellInventoryReadme.txt`: operating instructions.
- `Py/TestWellInventory.py`: 14 numerical tests; run with `python Py/TestWellInventory.py` (no ArcPy required).
- `Py/InspectPlacement.py`: read-only OGR reconstruction of the original WCAXY examples.
- `Py/InspectOptimizedPlacement.py`: read-only OGR checks of revised placement for DSUs 093, 094, and 095.

The diagnostic scripts require GDAL/OGR and the original local datasets, including `Gdb/WellInventory.gdb/WellSticks`. They do not create inventory output. Numerical tests and the independent geometry reconstruction passed locally. End-to-end execution of the revised toolbox still needs verification in licensed ArcGIS Pro.
