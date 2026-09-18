import os
import re
import csv
import hashlib
import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALES_DIR = os.path.join(BASE_DIR, "data", "sales")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

DB_FILE = os.path.join(OUTPUT_DIR, "q1_sales.duckdb")
CANONICAL_CSV = os.path.join(OUTPUT_DIR, "sales_canonical.csv")
PARQUET_FILE = os.path.join(OUTPUT_DIR, "sales_canonical.parquet")
PROOF_FILE = os.path.join(OUTPUT_DIR, "ingestion_proof.txt")


def get_business_info(filename):
    match = re.search(r"SALES_(S\d+)_(\d{8})", filename)

    if not match:
        return None, None

    store_id = match.group(1)
    d = match.group(2)

    business_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    return store_id, business_date


def normalize_row(row, store_id, business_date):
    bill_no = row.get("bill_no")
    line_no = row.get("line_no")

    product_code = row.get("product_code")
    if product_code is None:
        product_code = row.get("item_code")

    qty = row.get("qty")
    if qty is None:
        qty = row.get("quantity")

    unit_price = row.get("unit_price")
    if unit_price is None:
        unit_price = row.get("rate")

    line_type = row.get("line_type")
    if line_type is None:
        line_type = row.get("type")

    if bill_no is None or line_no is None:
        return None

    if product_code is None or qty is None or unit_price is None or line_type is None:
        return None

    try:
        qty = float(qty)
        unit_price = float(unit_price)
    except (ValueError, TypeError):
        return None

    return [
        str(bill_no).strip(),
        str(line_no).strip(),
        str(product_code).strip(),
        qty,
        unit_price,
        str(line_type).strip().upper(),
        store_id,
        business_date,
    ]


def read_csv_to_writer(path, writer, counters, store_id, business_date):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        first_line = f.readline()

        if not first_line:
            return

        delimiter = ";" if ";" in first_line else ","

        f.seek(0)

        reader = csv.DictReader(f, delimiter=delimiter)

        for row in reader:
            counters["rows_read"] += 1

            normalized = normalize_row(
                row,
                store_id,
                business_date
            )

            if normalized is not None:
                writer.writerow(normalized)
                counters["rows_written"] += 1


def read_parquet_to_writer(path, writer, counters, store_id, business_date):
    con = duckdb.connect()

    result = con.execute(
        """
        SELECT *
        FROM read_parquet(?)
        """,
        [path]
    )

    columns = [x[0] for x in result.description]

    for values in result.fetchall():
        counters["rows_read"] += 1

        row = dict(zip(columns, values))

        normalized = normalize_row(
            row,
            store_id,
            business_date
        )

        if normalized is not None:
            writer.writerow(normalized)
            counters["rows_written"] += 1

    con.close()


def build_canonical_csv():
    files = []

    for root, _, filenames in os.walk(SALES_DIR):
        for filename in filenames:
            if filename.lower().endswith((".csv", ".parquet")):
                files.append(os.path.join(root, filename))

    files.sort()

    print("Sales files found:", len(files))

    counters = {
        "rows_read": 0,
        "rows_written": 0
    }

    with open(
        CANONICAL_CSV,
        "w",
        encoding="utf-8",
        newline=""
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "bill_no",
            "line_no",
            "product_code",
            "qty",
            "unit_price",
            "line_type",
            "store_id",
            "business_date"
        ])

        for i, path in enumerate(files, 1):

            filename = os.path.basename(path)

            store_id, business_date = get_business_info(filename)

            if store_id is None:
                continue

            if filename.lower().endswith(".csv"):
                read_csv_to_writer(
                    path,
                    writer,
                    counters,
                    store_id,
                    business_date
                )
            else:
                read_parquet_to_writer(
                    path,
                    writer,
                    counters,
                    store_id,
                    business_date
                )

            if i % 500 == 0:
                print(
                    f"Processed: {i} files | "
                    f"Rows read: {counters['rows_read']}"
                )

    return len(files), counters


def create_deduplicated_parquet():
    con = duckdb.connect(DB_FILE)

    con.execute(
        """
        CREATE OR REPLACE TABLE raw_sales AS
        SELECT
            bill_no,
            line_no,
            product_code,
            CAST(qty AS DOUBLE) AS qty,
            CAST(unit_price AS DOUBLE) AS unit_price,
            line_type,
            store_id,
            CAST(business_date AS DATE) AS business_date
        FROM read_csv(
            ?,
            header = true,
            auto_detect = true
        )
        """,
        [CANONICAL_CSV]
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE sales_deduplicated AS
        SELECT
            bill_no,
            line_no,
            product_code,
            qty,
            unit_price,
            line_type,
            store_id,
            business_date
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY bill_no, line_no
                    ORDER BY store_id, business_date
                ) AS rn
            FROM raw_sales
        )
        WHERE rn = 1
        """
    )

    con.execute(
        """
        COPY sales_deduplicated
        TO ?
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """,
        [PARQUET_FILE]
    )

    raw_count = con.execute(
        "SELECT COUNT(*) FROM raw_sales"
    ).fetchone()[0]

    final_count = con.execute(
        "SELECT COUNT(*) FROM sales_deduplicated"
    ).fetchone()[0]

    duplicate_count = raw_count - final_count

    con.close()

    return raw_count, final_count, duplicate_count


def checksum_file(path):
    sha256 = hashlib.sha256()

    with open(path, "rb") as f:
        while True:
            block = f.read(1024 * 1024)

            if not block:
                break

            sha256.update(block)

    return sha256.hexdigest()


def main():

    print("=== Q1 SALES INGESTION ===")
    print("Source:", SALES_DIR)

    source_files, counters = build_canonical_csv()

    print()
    print("Rows read before cleaning:", counters["rows_read"])
    print("Valid rows written:", counters["rows_written"])

    raw_count, final_count, duplicate_count = (
        create_deduplicated_parquet()
    )

    checksum = checksum_file(os.path.join(OUTPUT_DIR, "sales_canonical.csv"))

    print()
    print("Rows loaded:", raw_count)
    print("Duplicate rows removed:", duplicate_count)
    print("Rows after deduplication:", final_count)
    print("SHA256:", checksum)
    print("Canonical Parquet:", PARQUET_FILE)

    with open(PROOF_FILE, "w", encoding="utf-8") as f:
        f.write("Q1 SALES INGESTION PROOF\n")
        f.write("========================\n")
        f.write(f"Source files: {source_files}\n")
        f.write(f"Rows read before cleaning: {counters['rows_read']}\n")
        f.write(f"Valid rows written: {counters['rows_written']}\n")
        f.write(f"Rows loaded: {raw_count}\n")
        f.write(f"Duplicate rows removed: {duplicate_count}\n")
        f.write(f"Rows after deduplication: {final_count}\n")
        f.write(f"SHA256: {checksum}\n")

    print("Proof file:", PROOF_FILE)


if __name__ == "__main__":
    main()