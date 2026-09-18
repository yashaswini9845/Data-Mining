CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS notices (
    notice_id TEXT PRIMARY KEY,
    portal_id TEXT NOT NULL,
    published_at TIMESTAMP,
    title TEXT,
    body TEXT,
    estimated_value NUMERIC,
    closing_date DATE
);

CREATE TABLE IF NOT EXISTS labelled_pairs (
    notice_id_a TEXT NOT NULL,
    notice_id_b TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN ('same', 'different')),
    PRIMARY KEY (notice_id_a, notice_id_b)
);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notice_opportunity (
    notice_id TEXT PRIMARY KEY REFERENCES notices(notice_id),
    opportunity_id BIGINT NOT NULL REFERENCES opportunities(opportunity_id)
);

CREATE TABLE IF NOT EXISTS notice_signatures (
    notice_id TEXT PRIMARY KEY REFERENCES notices(notice_id),
    normalized_text TEXT NOT NULL,
    signature BIGINT[] NOT NULL
);

CREATE TABLE IF NOT EXISTS lsh_buckets (
    band_no INTEGER NOT NULL,
    bucket_key TEXT NOT NULL,
    notice_id TEXT NOT NULL REFERENCES notices(notice_id),
    PRIMARY KEY (band_no, bucket_key, notice_id)
);

CREATE INDEX IF NOT EXISTS idx_lsh_bucket_lookup
ON lsh_buckets (band_no, bucket_key);

CREATE INDEX IF NOT EXISTS idx_notice_opportunity_opportunity
ON notice_opportunity (opportunity_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO settings (key, value)
VALUES
    ('false_merge_cost_ratio', '10'),
    ('retrieval_target_recall', '0.95')
ON CONFLICT (key) DO NOTHING;