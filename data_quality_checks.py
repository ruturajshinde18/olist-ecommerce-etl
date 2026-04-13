import os
import pandas as pd
import numpy as np
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_raw(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  [SKIP] File not found: {filename}")
        return pd.DataFrame()
    df = pd.read_csv(path)
    print(f"  Loaded {filename}: {df.shape[0]} rows × {df.shape[1]} cols")
    return df


def section(title):
    print(f"\n{'═' * 55}")
    print(f"  {title}")
    print(f"{'═' * 55}")


# NULL ANALYSIS

def null_analysis(df, name):
    section(f"NULL ANALYSIS — {name}")
    null_counts = df.isnull().sum()
    null_pct = (null_counts / len(df) * 100).round(2)

    report = pd.DataFrame({
        "null_count": null_counts,
        "null_pct": null_pct
    }).sort_values("null_pct", ascending=False)

    cols_with_nulls = report[report["null_count"] > 0]
    if cols_with_nulls.empty:
        print("  No nulls found — surprisingly clean!")
    else:
        print(cols_with_nulls.to_string())
        print()

        # flag any critical columns with high null rates
        critical_threshold = 20.0
        high_null = cols_with_nulls[cols_with_nulls["null_pct"] >= critical_threshold]
        if not high_null.empty:
            print(f"  ⚠ Columns with >{critical_threshold}% nulls (worth investigating):")
            for col in high_null.index:
                print(f"     - {col}: {high_null.loc[col, 'null_pct']}%")



# DUPLICATE DETECTION

def duplicate_check(df, name, key_col=None):
    section(f"DUPLICATE CHECK — {name}")

    # full row duplicates
    full_dupes = df.duplicated().sum()
    print(f"  Full row duplicates: {full_dupes}")

    if key_col and key_col in df.columns:
        key_dupes = df.duplicated(subset=key_col).sum()
        print(f"  Duplicates on '{key_col}': {key_dupes}")

        if key_dupes > 0:
            # show a sample of the duplicated keys
            dup_rows = df[df.duplicated(subset=key_col, keep=False)]
            print(f"\n  Sample duplicated {key_col} values:")
            print(dup_rows[key_col].value_counts().head(5).to_string())


# VALUE DISTRIBUTION CHECKS

def value_checks(df, name, cat_cols=None, num_cols=None):
    section(f"VALUE CHECKS — {name}")

    if cat_cols:
        for col in cat_cols:
            if col not in df.columns:
                continue
            print(f"\n  [{col}] unique values: {df[col].nunique()}")
            vc = df[col].value_counts(dropna=False).head(10)
            print(vc.to_string())

    if num_cols:
        print("\n  Numeric column summary:")
        subset = [c for c in num_cols if c in df.columns]
        if subset:
            print(df[subset].describe().round(2).to_string())



# REFERENTIAL INTEGRITY CHECKS

def referential_integrity(orders, customers, order_items, products, sellers):
    section("REFERENTIAL INTEGRITY")

    # orders → customers
    orphan_orders = orders[~orders["customer_id"].isin(customers["customer_id"])]
    print(f"  Orders with no matching customer: {len(orphan_orders)}")
    if not orphan_orders.empty:
        print(f"  ⚠ Sample: {orphan_orders['order_id'].head(3).tolist()}")

    # order_items → orders
    orphan_items = order_items[~order_items["order_id"].isin(orders["order_id"])]
    print(f"  Order items with no matching order: {len(orphan_items)}")

    # order_items → products
    if not products.empty:
        orphan_product_items = order_items[~order_items["product_id"].isin(products["product_id"])]
        print(f"  Order items with no matching product: {len(orphan_product_items)}")

    # order_items → sellers
    if not sellers.empty:
        orphan_seller_items = order_items[~order_items["seller_id"].isin(sellers["seller_id"])]
        print(f"  Order items with no matching seller: {len(orphan_seller_items)}")


# DATE CONSISTENCY CHECKS

def date_consistency(orders):
    section("DATE CONSISTENCY — orders")

    ts_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]

    # parse all timestamps
    for col in ts_cols:
        if col in orders.columns:
            orders[col] = pd.to_datetime(orders[col], errors="coerce")

    # check date range
    if "order_purchase_timestamp" in orders.columns:
        min_date = orders["order_purchase_timestamp"].min()
        max_date = orders["order_purchase_timestamp"].max()
        print(f"  Order date range: {min_date} → {max_date}")

        # orders in the future? shouldn't exist
        future_orders = orders[orders["order_purchase_timestamp"] > datetime.now()]
        if not future_orders.empty:
            print(f"  ⚠ Orders with future timestamps: {len(future_orders)}")

    # delivered BEFORE purchased? that's wrong
    if all(c in orders.columns for c in ["order_purchase_timestamp", "order_delivered_customer_date"]):
        delivered_before_purchase = orders[
            orders["order_delivered_customer_date"] < orders["order_purchase_timestamp"]
        ]
        if not delivered_before_purchase.empty:
            print(f"  ⚠ Orders delivered before purchase: {len(delivered_before_purchase)}")
        else:
            print("  ✓ No orders delivered before purchase date")

    # approved before purchased?
    if all(c in orders.columns for c in ["order_purchase_timestamp", "order_approved_at"]):
        approved_before = orders[
            orders["order_approved_at"] < orders["order_purchase_timestamp"]
        ]
        if not approved_before.empty:
            print(f"  ⚠ Orders approved before purchase timestamp: {len(approved_before)}")
        else:
            print("  ✓ Approval timestamps look fine")

    # estimated delivery in the past (should be future at time of purchase)
    # can't really check this post-hoc accurately, but let's see outliers
    if all(c in orders.columns for c in ["order_purchase_timestamp", "order_estimated_delivery_date"]):
        same_day = orders[
            orders["order_estimated_delivery_date"].dt.date == orders["order_purchase_timestamp"].dt.date
        ]
        print(f"  Estimated delivery = purchase date (suspicious): {len(same_day)}")



# PAYMENT CHECKS

def payment_checks(payments, orders):
    section("PAYMENT CHECKS")

    print(f"  Payment types:\n{payments['payment_type'].value_counts().to_string()}")

    # orders with no payment record
    orders_no_payment = orders[~orders["order_id"].isin(payments["order_id"])]
    print(f"\n  Orders with no payment record: {len(orders_no_payment)}")
    if not orders_no_payment.empty:
        # could be canceled orders — let's check
        status_breakdown = orders_no_payment["order_status"].value_counts()
        print(f"  Status of orders with no payment:\n{status_breakdown.to_string()}")

    # zero or negative payments
    zero_payments = payments[payments["payment_value"] <= 0]
    print(f"\n  Payments with value ≤ 0: {len(zero_payments)}")

    # unusually high payment values — potential data errors
    if "payment_value" in payments.columns:
        p99 = payments["payment_value"].quantile(0.99)
        outliers = payments[payments["payment_value"] > p99 * 3]
        print(f"  Extreme payment values (>3× p99 of {p99:.2f}): {len(outliers)}")
        if not outliers.empty:
            print(outliers[["order_id", "payment_type", "payment_value"]].head(5).to_string())



# REVIEW SCORE DISTRIBUTION

def review_checks(reviews, orders):
    section("REVIEW CHECKS")

    print(f"  Score distribution:\n{reviews['review_score'].value_counts().sort_index().to_string()}")

    # reviews for orders not in the orders table
    orphan_reviews = reviews[~reviews["order_id"].isin(orders["order_id"])]
    print(f"\n  Reviews with no matching order: {len(orphan_reviews)}")

    # orders with multiple reviews (shouldn't really happen but does)
    multi_review = reviews.groupby("order_id").size()
    multi_review_orders = multi_review[multi_review > 1]
    print(f"  Orders with more than 1 review: {len(multi_review_orders)}")
    if not multi_review_orders.empty:
        print(f"  Max reviews for a single order: {multi_review_orders.max()}")
        # honestly not sure what causes this — maybe re-submitted reviews?


# PRODUCT CHECKS

def product_checks(products):
    section("PRODUCT CHECKS")

    print(f"  Total products: {len(products)}")
    print(f"  Unique categories: {products['product_category_name'].nunique()}")

    # products with all dimension info missing
    dim_cols = ["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]
    all_null = products[dim_cols].isnull().all(axis=1).sum()
    print(f"  Products with all dimensions missing: {all_null}")

    # products never ordered — potentially stale catalog
    # (need order_items for this — checked in referential_integrity)



# MAIN

def run_checks():
    print(f"\nData Quality Check — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # load everything raw (no cleaning)
    orders       = load_raw("olist_orders_dataset.csv")
    customers    = load_raw("olist_customers_dataset.csv")
    order_items  = load_raw("olist_order_items_dataset.csv")
    payments     = load_raw("olist_order_payments_dataset.csv")
    reviews      = load_raw("olist_order_reviews_dataset.csv")
    products     = load_raw("olist_products_dataset.csv")
    sellers      = load_raw("olist_sellers_dataset.csv")

    datasets = {
        "orders":      (orders,      "order_id"),
        "customers":   (customers,   "customer_id"),
        "order_items": (order_items, "order_id"),   # not unique, it's composite
        "payments":    (payments,    "order_id"),
        "reviews":     (reviews,     "review_id"),
        "products":    (products,    "product_id"),
        "sellers":     (sellers,     "seller_id"),
    }

    for name, (df, key) in datasets.items():
        if df.empty:
            continue
        null_analysis(df, name)
        duplicate_check(df, name, key_col=key)

    # value distribution spot checks
    if not orders.empty:
        value_checks(orders, "orders",
                     cat_cols=["order_status"],
                     num_cols=[])

    if not payments.empty:
        value_checks(payments, "payments",
                     cat_cols=["payment_type"],
                     num_cols=["payment_value", "payment_installments"])

    if not reviews.empty:
        value_checks(reviews, "reviews",
                     cat_cols=["review_score"],
                     num_cols=[])

    # deeper checks
    if not orders.empty and not customers.empty and not order_items.empty:
        referential_integrity(orders, customers, order_items, products, sellers)

    if not orders.empty:
        date_consistency(orders.copy())

    if not payments.empty and not orders.empty:
        payment_checks(payments, orders)

    if not reviews.empty and not orders.empty:
        review_checks(reviews, orders)

    if not products.empty:
        product_checks(products)

    print("\n" + "=" * 55)
    print("Quality check complete.")
    print("=" * 55)


if __name__ == "__main__":
    run_checks()
