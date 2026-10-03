"""Independent read-only OGR reconstruction; does not replace an ArcPy run."""
import contextlib
import io
import json
import math
with contextlib.redirect_stdout(io.StringIO()):
    import InspectPlacement as data
from TestWellInventory import namespace
from osgeo import ogr


def subline(line, start, end):
    first, last = line.GetPoint(0), line.GetPoint(line.GetPointCount() - 1)
    length = line.Length()
    result = ogr.Geometry(ogr.wkbLineString)
    for distance in (start, end):
        f = distance / length
        result.AddPoint_2D(first[0] + f * (last[0] - first[0]), first[1] + f * (last[1] - first[1]))
    return result


def intervals(line, buffers):
    first, last = line.GetPoint(0), line.GetPoint(line.GetPointCount() - 1)
    dx, dy = last[0] - first[0], last[1] - first[1]
    length = line.Length()
    measure = lambda p: ((p[0] - first[0]) * dx + (p[1] - first[1]) * dy) / length
    result = []
    for buffer in buffers:
        for piece in data.lines(line.Intersection(buffer)):
            if piece.IsEmpty() or piece.GetPointCount() < 2:
                continue
            result.append((measure(piece.GetPoint(0)), measure(piece.GetPoint(piece.GetPointCount() - 1))))
    return result


report = []
data.dsus.ResetReading()
for feature in data.dsus:
    polygon = data.projected(data.dsus, feature)
    inset = polygon.Buffer(-140 * data.units)
    origin = inset.Centroid().GetPoint()
    az = math.radians(feature.GetField("AZIMUTH"))
    direction, normal = (math.sin(az), math.cos(az)), (math.cos(az), -math.sin(az))
    coords = [(p[0] - origin[0], p[1] - origin[1]) for p in data.points(inset)]
    along = [x * direction[0] + y * direction[1] for x, y in coords]
    across = [x * normal[0] + y * normal[1] for x, y in coords]
    spacing = feature.GetField("WCAXY_Spacing") * data.units
    maximum = feature.GetField("DSU_Length") * data.units
    buffers = [g.Buffer(spacing * 0.5, 64) for _, g in data.constraints if g.Distance(inset) < spacing * 0.5]
    best, best_score = [], None
    for offsets in namespace["phase_offsets"](min(across), max(across), spacing, 20):
        accepted = []
        for offset in offsets:
            line = ogr.Geometry(ogr.wkbLineString)
            for t in [min(along) - spacing, max(along) + spacing]:
                line.AddPoint_2D(origin[0] + t * direction[0] + offset * normal[0],
                                 origin[1] + t * direction[1] + offset * normal[1])
            for stick in data.lines(line.Intersection(inset)):
                if stick.IsEmpty() or stick.Length() <= 0.001:
                    continue
                if stick.Length() > maximum:
                    start = (stick.Length() - maximum) / 2
                    stick = subline(stick, start, start + maximum)
                decision = namespace["conflict_decision"](stick.Length(), intervals(stick, buffers),
                                                         5, 1000 * data.units, 0.001)
                if decision:
                    a, b, conflict, trimmed = decision
                    fitted = subline(stick, a, b) if trimmed else stick.Clone()
                    final_intervals = namespace["merge_intervals"](intervals(fitted, buffers), fitted.Length())
                    final_conflict = sum(y - x for x, y in final_intervals)
                    assert final_conflict <= fitted.Length() * 0.05 + 0.01
                    assert fitted.Length() <= maximum + 0.01
                    assert fitted.Length() >= 1000 * data.units - 0.01
                    assert fitted.Difference(inset).Length() < 0.01
                    accepted.append((fitted.Length(), final_conflict, trimmed))
        score = (round(sum(x[0] for x in accepted) / data.units, 2), len(accepted), -sum(x[1] for x in accepted))
        if best_score is None or score > best_score:
            best, best_score = accepted, score
    report.append({"dsu": feature.GetField("DSU_ID"), "sticks": len(best),
                   "totalLengthFt": round(sum(x[0] for x in best) / data.units),
                   "lengthsFt": [round(x[0] / data.units) for x in best],
                   "overlapPct": [round(100 * x[1] / x[0], 2) for x in best],
                   "trimmed": sum(x[2] for x in best)})
print(json.dumps(report, indent=2))
