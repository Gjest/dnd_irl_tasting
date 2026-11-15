"""Reads rows of the TASTINGS table straight out of an H2 MVStore file.

Values use H2's ValueDataType encoding: 0x20-0x2f small ints, 0x05 long +
varlong, 0x44+n short strings, 0x0b timestamp (date varlong, millis varlong,
nanos varint). Long strings and other tags are detected and reported.
"""
import json, sys
from collections import Counter

COLUMNS = ["id", "adventurer_name", "bitterness", "body", "carbonation", "clarity", "color", "created_at",
           "duration", "harmony", "mineral_intensity", "notes", "odor", "personal_enjoyment", "ph_sensation",
           "salinity", "sweetness", "temperature", "water_sample_id"]
unknown = Counter()

def varint(b, i):
    value = shift = 0
    while True:
        byte = b[i]; i += 1
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, i
        shift += 7

def chars(b, i, n):
    # H2 writes Java chars in a UTF-8-like form, one char at a time.
    out = []
    for _ in range(n):
        c = b[i]
        if c < 0x80:
            out.append(chr(c)); i += 1
        elif c < 0xe0:
            out.append(chr(((c & 0x1f) << 6) | (b[i+1] & 0x3f))); i += 2
        else:
            out.append(chr(((c & 0x0f) << 12) | ((b[i+1] & 0x3f) << 6) | (b[i+2] & 0x3f))); i += 3
    return "".join(out), i

def value(b, i):
    tag = b[i]; i += 1
    if 0x20 <= tag <= 0x2f:
        return tag - 0x20, i
    if tag == 0x05:
        return varint(b, i)
    if tag == 0x04:
        return varint(b, i)
    if 0x44 <= tag <= 0x63:
        return chars(b, i, tag - 0x44)
    if tag == 0x0b:
        date, i = varint(b, i); millis, i = varint(b, i); nanos, i = varint(b, i)
        y, m, d = date >> 9, (date >> 5) & 15, date & 31
        s = millis // 1000
        return f"{y:04d}-{m:02d}-{d:02d}T{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}", i
    if tag == 0x0d:  # long string: varint length, then chars
        n, i = varint(b, i)
        return chars(b, i, n)
    if tag == 0x00:
        return None, i
    unknown[tag] += 1
    raise ValueError(f"tag {tag:#x}")

def rows(data):
    found = {}
    for start in range(len(data)):
        if data[start] != 0x05:
            continue
        try:
            i, row = start, {}
            for col in COLUMNS:
                row[col], i = value(data, i)
        except (ValueError, IndexError):
            continue
        ints = [row[c] for c in COLUMNS if c not in ("id", "adventurer_name", "created_at", "notes", "water_sample_id")]
        if not all(isinstance(v, int) and 1 <= v <= 5 for v in ints):
            continue
        if not (isinstance(row["adventurer_name"], str) and isinstance(row["water_sample_id"], str) and str(row["created_at"]).startswith("20")):
            continue
        if row["id"] in found and found[row["id"]] != row:
            print("CONFLICT", row["id"], found[row["id"]], row, file=sys.stderr)
        found[row["id"]] = row
    return [found[k] for k in sorted(found)]

data = open(sys.argv[1], "rb").read()
result = rows(data)
print(len(result), "rows; unknown tags tried:", dict(unknown), file=sys.stderr)
json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
