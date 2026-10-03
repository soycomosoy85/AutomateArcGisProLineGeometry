"""Read-only OGR diagnostic for the WCAXY placement examples."""
import os
os.environ.setdefault("GDAL_PAM_PROXY_DIR", os.environ.get("TEMP", "."))
import json
import math
from pathlib import Path
from osgeo import ogr, osr

ogr.UseExceptions()
ROOT = Path(__file__).resolve().parent.parent
source = ogr.Open(str(ROOT / "Gdb/Well_Inventory_Template.gdb"), 0)
output = ogr.Open(str(ROOT / "Gdb/WellInventory.gdb"), 0)
out = output.GetLayerByName("WellSticks")
target = out.GetSpatialRef().Clone()
target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
units = 0.3048 / target.GetLinearUnits()


def projected(layer, feature):
    sr = layer.GetSpatialRef().Clone()
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    geom = feature.GetGeometryRef().Clone()
    geom.Transform(osr.CoordinateTransformation(sr, target))
    geom.FlattenTo2D()
    return geom


def points(geom):
    if geom.GetGeometryCount():
        for child in geom:
            yield from points(child)
    else:
        yield from geom.GetPoints()


def lines(geom):
    if geom.GetGeometryType() == ogr.wkbLineString:
        yield geom
    else:
        for child in geom:
            yield from lines(child)


wells = source.GetLayerByName("Well_Constraints")
wells.SetAttributeFilter("GUGG_BENCH = 'WCAXY'")
constraints = [(f.GetField("API_UWI"), projected(wells, f)) for f in wells]
dsus = source.GetLayerByName("DSUs")
dsus.SetAttributeFilter("DSU_ID IN ('DSU-ID-093', 'DSU-ID-094', 'DSU-ID-095')")
report = []
for feature in dsus:
    dsu_id = feature.GetField("DSU_ID")
    polygon = projected(dsus, feature)
    inset = polygon.Buffer(-140 * units)
    origin = inset.Centroid().GetPoint()
    az = math.radians(feature.GetField("AZIMUTH"))
    direction, normal = (math.sin(az), math.cos(az)), (math.cos(az), -math.sin(az))
    coords = [(p[0] - origin[0], p[1] - origin[1]) for p in points(inset)]
    along = [x * direction[0] + y * direction[1] for x, y in coords]
    across = [x * normal[0] + y * normal[1] for x, y in coords]
    spacing_ft = feature.GetField("WCAXY_Spacing")
    spacing = spacing_ft * units
    maximum = feature.GetField("DSU_Length") * units
    count = math.floor((max(across) - min(across)) / spacing) + 1
    start = (min(across) + max(across) - (count - 1) * spacing) / 2
    candidates = []
    nearby = [(api, g) for api, g in constraints if g.Distance(polygon) < spacing]
    for index in range(count):
        offset = start + index * spacing
        line = ogr.Geometry(ogr.wkbLineString)
        for t in [min(along) - spacing, max(along) + spacing]:
            line.AddPoint_2D(origin[0] + t * direction[0] + offset * normal[0],
                             origin[1] + t * direction[1] + offset * normal[1])
        for stick in lines(line.Intersection(inset)):
            length = stick.Length()
            if length <= 0.001:
                continue
            if length > maximum:
                first, last = stick.GetPoint(0), stick.GetPoint(stick.GetPointCount() - 1)
                fraction = (length - maximum) / (2 * length)
                shortened = ogr.Geometry(ogr.wkbLineString)
                for factor in [fraction, 1 - fraction]:
                    shortened.AddPoint_2D(first[0] + factor * (last[0] - first[0]),
                                         first[1] + factor * (last[1] - first[1]))
                stick = shortened
            distances = sorted((stick.Distance(g) / units, str(api), g.Intersects(polygon)) for api, g in nearby)
            candidates.append({"lane": index + 1, "lengthFt": round(stick.Length() / units, 1),
                               "nearestWells": [(round(d, 1), api, bool(inside)) for d, api, inside in distances[:3]],
                               "passesFull": not distances or distances[0][0] >= spacing_ft,
                               "passesHalf": not distances or distances[0][0] >= spacing_ft / 2})
    out.SetAttributeFilter("DSU_ID = '{}' AND BENCH = 'WCAXY'".format(dsu_id))
    report.append({"dsu": dsu_id, "spacingFt": spacing_ft, "azimuth": feature.GetField("AZIMUTH"),
                   "actualOutputCount": out.GetFeatureCount(), "candidates": candidates})
print(json.dumps(report, indent=2))
