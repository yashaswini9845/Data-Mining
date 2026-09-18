# Annapurna Stores — Q1 Data Platform

## Project Overview

This project builds a local data platform for Annapurna Stores to replace manual spreadsheet-based sales reporting.

The platform is designed to provide:

- Consistent monthly revenue figures
- Revenue analysis by store, product category, day of week, and month
- Historical product prices based on the reporting period
- Safe and repeatable data loading
- Federated queries across object storage and PostgreSQL
- Monthly reconciliation against finance figures

The implementation uses Docker Compose, MinIO, PostgreSQL, DuckDB, and Parquet.

> **Q1 scope:** Only the `data/` dataset is used. The separate `data_2/` dataset is not used.

---

## Architecture

```text
Daily Sales Files
       |
       v
     MinIO
  Data Lake / Raw
       |
       v
     DuckDB
 Analytical Engine
       |
       +----------------------+
       |                      |
       v                      v
  Sales Parquet          PostgreSQL
                         Master Data
                         - Stores
                         - Products
                         - Categories
                         - Price Revisions
```

### Components

| Component | Purpose |
|---|---|
| MinIO | Local object storage / data lake |
| PostgreSQL | Stores, products, categories and price revisions |
| DuckDB | Analytical and federated query engine |
| Parquet | Columnar analytical storage |
| Docker Compose | Reproducible local deployment |

---

## Project Structure

```text
Q1/
├── README.md
├── docker-compose.yml
├── data/
│   ├── sales/
│   ├── masters.sql
│   ├── billing_notes.md
│   └── finance_monthly.csv
├── duckdb/
├── output/
│   ├── sales_partitioned/
│   ├── sales_canonical.csv
│   ├── sales_canonical.parquet
│   ├── ingestion_proof.txt
│   ├── proof_run1_corrected.txt
│   ├── proof_run2_corrected.txt
│   └── proof_run3_corrected.txt
├── postgres/
│   └── init.sql
└── scripts/
    └── ingest_sales.py
```

---

# Part A — Platform Setup and Data Landing

## Platform Setup

The local platform consists of:

- PostgreSQL
- MinIO
- DuckDB

The PostgreSQL master tables are:

- `stores`
- `products`
- `product_categories`
- `price_revisions`

The sales files are landed into MinIO.

## Partitioning Strategy

Sales data is organized using:

```text
raw/sales/store=<store_id>/year=<YYYY>/month=<MM>/
```

For example:

```text
raw/sales/store=S01/year=2024/month=10/
```

This layout allows a query for a particular store and month to target only that partition.

### Measured Partition Example

For:

```text
S01 / October 2024
```

the partition contains:

```text
31 files
846,899 bytes
```

The complete partitioned sales dataset contains:

```text
4,457 files
68,706,877 bytes
```

Therefore, an S01 October query can potentially access:

```text
31 files
846,899 bytes
```

instead of scanning:

```text
4,457 files
68,706,877 bytes
```

### Partition Query

```sql
SELECT COUNT(*) AS rows_in_october_s01,
       ROUND(SUM(qty * unit_price), 2) AS amount
FROM read_csv_auto(
    's3://q1-datalake/raw/sales/store=S01/year=2024/month=10/*.csv'
);
```

Measured result:

```text
rows_in_october_s01 = 13,516
amount = 13,991,186.34
```

The above is a raw partition-query demonstration. It is not the final revenue figure because the official revenue definition handles line types such as `SALE`, `RETURN`, `DISCOUNT`, `VOID`, `TAX`, and `TENDER`.

---

# Part B — Idempotent Loading

The source contains resends and duplicate records.

The safe sales-line identifier is:

```text
(bill_no, line_no)
```

The ingestion process:

1. Reads CSV and Parquet sales files.
2. Normalizes different file dialects and column names.
3. Produces a canonical sales dataset.
4. Removes duplicate `(bill_no, line_no)` records.
5. Writes canonical CSV and Parquet output.
6. Calculates a SHA-256 checksum.

## Ingestion Measurements

```text
Sales files found:              4,457
Rows read before cleaning:      1,137,585
Valid rows written:             1,137,585
Rows loaded:                    1,137,585
Duplicate rows removed:         16,661
Rows after deduplication:       1,120,924
```

## Three-Run Proof

| Run | Rows After Deduplication | SHA-256 |
|---|---:|---|
| Run 1 | 1,120,924 | `4c08fdb854fbea7d858d1a35f17dc9313fd8b525ab9ec6855121ca230c0ed7f2` |
| Run 2 | 1,120,924 | `4c08fdb854fbea7d858d1a35f17dc9313fd8b525ab9ec6855121ca230c0ed7f2` |
| Run 3 | 1,120,924 | `4c08fdb854fbea7d858d1a35f17dc9313fd8b525ab9ec6855121ca230c0ed7f2` |

The identical row counts and checksums demonstrate that running the loading process repeatedly produces the same canonical result.

---

# Part C — Analytical Model and Revenue Slicing

## Star-Schema Approach

The analytical model separates transaction data from descriptive master data.

The main fact table is:

```text
fact_sales
```

and master/dimension data is maintained in PostgreSQL.

The final fact table contains:

```text
1,120,924 rows
```

Store names and addresses are therefore not repeated on every sales line.

## Product Identity

Product codes cannot be treated as globally unique because product codes were reissued.

The product join therefore uses:

```text
product_code
+
business_date BETWEEN valid_from AND valid_to
```

This ensures that the product version valid on the sale date is selected.

## Revenue Definition

Revenue is calculated from:

```text
SALE
RETURN
DISCOUNT
VOID
```

using:

```text
qty * unit_price
```

`TAX` and `TENDER` are excluded from revenue.

This prevents `TENDER`, which represents the bill total, from being counted as another revenue line.

---

## Revenue by Store

| Store | Revenue (INR) |
|---|---:|
| S01 | 56,995,199.14 |
| S02 | 47,194,947.02 |
| S03 | 61,864,894.46 |
| S04 | 40,201,258.53 |
| S05 | 30,159,037.54 |
| S06 | 52,584,302.70 |
| S07 | 35,219,585.45 |
| S08 | 34,477,161.43 |
| S09 | 27,978,995.77 |
| S10 | 59,327,041.98 |
| S11 | 32,429,712.91 |
| S12 | 44,433,598.82 |

## Revenue by Category

| Category ID | Revenue (INR) |
|---|---:|
| C01 | 7,335,274.17 |
| C02 | 39,696,588.61 |
| C03 | 25,805,866.86 |
| C04 | 98,677,244.71 |
| C05 | 82,736,636.78 |
| C06 | 18,408,992.48 |
| C07 | 37,437,446.74 |
| C08 | 28,253,823.00 |
| C09 | 88,746,237.02 |
| C10 | 29,765,097.34 |
| C11 | 12,957,549.04 |
| C12 | 15,314,853.80 |
| C13 | 17,251,020.23 |
| C14 | 25,749,321.35 |

## Revenue by Day of Week

| Day | Revenue (INR) |
|---|---:|
| Monday | 59,589,704.80 |
| Tuesday | 58,523,374.95 |
| Wednesday | 60,808,849.66 |
| Thursday | 65,020,714.40 |
| Friday | 79,012,260.21 |
| Saturday | 104,941,626.27 |
| Sunday | 94,969,205.46 |

---

# Part D — Historical Price Revisions

Historical prices are stored in:

```text
price_revisions
```

Measured table information:

```text
Price revision rows:       4,320
Products with revisions:   1,224
Earliest effective date:   2022-01-01
Latest effective date:     9999-12-31
```

Historical prices are selected according to the reporting period rather than using the current shelf price.

## Example

Product:

```text
P100005
Thums Up Mango Juice 250g
```

Product SK:

```text
1001
```

### March 2024

```text
Selling price = ₹103.45
```

### October 2024

```text
Selling price = ₹114.37
```

The query structure remains the same; only the reporting period changes.

Example:

```sql
WITH reporting_period AS (
    SELECT DATE '2024-03-01' AS period_start,
           DATE '2024-03-31' AS period_end
)
SELECT p.product_code,
       p.product_name,
       pr.product_sk,
       pr.selling_price AS historical_price
FROM pg.public.price_revisions pr
JOIN pg.public.products p
    ON pr.product_sk = p.product_sk
CROSS JOIN reporting_period r
WHERE p.product_code = 'P100005'
  AND pr.effective_from <= r.period_end
  AND pr.effective_to >= r.period_start;
```

For October 2024, only the reporting dates are changed.

---

# Part E — Federated Query

Sales data remains in the object-store Parquet dataset.

Store, product, and category master data remains in PostgreSQL.

DuckDB performs the join across both systems without copying the source data into the other system.

## Federated Query

```sql
SELECT
    p.category_id,
    c.category_name,
    COUNT(*) AS sales_lines,
    ROUND(
        SUM(
            CASE
                WHEN s.line_type IN
                     ('SALE','RETURN','DISCOUNT','VOID')
                THEN s.qty * s.unit_price
                ELSE 0
            END
        ), 2
    ) AS revenue
FROM read_parquet(
    'output/sales_canonical.parquet'
) s
JOIN pg.public.products p
    ON s.product_code = p.product_code
   AND s.business_date BETWEEN p.valid_from AND p.valid_to
JOIN pg.public.product_categories c
    ON p.category_id = c.category_id
WHERE s.line_type IN
      ('SALE','RETURN','DISCOUNT','VOID')
GROUP BY p.category_id, c.category_name
ORDER BY p.category_id;
```

## Federated Query Output

| Category | Sales Lines | Revenue (INR) |
|---|---:|---:|
| C01 Biscuits & Snacks | 54,244 | 7,335,274.17 |
| C02 Dairy | 60,998 | 39,696,588.61 |
| C03 Beverages | 50,685 | 25,805,866.86 |
| C04 Staples & Grains | 59,961 | 98,677,244.71 |
| C05 Edible Oils | 56,221 | 82,736,636.78 |
| C06 Spices & Masala | 51,566 | 18,408,992.48 |
| C07 Personal Care | 46,864 | 37,437,446.74 |
| C08 Home Care | 47,218 | 28,253,823.00 |
| C09 Baby Care | 57,216 | 88,746,237.02 |
| C10 Frozen & Ready to Eat | 57,609 | 29,765,097.34 |
| C11 Bakery | 59,835 | 12,957,549.04 |
| C12 Fruits & Vegetables | 55,356 | 15,314,853.80 |
| C13 Confectionery | 53,385 | 17,251,020.23 |
| C14 Stationery & General | 55,638 | 25,749,321.35 |

## Query Plan Evidence

DuckDB's physical plan contains:

```text
READ_PARQUET
POSTGRES_SCAN products
POSTGRES_SCAN product_categories
```

The product join uses:

```text
product_code = product_code
business_date >= valid_from
business_date <= valid_to
```

Plan estimates captured during testing:

```text
READ_PARQUET       ~1,120,924 rows
products           ~1,264 rows
categories         ~148 rows
```

This demonstrates that DuckDB evaluates the analytical query across the object-store sales data and PostgreSQL master data.

---

# Part F — Monthly Finance Reconciliation

The pipeline monthly revenue was compared against:

```text
data/finance_monthly.csv
```

Revenue was calculated using:

```text
SALE + RETURN + DISCOUNT + VOID
```

and excluding:

```text
TAX + TENDER
```

## Reconciliation Results

| Month | Pipeline Revenue | Finance Revenue | Difference | Classification |
|---|---:|---:|---:|---|
| 2024-01 | 38,446,071.33 | 38,446,071.33 | 0.00 | Match |
| 2024-02 | 34,887,085.55 | 34,887,085.55 | 0.00 | Match |
| 2024-03 | 41,971,649.09 | 42,457,899.09 | -486,250.00 | Requires further investigation |
| 2024-04 | 37,958,457.37 | 37,958,457.37 | 0.00 | Match |
| 2024-05 | 41,764,716.40 | 41,764,716.40 | 0.00 | Match |
| 2024-06 | 38,987,082.82 | 38,987,082.82 | 0.00 | Match |
| 2024-07 | 40,295,160.11 | 40,527,291.81 | -232,131.70 | Source data problem |
| 2024-08 | 45,252,181.75 | 45,252,181.75 | 0.00 | Match |
| 2024-09 | 44,615,037.46 | 44,615,037.46 | 0.00 | Match |
| 2024-10 | 56,359,195.92 | 56,359,195.92 | 0.00 | Match |
| 2024-11 | 51,583,838.47 | 51,583,838.47 | 0.00 | Match |
| 2024-12 | 50,745,259.48 | 50,745,209.00 | +50.48 | Requires further investigation |

---

## March Investigation

March line-type totals were:

```text
DISCOUNT = -422,529.83
RETURN   = -872,421.34
SALE     = 43,570,195.04
TAX      = 3,671,749.71
TENDER   = 45,643,398.80
VOID     = -303,594.78
```

Duplicate revenue line keys:

```text
0
```

March partition coverage:

```text
Files:          374
First date:     2024-03-01
Last date:      2024-03-31
Business days:  31
```

All 12 stores were present.

The March difference is:

```text
₹486,250.00
```

The available evidence did not conclusively establish whether the difference is a source-data issue, a revenue-definition difference, or a pipeline bug.

Classification:

```text
Requires further investigation
```

---

## July Investigation

The supplied billing notes identify a source-data gap for S07 in July 2024.

Measured S07 coverage:

```text
28 business days
```

Missing dates:

```text
2024-07-09
2024-07-10
2024-07-11
```

All other stores had 31 July business days.

S07 July revenue present in the pipeline:

```text
₹2,651,159.69
```

The July finance difference is:

```text
₹232,131.70
```

Therefore July is classified as:

```text
Source data problem
```

The exact difference was not independently matched to the missing-day amount, so no exact amount-level claim is made.

---

## December Investigation

December line-type totals were:

```text
DISCOUNT = -512,901.24
RETURN   = -1,144,992.16
SALE     = 52,692,638.60
TAX      = 4,446,582.31
TENDER   = 55,191,841.79
VOID     = -289,485.72
```

Duplicate revenue line keys:

```text
0
```

Pipeline revenue:

```text
₹50,745,259.48
```

Finance revenue:

```text
₹50,745,209.00
```

Difference:

```text
₹50.48
```

The available evidence did not conclusively establish the cause.

Classification:

```text
Requires further investigation
```

---

# Final Reconciliation Classification

```text
2024-01  -> Match
2024-02  -> Match
2024-03  -> Requires further investigation
2024-04  -> Match
2024-05  -> Match
2024-06  -> Match
2024-07  -> Source data problem
2024-08  -> Match
2024-09  -> Match
2024-10  -> Match
2024-11  -> Match
2024-12  -> Requires further investigation
```

---

# Data Quality Rules

### Business Date

The filename date is treated as the business date, even when an internal timestamp crosses midnight.

### Duplicate Lines

The safe deduplication key is:

```text
(bill_no, line_no)
```

### Revenue Lines

Included:

```text
SALE
RETURN
DISCOUNT
VOID
```

Excluded:

```text
TAX
TENDER
```

### Product Reissue

Product codes are not globally unique.

The product version is selected using:

```text
product_code
+
business_date
+
valid_from / valid_to
```

### Historical Prices

Historical selling price is selected from:

```text
price_revisions
```

according to the reporting period.

---

# Reproducibility and Evidence

Important generated outputs are stored under `output/`.

```text
output/
├── sales_partitioned/
├── sales_canonical.csv
├── sales_canonical.parquet
├── ingestion_proof.txt
├── proof_run1_corrected.txt
├── proof_run2_corrected.txt
└── proof_run3_corrected.txt
```

Canonical dataset size by row count:

```text
1,120,924 rows
```

Idempotency checksum:

```text
4c08fdb854fbea7d858d1a35f17dc9313fd8b525ab9ec6855121ca230c0ed7f2
```

The checksum is identical for all three ingestion runs.

---

# Key Results Summary

| Requirement | Result |
|---|---|
| Sales files processed | 4,457 |
| Rows before deduplication | 1,137,585 |
| Duplicate rows removed | 16,661 |
| Final canonical rows | 1,120,924 |
| S01 October files | 31 |
| S01 October bytes | 846,899 |
| Price revision rows | 4,320 |
| Products with revisions | 1,224 |
| PostgreSQL stores | 12 |
| PostgreSQL categories | 14 |
| Federated analytical engine | DuckDB |
| Object storage | MinIO |
| Relational database | PostgreSQL |
| Analytical storage | Parquet |

---

# Conclusion

The Q1 solution establishes a reproducible local data platform for Annapurna Stores.

It provides partitioned object storage, deterministic ingestion, a normalized analytical model, historical price handling, federated querying, and monthly reconciliation.

The measured results show that repeated ingestion produces the same canonical dataset, historical prices change correctly with the reporting period, and finance differences can be isolated for investigation using reproducible measurements.

The platform keeps raw sales data, analytical data, and PostgreSQL master data in their respective systems while using DuckDB for analytical and federated processing.



