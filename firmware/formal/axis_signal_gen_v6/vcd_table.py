"""Print selected top-level signals of an SBY trace.vcd as a per-cycle table.

usage: python vcd_table.py trace.vcd sig1 sig2 ...   (names as in sg_v6_formal)
Only rows where some signal changed are printed.
"""
import sys


def parse(path, want):
    ids, vals, rows, t = {}, {}, [], None
    scope = []
    with open(path) as f:
        for line in f:
            tok = line.split()
            if not tok:
                continue
            if tok[0] == "$scope":
                scope.append(tok[2])
            elif tok[0] == "$upscope":
                scope.pop()
            elif tok[0] == "$var" and len(scope) == 1:
                name = tok[4]
                if name in want:
                    ids.setdefault(tok[3], []).append(name)
            elif tok[0].startswith("#"):
                if t is not None:
                    rows.append((t, dict(vals)))
                t = int(tok[0][1:])
            elif tok[0][0] in "01xz" and len(tok) == 1 and tok[0][1:] in ids:
                for n in ids[tok[0][1:]]:
                    vals[n] = tok[0][0]
            elif tok[0][0] == "b" and len(tok) == 2 and tok[1] in ids:
                for n in ids[tok[1]]:
                    v = tok[0][1:]
                    vals[n] = str(int(v, 2)) if set(v) <= {"0", "1"} else v
    if t is not None:
        rows.append((t, dict(vals)))
    return rows


if __name__ == "__main__":
    path, want = sys.argv[1], sys.argv[2:]
    rows = parse(path, set(want))
    print("\t".join(want))
    prev = None
    for _, v in rows:
        cur = [v.get(n, "-") for n in want]
        if cur != prev:
            print("\t".join(cur))
        prev = cur
