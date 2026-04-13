import os
import pandas as pd
import numpy as np
import sqlite3
import logging
from datetime import datetime

# basic logging setup — probably should move this to a config file later
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log")
    ]
)
log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(os.path.dirname(__file__), "olist_warehouse.db")



# STEP 1: LOAD DATA

def load_data(data_dir=DATA_DIR):
    """
    Load all Olist CSV files into dataframes.
    Keeping them separate for now — will merge later in transform step.
    """
    log.info("Loading raw CSV files from: %s", data_dir)

    files = {
        "orders":       "olist_orders_dataset.csv",
        "customers":    "olist_customers_dataset.csv",
        "order_items":  "olist_order_items_dataset.csv",
        "payments":     "olist_order_payments_dataset.csv",
        "reviews":      "olist_order_reviews_dataset.csv",
        "products":     "olist_products_dataset.csv",
        "sellers":      "olist_sellers_dataset.csv",
        "geo":          "olist_geolocation_dataset.csv",
        "category_translation": "product_category_name_translation.csv",
    }

    dfs = {}
    for key, filename in files.items():
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path):
            log.warning("File not found: %s — skipping", filename)
            continue
        try:
            dfs[key] = pd.read_csv(path)
            log.info("  Loaded %-25s → %d rows, %d cols", filename, *dfs[key].shape)
        except Exception as e:
            log.error("Failed to load %s: %s", filename, e)

    return dfs


# STEP 2: CLEAN DATA

def clean_data(dfs):
    """
    Realistic cleaning pass.
    Some decisions here are judgment calls — I've noted where I'm not 100% sure.
    """
    log.info("Starting data cleaning...")

    orders = dfs.get("orders", pd.DataFrame()).copy()
    customers = dfs.get("customers", pd.DataFrame()).copy()
    order_items = dfs.get("order_items", pd.DataFrame()).copy()
    payments = dfs.get("payments", pd.DataFrame()).copy()
    reviews = dfs.get("reviews", pd.DataFrame()).copy()
    products = dfs.get("products", pd.DataFrame()).copy()
    sellers = dfs.get("sellers", pd.DataFrame()).copy()
    category_translation = dfs.get("category_translation", pd.DataFrame()).copy()

    # ── ORDERS ──────────────────────────────────
    log.info("Cleaning: orders")

    # these timestamp cols are strings — convert them properly
    # assuming they're all in UTC (the docs don't say, but Brazil is UTC-3, so this might be wrong)
    ts_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    for col in ts_cols:
        if col in orders.columns:
            orders[col] = pd.to_datetime(orders[col], errors="coerce")

    # drop duplicate order_ids — shouldn't happen but just in case
    before = len(orders)
    orders.drop_duplicates(subset="order_id", inplace=True)
    if len(orders) < before:
        log.warning("  Dropped %d duplicate order rows", before - len(orders))

    # filter to only delivered or shipped orders for analysis
    # canceled/unavailable orders mess up delivery time calculations
    valid_statuses = ["delivered", "shipped", "invoiced", "processing", "approved"]
    # actually keeping all statuses — might need canceled for churn analysis later
    # orders = orders[orders["order_status"].isin(valid_statuses)]

    # order_approved_at has some nulls — probably orders that were never approved
    # not filling these, they're meaningful nulls
    null_approved = orders["order_approved_at"].isna().sum()
    if null_approved > 0:
        log.info("  %d orders have null order_approved_at (likely not processed)", null_approved)

    # same for delivery dates — null means not yet delivered
    null_delivered = orders["order_delivered_customer_date"].isna().sum()
    log.info("  %d orders with no delivery date (in-transit or canceled)", null_delivered)

    # ── CUSTOMERS ────────────────────────────────
    log.info("Cleaning: customers")

    # customer_unique_id is the actual customer, customer_id is per-order
    # easy to confuse these — keeping both
    customers.drop_duplicates(subset="customer_id", inplace=True)

    # state codes look fine but let's normalize to uppercase just in case
    if "customer_state" in customers.columns:
        customers["customer_state"] = customers["customer_state"].str.strip().str.upper()

    # city names are messy — lowercase and strip
    if "customer_city" in customers.columns:
        customers["customer_city"] = (
            customers["customer_city"]
            .str.strip()
            .str.lower()
            # some cities have weird accented chars — keeping them for now
        )

    # ── ORDER ITEMS ──────────────────────────────
    log.info("Cleaning: order_items")

    order_items.drop_duplicates(inplace=True)

    # shipping_limit_date — converting
    if "shipping_limit_date" in order_items.columns:
        order_items["shipping_limit_date"] = pd.to_datetime(
            order_items["shipping_limit_date"], errors="coerce"
        )

    # price and freight_value should be positive
    for col in ["price", "freight_value"]:
        if col in order_items.columns:
            negatives = (order_items[col] < 0).sum()
            if negatives > 0:
                log.warning("  Found %d negative values in %s — setting to NaN", negatives, col)
                order_items.loc[order_items[col] < 0, col] = np.nan

    # ── PAYMENTS ────────────────────────────────
    log.info("Cleaning: payments")

    payments.drop_duplicates(inplace=True)

    # payment_value should be positive
    if "payment_value" in payments.columns:
        payments = payments[payments["payment_value"] >= 0]

    # some orders have multiple payment rows (installments + credit card, etc.)
    # not collapsing them yet — keeping granular for now

    # ── REVIEWS ──────────────────────────────────
    log.info("Cleaning: reviews")

    reviews.drop_duplicates(subset="review_id", inplace=True)

    # review_comment_title and review_comment_message have tons of nulls
    # that's normal — most people don't leave text reviews
    # not sure why review_score also has some nulls — dropping those rows
    null_score = reviews["review_score"].isna().sum()
    if null_score > 0:
        log.warning("  %d reviews with null review_score — dropping", null_score)
        reviews.dropna(subset=["review_score"], inplace=True)

    for col in ["review_creation_date", "review_answer_timestamp"]:
        if col in reviews.columns:
            reviews[col] = pd.to_datetime(reviews[col], errors="coerce")

    # ── PRODUCTS ────────────────────────────────
    log.info("Cleaning: products")

    products.drop_duplicates(subset="product_id", inplace=True)

    # product_category_name is in Portuguese — will join translation later
    # a bunch of products have null dimensions/weight — not sure if data issue
    # or if those products were just not measured. filling with median by category
    dim_cols = [
        "product_weight_g", "product_length_cm",
        "product_height_cm", "product_width_cm"
    ]
    for col in dim_cols:
        if col in products.columns:
            null_count = products[col].isna().sum()
            if null_count > 0:
                # not sure about this — filling with overall median for now
                median_val = products[col].median()
                products[col] = products[col].fillna(median_val)
                log.info("  Filled %d nulls in %s with median (%.2f)", null_count, col, median_val)

    # product_name_lenght/description_lenght — typos in original dataset (missing 'g')
    # leaving as-is, don't want to rename and confuse the join later

    if not category_translation.empty:
        products = products.merge(
            category_translation,
            on="product_category_name",
            how="left"
        )
        # some categories won't have a translation — filling with original
        if "product_category_name_english" in products.columns:
            products["product_category_name_english"] = products[
                "product_category_name_english"
            ].fillna(products["product_category_name"])

    # ── SELLERS ──────────────────────────────────
    log.info("Cleaning: sellers")

    sellers.drop_duplicates(subset="seller_id", inplace=True)

    if "seller_state" in sellers.columns:
        sellers["seller_state"] = sellers["seller_state"].str.strip().str.upper()

    if "seller_city" in sellers.columns:
        sellers["seller_city"] = sellers["seller_city"].str.strip().str.lower()

    log.info("Cleaning complete.")

    return {
        "orders": orders,
        "customers": customers,
        "order_items": order_items,
        "payments": payments,
        "reviews": reviews,
        "products": products,
        "sellers": sellers,
    }


# STEP 3: TRANSFORM DATA

def transform_data(cleaned):
    """
    Merge tables, create derived features, and build dimensional tables.
    This is where most of the analytical value gets added.
    """
    log.info("Starting transformations...")

    orders = cleaned["orders"]
    customers = cleaned["customers"]
    order_items = cleaned["order_items"]
    payments = cleaned["payments"]
    reviews = cleaned["reviews"]
    products = cleaned["products"]
    sellers = cleaned["sellers"]

    # ── TOTAL ORDER VALUE ────────────────────────
    # aggregate payments by order_id — some orders have multiple payment methods
    payment_agg = (
        payments.groupby("order_id")
        .agg(
            total_payment=("payment_value", "sum"),
            payment_installments=("payment_installments", "max"),
            payment_type=("payment_type", lambda x: x.mode()[0] if not x.empty else None),
        )
        .reset_index()
    )

    # aggregate items: total item value + freight per order
    items_agg = (
        order_items.groupby("order_id")
        .agg(
            total_items_value=("price", "sum"),
            total_freight=("freight_value", "sum"),
            item_count=("order_item_id", "count"),
        )
        .reset_index()
    )
    items_agg["total_order_value"] = items_agg["total_items_value"] + items_agg["total_freight"]

    # ── DELIVERY DELAY ───────────────────────────
    # only makes sense for delivered orders
    delivered_orders = orders[orders["order_status"] == "delivered"].copy()

    delivered_orders["delivery_delay_days"] = (
        delivered_orders["order_delivered_customer_date"] -
        delivered_orders["order_estimated_delivery_date"]
    ).dt.days

    # positive = late, negative = early, 0 = on time
    delivered_orders["is_late"] = delivered_orders["delivery_delay_days"] > 0

    # ── MERGE CORE ───────────────────────────────
    log.info("Merging orders → customers...")
    fact = orders.merge(customers[["customer_id", "customer_unique_id", "customer_state", "customer_city"]], on="customer_id", how="left")

    log.info("Merging → payment aggregates...")
    fact = fact.merge(payment_agg, on="order_id", how="left")

    log.info("Merging → items aggregates...")
    fact = fact.merge(items_agg, on="order_id", how="left")

    # bring delivery delay info back in
    delay_cols = ["order_id", "delivery_delay_days", "is_late"]
    fact = fact.merge(
        delivered_orders[delay_cols],
        on="order_id",
        how="left"
    )

    # ── REVIEW SCORES ────────────────────────────
    # one review per order (mostly) — taking the latest if there are dupes
    review_agg = (
        reviews.sort_values("review_answer_timestamp")
        .groupby("order_id")
        .agg(review_score=("review_score", "last"))
        .reset_index()
    )
    fact = fact.merge(review_agg, on="order_id", how="left")

    # ── DIM TIME ─────────────────────────────────
    log.info("Building dim_time...")
    all_dates = orders["order_purchase_timestamp"].dropna()
    dim_time = pd.DataFrame({"date": pd.to_datetime(all_dates.dt.date.unique())})
    dim_time["year"] = dim_time["date"].dt.year
    dim_time["month"] = dim_time["date"].dt.month
    dim_time["day"] = dim_time["date"].dt.day
    dim_time["quarter"] = dim_time["date"].dt.quarter
    dim_time["day_of_week"] = dim_time["date"].dt.day_name()
    dim_time["is_weekend"] = dim_time["date"].dt.weekday >= 5
    dim_time["month_name"] = dim_time["date"].dt.month_name()
    dim_time["week_of_year"] = dim_time["date"].dt.isocalendar().week.astype(int)
    dim_time.sort_values("date", inplace=True)
    dim_time.reset_index(drop=True, inplace=True)
    dim_time["time_id"] = dim_time.index + 1

    # ── DIM PRODUCTS (with seller join) ─────────
    # order_items has both product and seller — good for dim_products enrichment
    item_product_seller = order_items[["product_id", "seller_id"]].drop_duplicates()
    dim_products = products.merge(item_product_seller, on="product_id", how="left")

    # ── ORDER DATE KEY ───────────────────────────
    fact["purchase_date"] = fact["order_purchase_timestamp"].dt.normalize()
    fact = fact.merge(
        dim_time[["date", "time_id"]].rename(columns={"date": "purchase_date"}),
        on="purchase_date",
        how="left"
    )

    log.info("Transform complete. fact_orders shape: %s", fact.shape)

    return {
        "fact_orders": fact,
        "dim_customers": customers,
        "dim_products": dim_products,
        "dim_sellers": sellers,
        "dim_time": dim_time,
        "order_items": order_items,  # keeping for detail queries
        "payments": payments,
        "reviews": reviews,
    }



# STEP 4: LOAD TO SQL

def load_to_sql(transformed, db_path=DB_PATH):
    """
    Write transformed dataframes to SQLite.
    Using SQLite for portability — would use Postgres in a real prod setup.
    Schema is defined separately in schema.sql.
    """
    log.info("Loading data to SQLite at: %s", db_path)

    conn = sqlite3.connect(db_path)

    table_map = {
        "fact_orders":    transformed["fact_orders"],
        "dim_customers":  transformed["dim_customers"],
        "dim_products":   transformed["dim_products"],
        "dim_sellers":    transformed["dim_sellers"],
        "dim_time":       transformed["dim_time"],
        "order_items":    transformed["order_items"],
        "payments":       transformed["payments"],
        "reviews":        transformed["reviews"],
    }

    for table_name, df in table_map.items():
        if df.empty:
            log.warning("  Skipping %s — dataframe is empty", table_name)
            continue
        try:
            # convert datetime cols to string for SQLite compatibility
            df_copy = df.copy()
            for col in df_copy.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
                df_copy[col] = df_copy[col].astype(str)
            # bool to int for SQLite
            for col in df_copy.select_dtypes(include=["bool"]).columns:
                df_copy[col] = df_copy[col].astype(int)

            df_copy.to_sql(table_name, conn, if_exists="replace", index=False)
            log.info("  ✓ Wrote %d rows to table: %s", len(df_copy), table_name)
        except Exception as e:
            log.error("  Failed to write %s: %s", table_name, e)

    conn.close()
    log.info("All tables written to database.")


# MAIN

def run_pipeline():
    log.info("=" * 55)
    log.info("Olist ETL Pipeline started at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 55)

    raw = load_data()

    if not raw:
        log.error("No data loaded — check that CSVs exist in /data folder")
        return

    cleaned = clean_data(raw)
    transformed = transform_data(cleaned)
    load_to_sql(transformed)

    log.info("Pipeline finished successfully.")


if __name__ == "__main__":
    run_pipeline()
