import math
import re
import hashlib
import psycopg2

BANDS = 8
ROWS_PER_BAND = 4


def shingles(text):
    words = text.split()
    if len(words) < 3:
        return {text}
    return {' '.join(words[i:i+3]) for i in range(len(words)-2)}


def exact_jaccard(a, b):
    sa = shingles(a)
    sb = shingles(b)
    u = sa | sb
    return len(sa & sb) / len(u) if u else 1.0


conn = psycopg2.connect(
    host="postgres",
    port=5432,
    dbname="setubid",
    user="setubid",
    password="setubid"
)

cur = conn.cursor()

cur.execute("""
SELECT lp.notice_id_a, lp.notice_id_b, lp.label,
       a.normalized_text, b.normalized_text,
       a.signature, b.signature
FROM labelled_pairs lp
JOIN notice_signatures a ON a.notice_id = lp.notice_id_a
JOIN notice_signatures b ON b.notice_id = lp.notice_id_b
""")

pairs = cur.fetchall()

# ---------------- B: MINHASH ESTIMATION ERROR ----------------

errors = []
bins = {}

for a, b, label, text_a, text_b, sig_a, sig_b in pairs:

    true_sim = exact_jaccard(text_a, text_b)

    estimated = sum(
        x == y for x, y in zip(sig_a, sig_b)
    ) / len(sig_a)

    error = abs(estimated - true_sim)
    errors.append(error)

    bucket = min(0.9, math.floor(true_sim * 10) / 10)

    if bucket not in bins:
        bins[bucket] = []

    bins[bucket].append((true_sim, estimated))

print()
print("========== SECTION B ==========")
print("MinHash signature size:", len(pairs[0][5]))
print("Pairs measured:", len(errors))
print("Mean absolute error:", round(sum(errors) / len(errors), 4))
print("Maximum absolute error:", round(max(errors), 4))

print()
print("True similarity range")
for k in sorted(bins):
    vals = bins[k]
    mae = sum(abs(x-y) for x,y in vals) / len(vals)
    print(
        f"{k:.1f}-{k+0.1:.1f}:",
        len(vals),
        "pairs, MAE =", round(mae, 4)
    )

# ---------------- C: SURVIVAL VS TRUE SIMILARITY ----------------

curve = {}

for a, b, label, text_a, text_b, sig_a, sig_b in pairs:

    true_sim = exact_jaccard(text_a, text_b)

    cur.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM lsh_buckets x
            JOIN lsh_buckets y
              ON x.band_no = y.band_no
             AND x.bucket_key = y.bucket_key
            WHERE x.notice_id = %s
              AND y.notice_id = %s
        )
    """, (a, b))

    survived = cur.fetchone()[0]

    bucket = min(0.9, math.floor(true_sim * 10) / 10)

    if bucket not in curve:
        curve[bucket] = [0, 0]

    curve[bucket][0] += 1
    curve[bucket][1] += int(survived)

print()
print("========== SECTION C ==========")
print("True similarity -> candidate survival")

for k in sorted(curve):
    total, survived = curve[k]
    print(
        f"{k:.1f}-{k+0.1:.1f}:",
        survived,
        "/",
        total,
        "=",
        round(survived / total, 4)
    )

# ---------------- E: MITIGATION ----------------
# Remove extremely large buckets from candidate retrieval.
# This reduces pathological work while measuring the recall cost.

cur.execute("""
SELECT band_no, bucket_key, COUNT(*)
FROM lsh_buckets
GROUP BY band_no, bucket_key
""")

large_buckets = set()

for band, key, size in cur.fetchall():
    if size > 100:
        large_buckets.add((band, key))

before_same = 0
after_same = 0
before_diff = 0
after_diff = 0

for a, b, label, text_a, text_b, sig_a, sig_b in pairs:

    cur.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM lsh_buckets x
            JOIN lsh_buckets y
              ON x.band_no = y.band_no
             AND x.bucket_key = y.bucket_key
            WHERE x.notice_id = %s
              AND y.notice_id = %s
        )
    """, (a, b))

    before = cur.fetchone()[0]

    cur.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM lsh_buckets x
            JOIN lsh_buckets y
              ON x.band_no = y.band_no
             AND x.bucket_key = y.bucket_key
            WHERE x.notice_id = %s
              AND y.notice_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM lsh_buckets z
                  WHERE z.band_no = x.band_no
                    AND z.bucket_key = x.bucket_key
                  GROUP BY z.band_no, z.bucket_key
                  HAVING COUNT(*) > 100
              )
        )
    """, (a, b))

    after = cur.fetchone()[0]

    if label == "same":
        before_same += int(before)
        after_same += int(after)
    else:
        before_diff += int(before)
        after_diff += int(after)

print()
print("========== SECTION E ==========")
print("Mitigation: ignore LSH buckets with >100 notices")
print("Large buckets:", len(large_buckets))

print("SAME before:", before_same, "/", 279,
      "=", round(before_same / 279, 4))

print("SAME after:", after_same, "/", 279,
      "=", round(after_same / 279, 4))

print("DIFFERENT before:", before_diff, "/", 621,
      "=", round(before_diff / 621, 4))

print("DIFFERENT after:", after_diff, "/", 621,
      "=", round(after_diff / 621, 4))

print()
print("========== SECTION D ==========")

cur.execute("""
EXPLAIN (ANALYZE, BUFFERS)
SELECT notice_id
FROM lsh_buckets
WHERE band_no = 0
  AND bucket_key = (
      SELECT bucket_key
      FROM lsh_buckets
      WHERE band_no = 0
      LIMIT 1
  )
""")

for row in cur.fetchall():
    print(row[0])

cur.close()
conn.close()