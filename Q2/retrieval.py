import re
import hashlib
import numpy as np
import psycopg2

NUM_HASHES = 32
BANDS = 8
ROWS_PER_BAND = 4


def normalize(text):
    text = text.lower()

    text = re.sub(
        r'national procurement aggregation service|state procurement cell',
        ' ',
        text
    )

    text = re.sub(
        r'\b(npas|spc|pwd|mc|tn)[-/\\]?[a-z0-9/.-]*\b',
        ' ',
        text
    )

    text = re.sub(
        r'\b\d{1,4}[-/]\d{1,2}[-/]\d{2,4}\b',
        ' ',
        text
    )

    text = re.sub(r'\b\d+\b', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def shingles(text):
    words = text.split()

    if len(words) < 3:
        return {text}

    return {
        ' '.join(words[i:i + 3])
        for i in range(len(words) - 2)
    }


def base_hash(s):
    return int.from_bytes(
        hashlib.blake2b(
            s.encode(),
            digest_size=8
        ).digest(),
        'little'
    )


def signature(shingle_set):
    values = np.array(
        [base_hash(s) for s in shingle_set],
        dtype=np.uint64
    )

    if len(values) == 0:
        return [0] * NUM_HASHES

    prime = np.uint64(18446744073709551557)

    result = []

    for seed in range(NUM_HASHES):
        a = np.uint64(1000003 + seed * 7919)
        b = np.uint64(9176 + seed * 104729)

        hashed = (a * values + b) % prime
        result.append(int(hashed.min()))

    return result


conn = psycopg2.connect(
    host="postgres",
    port=5432,
    dbname="setubid",
    user="setubid",
    password="setubid"
)

cur = conn.cursor()

cur.execute("""
    SELECT notice_id, title, body
    FROM notices
    ORDER BY notice_id
""")

rows = cur.fetchall()

print("Notices:", len(rows))

for i, (notice_id, title, body) in enumerate(rows, 1):

    text = normalize(
        (title or "") + " " + (body or "")
    )

    sig = signature(shingles(text))

    cur.execute("""
        INSERT INTO notice_signatures
        (notice_id, normalized_text, signature)
        VALUES (%s, %s, %s)
        ON CONFLICT (notice_id)
        DO UPDATE SET
            normalized_text = EXCLUDED.normalized_text,
            signature = EXCLUDED.signature
    """, (notice_id, text, sig))

    for band in range(BANDS):

        start = band * ROWS_PER_BAND
        end = start + ROWS_PER_BAND

        bucket_key = hashlib.sha1(
            ",".join(map(str, sig[start:end])).encode()
        ).hexdigest()

        cur.execute("""
            INSERT INTO lsh_buckets
            (band_no, bucket_key, notice_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (band, bucket_key, notice_id))

    if i % 500 == 0:
        conn.commit()
        print("Processed:", i)

conn.commit()

print("LSH construction complete.")

# Candidate survival on labelled pairs
cur.execute("""
    SELECT
        lp.notice_id_a,
        lp.notice_id_b,
        lp.label,
        a.normalized_text,
        b.normalized_text
    FROM labelled_pairs lp
    JOIN notice_signatures a
      ON a.notice_id = lp.notice_id_a
    JOIN notice_signatures b
      ON b.notice_id = lp.notice_id_b
""")

pairs = cur.fetchall()

same_total = 0
same_survived = 0
different_total = 0
different_survived = 0

for a, b, label, text_a, text_b in pairs:

    sa = shingles(text_a)
    sb = shingles(text_b)

    union = sa | sb
    exact_jaccard = (
        len(sa & sb) / len(union)
        if union else 1.0
    )

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

    if label == "same":
        same_total += 1
        same_survived += int(survived)

    else:
        different_total += 1
        different_survived += int(survived)

print()
print("SECTION C - CANDIDATE RETRIEVAL")
print("Same pairs:", same_total)
print("Same surviving:", same_survived)
print(
    "Same candidate recall:",
    round(same_survived / same_total, 4)
)

print("Different pairs:", different_total)
print("Different surviving:", different_survived)
print(
    "Different survival:",
    round(different_survived / different_total, 4)
)

# Candidate workload distribution
cur.execute("""
    SELECT
        band_no,
        bucket_key,
        COUNT(*) AS bucket_size
    FROM lsh_buckets
    GROUP BY band_no, bucket_key
    ORDER BY bucket_size DESC
""")

bucket_sizes = [r[2] for r in cur.fetchall()]

print()
print("SECTION E - WORK DISTRIBUTION")
print("Buckets:", len(bucket_sizes))

if bucket_sizes:
    print("Maximum bucket size:", max(bucket_sizes))
    print("Average bucket size:", round(sum(bucket_sizes) / len(bucket_sizes), 2))

    q50, q95, q99 = np.percentile(
        bucket_sizes,
        [50, 95, 99]
    )

    print("Median bucket size:", round(q50, 2))
    print("95th percentile:", round(q95, 2))
    print("99th percentile:", round(q99, 2))

# D - planner evidence
print()
print("SECTION D - QUERY PLAN")

cur.execute("""
    EXPLAIN (ANALYZE, BUFFERS)
    SELECT x.notice_id
    FROM lsh_buckets x
    WHERE x.band_no = 0
    AND x.bucket_key = (
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