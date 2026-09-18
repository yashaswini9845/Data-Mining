import csv
import glob
import psycopg2

conn = psycopg2.connect(
    host="host.docker.internal",
    port=5433,
    dbname="setubid",
    user="setubid",
    password="setubid"
)

cur = conn.cursor()

# Load notices
notice_files = glob.glob("data_2/notices/*.csv")

notice_count = 0

for filename in notice_files:
    with open(filename, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            cur.execute("""
                INSERT INTO notices
                (notice_id, portal_id, published_at, title, body,
                 estimated_value, closing_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (notice_id) DO NOTHING
            """, (
                row["notice_id"],
                row["portal_id"],
                row["published_at"] or None,
                row["title"],
                row["body"],
                row["estimated_value"] or None,
                row["closing_date"] or None
            ))

            notice_count += 1

# Load labelled pairs
pair_count = 0

with open("data_2/labelled_pairs.csv", "r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        cur.execute("""
            INSERT INTO labelled_pairs
            (notice_id_a, notice_id_b, label)
            VALUES (%s, %s, %s)
            ON CONFLICT (notice_id_a, notice_id_b) DO NOTHING
        """, (
            row["notice_id_a"],
            row["notice_id_b"],
            row["label"]
        ))

        pair_count += 1

conn.commit()

cur.execute("SELECT COUNT(*) FROM notices")
db_notices = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM labelled_pairs")
db_pairs = cur.fetchone()[0]

print("CSV notice rows processed:", notice_count)
print("CSV labelled pairs processed:", pair_count)
print("Database notices:", db_notices)
print("Database labelled pairs:", db_pairs)

cur.close()
conn.close()