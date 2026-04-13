-- schema.sql
-- Star schema for the Olist e-commerce data warehouse
-- Designed for analytical queries — not transactional use
-- Using SQLite syntax (can be adapted to Postgres with minor changes)
--
-- Tables:
--   fact_orders       → core fact table, one row per order
--   dim_customers     → customer dimension
--   dim_products      → product dimension
--   dim_sellers       → seller dimension
--   dim_time          → date dimension for time-series analysis
--   order_items       → line-item detail (not a dim, used for drill-down)
--   payments          → payment detail (multiple rows per order)
--   reviews           → review detail (one per order mostly)

-- ─────────────────────────────────────────────────────────
-- DIM: CUSTOMERS
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_customers (
    customer_id         TEXT PRIMARY KEY,    -- per-order customer ID (not unique across orders)
    customer_unique_id  TEXT NOT NULL,       -- actual unique customer identifier
    customer_zip_code_prefix TEXT,
    customer_city       TEXT,
    customer_state      TEXT
);

-- index on unique_id for customer-level aggregations
CREATE INDEX IF NOT EXISTS idx_customers_unique ON dim_customers(customer_unique_id);
CREATE INDEX IF NOT EXISTS idx_customers_state  ON dim_customers(customer_state);


-- ─────────────────────────────────────────────────────────
-- DIM: PRODUCTS
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_products (
    product_id                      TEXT PRIMARY KEY,
    product_category_name           TEXT,
    product_category_name_english   TEXT,         -- translated from Portuguese
    product_name_lenght             INTEGER,      -- keeping original typo from dataset
    product_description_lenght      INTEGER,
    product_photos_qty              INTEGER,
    product_weight_g                REAL,
    product_length_cm               REAL,
    product_height_cm               REAL,
    product_width_cm                REAL,
    seller_id                       TEXT          -- denormalized for convenience
);

CREATE INDEX IF NOT EXISTS idx_products_category ON dim_products(product_category_name_english);


-- ─────────────────────────────────────────────────────────
-- DIM: SELLERS
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_sellers (
    seller_id               TEXT PRIMARY KEY,
    seller_zip_code_prefix  TEXT,
    seller_city             TEXT,
    seller_state            TEXT
);

CREATE INDEX IF NOT EXISTS idx_sellers_state ON dim_sellers(seller_state);


-- ─────────────────────────────────────────────────────────
-- DIM: TIME
-- One row per calendar date found in the orders data
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_time (
    time_id         INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,     -- stored as YYYY-MM-DD
    year            INTEGER,
    month           INTEGER,
    month_name      TEXT,
    day             INTEGER,
    quarter         INTEGER,
    week_of_year    INTEGER,
    day_of_week     TEXT,
    is_weekend      INTEGER            -- 0 or 1 (boolean in SQLite)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_time_date ON dim_time(date);


-- ─────────────────────────────────────────────────────────
-- FACT: ORDERS
-- One row per order — the central table
-- Denormalizes some fields for faster dashboard queries
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_orders (
    -- keys
    order_id                        TEXT PRIMARY KEY,
    customer_id                     TEXT NOT NULL,
    customer_unique_id              TEXT,
    time_id                         INTEGER,           -- FK to dim_time

    -- order lifecycle timestamps
    order_purchase_timestamp        TEXT,
    order_approved_at               TEXT,
    order_delivered_carrier_date    TEXT,
    order_delivered_customer_date   TEXT,
    order_estimated_delivery_date   TEXT,

    -- status
    order_status                    TEXT,

    -- customer location (denormalized from dim_customers)
    customer_state                  TEXT,
    customer_city                   TEXT,

    -- derived delivery metrics
    delivery_delay_days             REAL,   -- positive = late
    is_late                         INTEGER, -- 0/1

    -- financials (aggregated from payments + order_items)
    total_payment                   REAL,
    total_items_value               REAL,
    total_freight                   REAL,
    total_order_value               REAL,   -- items + freight
    item_count                      INTEGER,
    payment_installments            INTEGER,
    payment_type                    TEXT,   -- most common payment type for order

    -- quality signal
    review_score                    REAL,   -- 1–5, null if no review

    -- foreign keys (not enforced in SQLite but good for documentation)
    -- FOREIGN KEY (customer_id)  REFERENCES dim_customers(customer_id),
    -- FOREIGN KEY (time_id)      REFERENCES dim_time(time_id)
    purchase_date                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_customer ON fact_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_fact_status   ON fact_orders(order_status);
CREATE INDEX IF NOT EXISTS idx_fact_date     ON fact_orders(order_purchase_timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_late     ON fact_orders(is_late);


-- ─────────────────────────────────────────────────────────
-- ORDER ITEMS (line-item detail)
-- Not a dimension, more of a bridge/detail table
-- Joins to dim_products and dim_sellers
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    order_id            TEXT NOT NULL,
    order_item_id       INTEGER NOT NULL,   -- item sequence within order
    product_id          TEXT,
    seller_id           TEXT,
    shipping_limit_date TEXT,
    price               REAL,
    freight_value       REAL,

    PRIMARY KEY (order_id, order_item_id)

    -- FOREIGN KEY (order_id)    REFERENCES fact_orders(order_id),
    -- FOREIGN KEY (product_id)  REFERENCES dim_products(product_id),
    -- FOREIGN KEY (seller_id)   REFERENCES dim_sellers(seller_id)
);

CREATE INDEX IF NOT EXISTS idx_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_items_seller  ON order_items(seller_id);


-- ─────────────────────────────────────────────────────────
-- PAYMENTS
-- Multiple rows per order possible (installments, mixed methods)
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    order_id                TEXT NOT NULL,
    payment_sequential      INTEGER,        -- sequence in multi-payment scenarios
    payment_type            TEXT,           -- credit_card, boleto, voucher, debit_card
    payment_installments    INTEGER,
    payment_value           REAL,

    PRIMARY KEY (order_id, payment_sequential)

    -- FOREIGN KEY (order_id) REFERENCES fact_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_payments_type ON payments(payment_type);


-- ─────────────────────────────────────────────────────────
-- REVIEWS
-- Mostly one per order, but there are edge cases with multiple
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
    review_id               TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL,
    review_score            INTEGER,        -- 1 to 5
    review_comment_title    TEXT,
    review_comment_message  TEXT,
    review_creation_date    TEXT,
    review_answer_timestamp TEXT

    -- FOREIGN KEY (order_id) REFERENCES fact_orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_order ON reviews(order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_score ON reviews(review_score);


-- ─────────────────────────────────────────────────────────
-- USEFUL VIEWS (optional, helps with BI tool connections)
-- ─────────────────────────────────────────────────────────

-- monthly revenue summary
CREATE VIEW IF NOT EXISTS v_monthly_revenue AS
SELECT
    t.year,
    t.month,
    t.month_name,
    COUNT(f.order_id)       AS total_orders,
    SUM(f.total_order_value) AS revenue,
    AVG(f.total_order_value) AS avg_order_value,
    SUM(CASE WHEN f.is_late = 1 THEN 1 ELSE 0 END) AS late_deliveries
FROM fact_orders f
JOIN dim_time t ON f.time_id = t.time_id
WHERE f.order_status = 'delivered'
GROUP BY t.year, t.month, t.month_name
ORDER BY t.year, t.month;


-- seller performance summary
CREATE VIEW IF NOT EXISTS v_seller_performance AS
SELECT
    s.seller_id,
    s.seller_state,
    COUNT(DISTINCT oi.order_id)     AS total_orders,
    SUM(oi.price)                   AS total_revenue,
    AVG(oi.price)                   AS avg_item_price,
    AVG(r.review_score)             AS avg_review_score
FROM dim_sellers s
LEFT JOIN order_items oi ON s.seller_id = oi.seller_id
LEFT JOIN reviews r      ON oi.order_id = r.order_id
GROUP BY s.seller_id, s.seller_state;


-- customer order summary (for RFM-style analysis)
CREATE VIEW IF NOT EXISTS v_customer_summary AS
SELECT
    c.customer_unique_id,
    c.customer_state,
    COUNT(f.order_id)              AS order_count,
    SUM(f.total_order_value)       AS lifetime_value,
    AVG(f.total_order_value)       AS avg_order_value,
    MAX(f.order_purchase_timestamp) AS last_order_date,
    AVG(f.review_score)            AS avg_review_score
FROM dim_customers c
JOIN fact_orders f ON c.customer_id = f.customer_id
GROUP BY c.customer_unique_id, c.customer_state;
