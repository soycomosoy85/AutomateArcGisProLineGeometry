"""ArcGIS Pro Python toolbox. All distances in input attributes are feet.

Add this file using Catalog > Toolboxes > Add Toolbox. No extensions required.
The reference LTD feature class is never read or copied.
"""
import math
import os
from collections import Counter, defaultdict

import arcpy


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Gdb", "Well_Inventory_Template.gdb")
FOOT_METERS = 0.3048


def bench_fields(names):
    """Map both B_1BS_Spacing and 1BS_Spacing to 1BS."""
    result = {}
    for name in names:
        if not name.lower().endswith("_spacing"):
            continue
        bench = name[:-8].upper()
        if bench.startswith("B_"):
            bench = bench[2:]
        if not bench or bench in result:
            raise ValueError("Ambiguous bench spacing field: " + name)
        result[bench] = name
    return result


def lane_offsets(low, high, spacing):
    """Center an evenly spaced pattern across the inset polygon's full width."""
    if spacing <= 0 or high < low:
        raise ValueError("Invalid spacing or width")
    count = int(math.floor((high - low) / spacing)) + 1
    if count > 100000:
        raise ValueError("Excessive lane count; check spacing units")
    start = (low + high - (count - 1) * spacing) / 2
    return [start + i * spacing for i in range(count)]


def finite_positive(value):
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def phase_offsets(low, high, spacing, trials):
    """Centered baseline plus a deterministic sampled search over one spacing."""
    yield lane_offsets(low, high, spacing)
    if trials <= 1:
        return
    for i in range(trials):
        start = low + spacing * i / trials
        if start <= high:
            count = int(math.floor((high - start) / spacing)) + 1
            yield [start + k * spacing for k in range(count)]


def merge_intervals(intervals, length):
    """Union conflict lengths so overlapping well buffers are not double counted."""
    merged = []
    for a, b in sorted((max(0.0, min(a, b)), min(length, max(a, b))) for a, b in intervals):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def conflict_decision(length, intervals, allowed_percent, minimum, tolerance):
    """Retain an allowed overlap, otherwise retain the longest conflict-free piece."""
    merged = merge_intervals(intervals, length)
    conflict = sum(b - a for a, b in merged)
    if length <= tolerance or length < minimum:
        return None
    if conflict <= length * allowed_percent / 100 + tolerance:
        return (0.0, length, conflict, False)
    gaps, previous = [], 0.0
    for a, b in merged:
        gaps.append((previous, a))
        previous = b
    gaps.append((previous, length))
    a, b = max(gaps, key=lambda pair: pair[1] - pair[0])
    if b - a <= tolerance or b - a < minimum:
        return None
    return (a, b, 0.0, True)


def fit_constraint(stick, buffers, sr, allowed_percent, minimum, tolerance):
    intervals = []
    for buffer in buffers:
        if not overlaps(stick.extent, buffer.extent, 0):
            continue
        for piece in parts(stick.intersect(buffer, 2), sr):
            intervals.append((stick.measureOnLine(piece.firstPoint),
                              stick.measureOnLine(piece.lastPoint)))
    decision = conflict_decision(stick.length, intervals, allowed_percent, minimum, tolerance)
    if decision is None:
        return None
    start, end, conflict, trimmed = decision
    fitted = stick.segmentAlongLine(start, end, False) if trimmed else stick
    return fitted, conflict, trimmed


def parts(geometry, spatial_reference):
    """Keep disconnected clipped segments separate; never bridge a polygon hole."""
    for part in geometry:
        points = []
        for point in part:
            if point is None:
                if len(points) > 1:
                    yield arcpy.Polyline(arcpy.Array(points), spatial_reference)
                points = []
            else:
                points.append(point)
        if len(points) > 1:
            yield arcpy.Polyline(arcpy.Array(points), spatial_reference)


def overlaps(a, b, margin):
    return not (a.XMax + margin < b.XMin or b.XMax + margin < a.XMin
                or a.YMax + margin < b.YMin or b.YMax + margin < a.YMin)


def projector(dataset, target):
    source = arcpy.Describe(dataset).spatialReference
    if source.name == "Unknown":
        raise ValueError("Input has an unknown coordinate system: " + str(dataset))
    transform = None
    if source.GCS.name != target.GCS.name:
        options = arcpy.ListTransformations(source, target, arcpy.Describe(dataset).extent)
        if not options:
            raise ValueError("No geographic transformation available for " + str(dataset))
        transform = options[0]
        arcpy.AddWarning("Geographic transformation for {}: {}".format(dataset, transform))
    return lambda geometry: geometry.projectAs(target, transform) if transform else geometry.projectAs(target)


TEXT_FIELDS = {
    "WELL_ID": 255, "BENCH": 50, "DSU_ID": 255, "DSU_OP": 255,
    "BASIN": 100, "STATE": 100, "COUNTY": 100, "TCA_Name": 255,
    "GUGG_Bench": 50, "VDEP_INV_BENCH": 50, "VDEP_SRC_BENCH": 50,
    "VDEP_SRC_ID": 255, "INFILL_FLAG": 10, "INFILL_L_ID": 255,
    "INFILL_R_ID": 255,
}
DOUBLE_FIELDS = [
    "DSU_ACRES", "DSU_Width", "WPS", "Spacing", "BufferDist", "DrainDist",
    "VDEP_DIST_FT", "VDEP_THRESH_FT", "VDEP_MULT", "INFILL_L_DIST",
    "INFILL_R_DIST", "INFILL_SPAC",
    "ClearanceFt", "OverlapFt", "OverlapPct", "OverlapLimitPct", "StickLengthFt",
    "LaneOffsetFt",
]
LONG_FIELDS = [
    "AZIMUTH", "DSU_Length", "VR5_UNIT_ID", "VDEP_FLAG", "VDEP_RULE_CNT",
    "VDEP_TESTED", "INFILL_L_CNT", "INFILL_R_CNT", "INFILL_TESTED",
    "ConstraintTrimmed",
]


class Toolbox:
    def __init__(self):
        self.label = "Well Inventory"
        self.alias = "WellInventory"
        self.tools = [BuildWellSticks]


class BuildWellSticks:
    def __init__(self):
        self.label = "Build Well Sticks"
        self.description = (
            "Create bench-specific sticks from DSU spacing fields. Azimuth is clockwise "
            "from GRID north. Searches parallel lane offsets, clips to inset DSUs, caps "
            "at DSU_Length, permits limited same-bench clearance overlap, and trims "
            "larger conflicts. Best layout maximizes total retained lateral length. "
            "Infill/VDEP remain null."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        specs = [
            ("DsuPolygons", "DSU polygons", "GPFeatureLayer", "Required", "Input"),
            ("WellConstraints", "Existing well constraints", "GPFeatureLayer", "Required", "Input"),
            ("OutputSticks", "Output sticks (new file geodatabase feature class)", "DEFeatureClass", "Required", "Output"),
            ("WorkingCoordinateSystem", "Working projected coordinate system (azimuth uses grid north)", "GPSpatialReference", "Required", "Input"),
            ("SetbackFeet", "Boundary setback (feet)", "GPDouble", "Required", "Input"),
            ("MinimumLengthFeet", "Minimum stick length (feet)", "GPDouble", "Required", "Input"),
            ("ClearanceMultiplier", "Existing-well clearance / bench spacing", "GPDouble", "Required", "Input"),
            ("AllowedOverlapPercent", "Maximum stick length inside well clearance areas (%)", "GPDouble", "Required", "Input"),
            ("OffsetTrials", "Lane offset search samples (1 = centered only)", "GPLong", "Required", "Input"),
        ]
        params = [arcpy.Parameter(name=n, displayName=d, datatype=t,
                                 parameterType=r, direction=direction)
                  for n, d, t, r, direction in specs]
        params[0].filter.list = ["Polygon"]
        params[1].filter.list = ["Polyline"]
        params[0].value = os.path.join(SOURCE, "DSUs")
        params[1].value = os.path.join(SOURCE, "Well_Constraints")
        params[2].value = os.path.join(ROOT, "Gdb", "WellInventory.gdb", "WellSticksOptimized")
        params[4].value = 140
        params[5].value = 1000
        params[6].value = 0.5
        params[7].value = 5
        params[8].value = 20
        for p in params[4:6]:
            p.filter.type = "Range"
            p.filter.list = [0, 1000000]
        for p, limits in [(params[6], [0.01, 10]), (params[7], [0, 100]), (params[8], [1, 200])]:
            p.filter.type = "Range"
            p.filter.list = limits
        return params

    def isLicensed(self):
        return True

    def updateMessages(self, parameters):
        for index, required in [(0, ["DSU_ID", "AZIMUTH", "DSU_Length"]),
                                (1, ["GUGG_BENCH"])]:
            p = parameters[index]
            if p.valueAsText and arcpy.Exists(p.valueAsText):
                names = {f.name.upper() for f in arcpy.ListFields(p.valueAsText)}
                missing = [name for name in required if name.upper() not in names]
                if missing:
                    p.setErrorMessage("Missing fields: " + ", ".join(missing))
                if index == 0 and not any(n.endswith("_SPACING") for n in names):
                    p.setErrorMessage("No bench *_Spacing fields found.")
        if parameters[2].valueAsText and arcpy.Exists(parameters[2].valueAsText):
            parameters[2].setErrorMessage("Choose a new output name; existing data will not be overwritten.")

    def execute(self, parameters, messages):
        try:
            self.build(parameters)
        except Exception as exc:
            arcpy.AddError(str(exc))
            raise

    def build(self, parameters):
        dsus, wells, output = [p.valueAsText for p in parameters[:3]]
        sr = arcpy.SpatialReference()
        sr.loadFromString(parameters[3].valueAsText)
        if sr.type != "Projected" or not sr.metersPerUnit:
            raise ValueError("Select a projected coordinate system suitable for the DSUs.")
        units_per_foot = FOOT_METERS / sr.metersPerUnit
        setback_ft = float(parameters[4].value)
        minimum_ft = float(parameters[5].value)
        clearance_multiplier = float(parameters[6].value)
        allowed_overlap = float(parameters[7].value)
        trials = int(parameters[8].value)
        if not math.isfinite(clearance_multiplier) or not 0.01 <= clearance_multiplier <= 10:
            raise ValueError("Clearance multiplier must be between 0.01 and 10.")
        if not math.isfinite(allowed_overlap) or not 0 <= allowed_overlap <= 100:
            raise ValueError("Overlap percent must be between 0 and 100.")
        if not 1 <= trials <= 200:
            raise ValueError("Offset search samples must be between 1 and 200.")
        if not all(math.isfinite(v) and v >= 0 for v in [setback_ft, minimum_ft]):
            raise ValueError("Setback and minimum length must be finite and nonnegative.")
        output = os.path.abspath(output)
        if os.path.commonpath([os.path.normcase(output), os.path.normcase(ROOT)]) != os.path.normcase(ROOT):
            raise ValueError("Save output inside the Well Inventory Automation directory.")
        workspace, name = os.path.split(output)
        if not workspace.lower().endswith(".gdb"):
            raise ValueError("Output must be directly inside a file geodatabase (.gdb).")
        if arcpy.Exists(output):
            raise ValueError("Output already exists. Choose a new name.")
        if arcpy.ValidateTableName(name, workspace if arcpy.Exists(workspace) else os.path.dirname(workspace)) != name:
            raise ValueError("Invalid output feature class name: " + name)

        fields = [f.name for f in arcpy.ListFields(dsus)
                  if f.type not in ("Geometry", "OID", "Blob", "Raster")]
        lookup = {f.upper(): f for f in fields}
        for required in ["DSU_ID", "AZIMUTH", "DSU_LENGTH"]:
            if required not in lookup:
                raise ValueError("Missing DSU field: " + required)
        benches = bench_fields(fields)
        if not benches:
            raise ValueError("No bench spacing fields found.")
        well_fields = {f.name.upper(): f.name for f in arcpy.ListFields(wells)}
        if "GUGG_BENCH" not in well_fields:
            raise ValueError("Well constraints require GUGG_BENCH.")
        project_dsu, project_well = projector(dsus, sr), projector(wells, sr)
        stats = Counter()
        records = []
        seen = set()
        # Validate every selected DSU before creating any output.
        with arcpy.da.SearchCursor(dsus, fields + ["SHAPE@"]) as cursor:
            for values in cursor:
                row = dict(zip(fields, values[:-1]))
                dsu_id = row[lookup["DSU_ID"]]
                if dsu_id is None or not str(dsu_id).strip() or str(dsu_id) in seen:
                    raise ValueError("DSU_ID must be populated and unique: " + str(dsu_id))
                seen.add(str(dsu_id))
                if values[-1] is None or values[-1].pointCount == 0:
                    raise ValueError("Empty DSU geometry: " + str(dsu_id))
                azimuth, maximum = row[lookup["AZIMUTH"]], row[lookup["DSU_LENGTH"]]
                if azimuth is None or not math.isfinite(float(azimuth)) or not 0 <= float(azimuth) <= 360:
                    raise ValueError("Invalid AZIMUTH for " + str(dsu_id))
                if not finite_positive(maximum):
                    raise ValueError("Invalid DSU_Length for " + str(dsu_id))
                for bench, field in benches.items():
                    if row[field] is not None and not finite_positive(row[field]):
                        raise ValueError("Spacing must be positive or null: {} / {}".format(dsu_id, bench))
                records.append((str(dsu_id), row, project_dsu(values[-1])))
        records.sort(key=lambda item: item[0])
        if not records:
            raise ValueError("No DSUs to process. Check layer selections and filters.")

        constraints = defaultdict(list)
        with arcpy.da.SearchCursor(wells, [well_fields["GUGG_BENCH"], "SHAPE@"]) as cursor:
            for bench, geometry in cursor:
                key = str(bench).strip().upper() if bench is not None else ""
                if not key:
                    stats["Existing wells with missing bench (not applied)"] += 1
                    continue
                if key not in benches:
                    continue
                if geometry is None or geometry.pointCount == 0:
                    raise ValueError("An eligible well constraint has empty geometry in bench " + key)
                geometry = project_well(geometry)
                constraints[key].append((geometry, geometry.extent))

        arcpy.AddMessage("Using {}. Azimuth is clockwise from grid north; input distances are feet.".format(sr.name))
        arcpy.AddMessage("Placement: {} offset samples; clearance multiplier {}; overlap limit {}%; minimum {} ft.".format(
            trials, clearance_multiplier, allowed_overlap, minimum_ft))
        if stats["Existing wells with missing bench (not applied)"]:
            arcpy.AddWarning("{} existing wells have no GUGG_BENCH and cannot be matched.".format(
                stats["Existing wells with missing bench (not applied)"]))
        if not arcpy.Exists(workspace):
            os.makedirs(os.path.dirname(workspace), exist_ok=True)
            arcpy.management.CreateFileGDB(os.path.dirname(workspace), os.path.basename(workspace))
        # Build at a unique staging path; expose final name only after success.
        staging = arcpy.CreateUniqueName("WellSticksPending", workspace)
        try:
            with arcpy.EnvManager(outputCoordinateSystem=sr, overwriteOutput=False,
                                  extent=None, outputZFlag="Disabled", outputMFlag="Disabled"):
                arcpy.management.CreateFeatureclass(workspace, os.path.basename(staging),
                                                    "POLYLINE", spatial_reference=sr,
                                                    has_m="DISABLED", has_z="DISABLED")
                for field, length in TEXT_FIELDS.items():
                    arcpy.management.AddField(staging, field, "TEXT", field_length=length, field_is_nullable="NULLABLE")
                for kind, names in [("DOUBLE", DOUBLE_FIELDS), ("LONG", LONG_FIELDS)]:
                    for field in names:
                        arcpy.management.AddField(staging, field, kind, field_is_nullable="NULLABLE")
                out_fields = list(TEXT_FIELDS) + DOUBLE_FIELDS + LONG_FIELDS
                tolerance = max(float(sr.XYTolerance), 1e-8)
                with arcpy.da.InsertCursor(staging, out_fields + ["SHAPE@"], explicit=True) as cursor:
                    for dsu_id, row, polygon in records:
                        arcpy.AddMessage("Processing " + dsu_id)
                        inset = polygon.buffer(-setback_ft * units_per_foot) if setback_ft else polygon
                        if inset is None or inset.pointCount == 0 or inset.area <= 0:
                            stats["DSUs eliminated by setback"] += 1
                            continue
                        az = math.radians(float(row[lookup["AZIMUTH"]]))
                        direction = (math.sin(az), math.cos(az))
                        normal = (math.cos(az), -math.sin(az))
                        origin = inset.centroid
                        along, across = [], []
                        for part in inset:
                            for p in part:
                                if p is not None:
                                    x, y = p.X - origin.X, p.Y - origin.Y
                                    along.append(x * direction[0] + y * direction[1])
                                    across.append(x * normal[0] + y * normal[1])
                        maximum = float(row[lookup["DSU_LENGTH"]]) * units_per_foot
                        for bench, spacing_field in sorted(benches.items()):
                            spacing_ft = row[spacing_field]
                            if spacing_ft is None:
                                stats["Null DSU/bench combinations skipped"] += 1
                                continue
                            spacing = float(spacing_ft) * units_per_foot
                            clearance = spacing * clearance_multiplier
                            local_wells = [g for g, ext in constraints[bench]
                                           if overlaps(inset.extent, ext, clearance)]
                            buffers = [g.buffer(clearance) for g in local_wells]
                            best, best_score = [], None
                            for offsets in phase_offsets(min(across), max(across), spacing, trials):
                                accepted = []
                                for offset in offsets:
                                    endpoints = [arcpy.Point(origin.X + t * direction[0] + offset * normal[0],
                                                             origin.Y + t * direction[1] + offset * normal[1])
                                                 for t in (min(along) - spacing, max(along) + spacing)]
                                    line = arcpy.Polyline(arcpy.Array(endpoints), sr)
                                    clipped = line.intersect(inset, 2)
                                    for stick in parts(clipped, sr):
                                        if stick.length > maximum:
                                            start = (stick.length - maximum) / 2
                                            stick = stick.segmentAlongLine(start, start + maximum, False)
                                        fitted = fit_constraint(stick, buffers, sr, allowed_overlap,
                                                                minimum_ft * units_per_foot, tolerance)
                                        if fitted is not None:
                                            accepted.append((*fitted, offset))
                                # Total useful footage first, count second, less conflict third.
                                # Stable ties retain the centered/earlier layout.
                                score = (round(sum(item[0].length for item in accepted) / units_per_foot, 2),
                                         len(accepted), -sum(item[1] for item in accepted))
                                if best_score is None or score > best_score:
                                    best_score, best = score, accepted
                            arcpy.AddMessage("{} / {}: {} sticks, {:.0f} lateral ft".format(
                                dsu_id, bench, len(best), sum(item[0].length for item in best) / units_per_foot))
                            for stick, conflict, trimmed, offset in best:
                                if stick.length > maximum + tolerance or stick.difference(inset).length > tolerance:
                                    raise ValueError("Geometry validation failed for " + dsu_id)
                                # Recheck final geometry; percentage denominator is final length.
                                checked = fit_constraint(stick, buffers, sr, allowed_overlap,
                                                         minimum_ft * units_per_foot, tolerance)
                                if checked is None or checked[2]:
                                    raise ValueError("Final overlap validation failed for " + dsu_id)
                                conflict = checked[1]
                                stats["Constraint-trimmed output sticks"] += int(trimmed)
                                stats["Output sticks with allowed overlap"] += int(conflict > tolerance)
                                attributes = {field: None for field in out_fields}
                                for field in ["DSU_ID", "DSU_ACRES", "AZIMUTH", "DSU_Length", "DSU_Width",
                                              "DSU_OP", "BASIN", "STATE", "COUNTY"]:
                                    if field.upper() in lookup:
                                        attributes[field] = row[lookup[field.upper()]]
                                stats["Output sticks"] += 1
                                attributes.update(WELL_ID="LTD-ID-{:06d}-{}-{}".format(stats["Output sticks"], dsu_id, bench),
                                                  BENCH=bench, GUGG_Bench=bench, Spacing=spacing_ft,
                                                  ClearanceFt=clearance / units_per_foot,
                                                  OverlapFt=conflict / units_per_foot,
                                                  OverlapPct=100 * conflict / stick.length,
                                                  OverlapLimitPct=allowed_overlap,
                                                  StickLengthFt=stick.length / units_per_foot,
                                                  LaneOffsetFt=offset / units_per_foot,
                                                  ConstraintTrimmed=int(trimmed))
                                prefix = spacing_field[:-8]
                                for suffix, target in [("_WPS", "WPS"), ("_TCA", "TCA_Name")]:
                                    source_field = lookup.get((prefix + suffix).upper())
                                    if source_field:
                                        attributes[target] = row[source_field]
                                # Undefined ancillary fields, including BufferDist/DrainDist,
                                # intentionally remain null; do not infer later business logic.
                                cursor.insertRow([attributes[f] for f in out_fields] + [stick])
                arcpy.management.Rename(staging, output)
        except Exception:
            if arcpy.Exists(staging):
                arcpy.management.Delete(staging)
            raise
        parameters[2].value = output
        for key, count in sorted(stats.items()):
            arcpy.AddMessage("{}: {:,}".format(key, count))
        if not stats["Output sticks"]:
            arcpy.AddWarning("No sticks met the current rules. The output feature class is empty.")
        arcpy.AddMessage("Created " + output)
