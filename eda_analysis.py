import os
import warnings
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore")

# config
DATA_DIR  = os.path.join(os.path.dirname(__file__), "data")
PLOT_DIR  = os.path.join(os.path.dirname(__file__), "eda_plots")
os.makedirs(PLOT_DIR, exist_ok=True)

# consistent style across all plots
sns.set_theme(style="darkgrid", palette="muted")
plt.rcParams.update({
    "figure.dpi": 120,
    "figure.figsize": (10, 5),
    "axes.titlesize": 13,
    "axes.labelsize": 11,
})


# helpers

def load(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  [SKIP] {filename} not found")
        return pd.DataFrame()
    return pd.read_csv(path)

def save_plot(name):
    path = os.path.join(PLOT_DIR, f"{name}.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"  saved → eda_plots/{name}.png")

def header(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


# SECTION 1: LOAD & PREP

def load_and_prep():
    """
    Load the files we need and do minimal prep so the EDA is clean.
    Keeping this separate from pipeline.py's clean_data() — I want to look at
    the raw-ish data here, not the fully transformed version.
    """
    header("Loading data")

    orders      = load("olist_orders_dataset.csv")
    customers   = load("olist_customers_dataset.csv")
    items       = load("olist_order_items_dataset.csv")
    payments    = load("olist_order_payments_dataset.csv")
    reviews     = load("olist_order_reviews_dataset.csv")
    products    = load("olist_products_dataset.csv")
    sellers     = load("olist_sellers_dataset.csv")
    translation = load("product_category_name_translation.csv")

    # timestamp parsing — assuming UTC
    ts_cols = [
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    for col in ts_cols:
        if col in orders.columns:
            orders[col] = pd.to_datetime(orders[col], errors="coerce")

    # useful derived columns
    delivered = orders[orders["order_status"] == "delivered"].copy()
    delivered["delivery_delay_days"] = (
        delivered["order_delivered_customer_date"] -
        delivered["order_estimated_delivery_date"]
    ).dt.days
    delivered["is_late"] = delivered["delivery_delay_days"] > 0

    # pull year/month for time series
    orders["purchase_month"] = orders["order_purchase_timestamp"].dt.to_period("M")
    orders["purchase_year"]  = orders["order_purchase_timestamp"].dt.year
    orders["purchase_dow"]   = orders["order_purchase_timestamp"].dt.day_name()
    orders["purchase_hour"]  = orders["order_purchase_timestamp"].dt.hour

    # merge category translation into products
    if not translation.empty and not products.empty:
        products = products.merge(translation, on="product_category_name", how="left")
        products["category_en"] = products["product_category_name_english"].fillna(
            products["product_category_name"]
        )

    # total payment per order
    if not payments.empty:
        pay_agg = payments.groupby("order_id")["payment_value"].sum().reset_index()
        pay_agg.columns = ["order_id", "total_payment"]
    else:
        pay_agg = pd.DataFrame(columns=["order_id", "total_payment"])

    # total items value + freight per order
    if not items.empty:
        items_agg = items.groupby("order_id").agg(
            total_price=("price", "sum"),
            total_freight=("freight_value", "sum"),
            item_count=("order_item_id", "count"),
        ).reset_index()
        items_agg["order_value"] = items_agg["total_price"] + items_agg["total_freight"]
    else:
        items_agg = pd.DataFrame()

    print("\n  Ready. Datasets loaded:")
    for name, df in [("orders", orders), ("customers", customers), ("items", items),
                     ("payments", payments), ("reviews", reviews), ("products", products)]:
        print(f"    {name:12s}: {len(df):>7,} rows")

    return {
        "orders":     orders,
        "delivered":  delivered,
        "customers":  customers,
        "items":      items,
        "items_agg":  items_agg,
        "payments":   payments,
        "pay_agg":    pay_agg,
        "reviews":    reviews,
        "products":   products,
        "sellers":    sellers,
    }


# ════════════════════════════════════════════════════════
# SECTION 2: ORDER VOLUME OVER TIME
# ════════════════════════════════════════════════════════

def orders_over_time(orders):
    header("Order Volume Over Time")

    monthly = (
        orders.groupby("purchase_month")
        .size()
        .reset_index(name="order_count")
    )
    monthly["purchase_month"] = monthly["purchase_month"].astype(str)

    print(f"  Date range: {orders['order_purchase_timestamp'].min().date()} "
          f"→ {orders['order_purchase_timestamp'].max().date()}")
    print(f"  Peak month: {monthly.loc[monthly['order_count'].idxmax(), 'purchase_month']} "
          f"({monthly['order_count'].max():,} orders)")
    print(f"  Quiet month: {monthly.loc[monthly['order_count'].idxmin(), 'purchase_month']} "
          f"({monthly['order_count'].min():,} orders)")

    fig, ax = plt.subplots()
    ax.plot(monthly["purchase_month"], monthly["order_count"], marker="o", ms=4, lw=1.8)
    ax.fill_between(monthly["purchase_month"], monthly["order_count"], alpha=0.15)
    ax.set_title("Monthly Order Volume")
    ax.set_xlabel("Month")
    ax.set_ylabel("Number of Orders")
    # rotate x labels so they don't pile up
    plt.xticks(rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    plt.tight_layout()
    save_plot("01_monthly_order_volume")

    # orders by day of week — does business spike on weekends?
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_counts = orders["purchase_dow"].value_counts().reindex(dow_order)

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(dow_counts.index, dow_counts.values, color=sns.color_palette("muted", 7))
    ax.set_title("Orders by Day of Week")
    ax.set_ylabel("Orders")
    ax.bar_label(bars, fmt="{:,.0f}", fontsize=8, padding=3)
    plt.tight_layout()
    save_plot("02_orders_by_day_of_week")

    # orders by hour — just curious about purchase behaviour
    hour_counts = orders["purchase_hour"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(hour_counts.index, hour_counts.values, color="#5B8DB8", width=0.7)
    ax.set_title("Orders by Hour of Day")
    ax.set_xlabel("Hour (0–23)")
    ax.set_ylabel("Orders")
    ax.set_xticks(range(0, 24))
    plt.tight_layout()
    save_plot("03_orders_by_hour")



# SECTION 3: ORDER VALUE DISTRIBUTION

def order_value_distribution(items_agg, pay_agg):
    header("Order Value Distribution")

    if items_agg.empty or pay_agg.empty:
        print("  Skipping — items or payments data missing")
        return

    ov = items_agg[["order_id", "order_value"]].merge(pay_agg, on="order_id", how="inner")
    ov = ov[ov["order_value"] > 0]  # drop zeros, probably data issues

    # basic stats
    print(f"  Order value stats (BRL):")
    desc = ov["order_value"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
    print(desc.round(2).to_string())

    # skewness — spoiler: it'll be right-skewed
    skew = ov["order_value"].skew()
    print(f"\n  Skewness: {skew:.2f}  {'(right-skewed — expected)' if skew > 1 else ''}")

    # histogram — cap at 99th percentile so the viz is readable
    cap = ov["order_value"].quantile(0.99)
    plot_data = ov[ov["order_value"] <= cap]["order_value"]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(plot_data, bins=60, color="#5B8DB8", edgecolor="white", linewidth=0.4)
    ax.axvline(plot_data.mean(),   color="#E74C3C", ls="--", lw=1.5, label=f"Mean: R${plot_data.mean():.0f}")
    ax.axvline(plot_data.median(), color="#2ECC71", ls="--", lw=1.5, label=f"Median: R${plot_data.median():.0f}")
    ax.set_title("Order Value Distribution (capped at 99th pct)")
    ax.set_xlabel("Order Value (BRL)")
    ax.set_ylabel("Count")
    ax.legend()
    plt.tight_layout()
    save_plot("04_order_value_distribution")

    # log-transformed — helps see the shape better
    ov["log_value"] = np.log1p(ov["order_value"])
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.hist(ov["log_value"], bins=60, color="#8E6DBF", edgecolor="white", linewidth=0.4)
    ax.set_title("Order Value — Log Transformed")
    ax.set_xlabel("log(1 + Order Value)")
    ax.set_ylabel("Count")
    plt.tight_layout()
    save_plot("05_order_value_log_distribution")



# SECTION 4: DELIVERY DELAY ANALYSIS


def delivery_analysis(delivered):
    header("Delivery Delay Analysis")

    if delivered.empty:
        print("  No delivered orders found — skipping")
        return

    delay = delivered["delivery_delay_days"].dropna()

    print(f"  Delivered orders: {len(delivered):,}")
    print(f"  Late deliveries:  {delivered['is_late'].sum():,} "
          f"({delivered['is_late'].mean()*100:.1f}%)")
    print(f"\n  Delay stats (days):")
    print(delay.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_string())

    # delay distribution — show early and late deliveries
    cap_low  = delay.quantile(0.01)
    cap_high = delay.quantile(0.99)
    clipped  = delay.clip(cap_low, cap_high)

    fig, ax = plt.subplots()
    ax.hist(clipped, bins=60, color="#E8834E", edgecolor="white", linewidth=0.4)
    ax.axvline(0,            color="black",   ls="-",  lw=1.2, label="0 = on time")
    ax.axvline(delay.mean(), color="#C0392B", ls="--", lw=1.5, label=f"Mean: {delay.mean():.1f}d")
    ax.set_title("Delivery Delay Distribution (positive = late)")
    ax.set_xlabel("Days (actual − estimated)")
    ax.set_ylabel("Count")
    ax.legend()
    plt.tight_layout()
    save_plot("06_delivery_delay_distribution")

    # late rate by customer state
    if "customer_state" in delivered.columns:
        state_late = (
            delivered.groupby("customer_state")["is_late"]
            .agg(["mean", "count"])
            .rename(columns={"mean": "late_rate", "count": "orders"})
            .sort_values("late_rate", ascending=False)
        )
        # only show states with enough orders to be meaningful
        state_late = state_late[state_late["orders"] >= 100]

        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.barh(state_late.index, state_late["late_rate"] * 100, color="#E8834E")
        ax.set_title("Late Delivery Rate by Customer State (min 100 orders)")
        ax.set_xlabel("Late Rate (%)")
        ax.bar_label(bars, fmt="{:.1f}%", fontsize=8, padding=3)
        plt.tight_layout()
        save_plot("07_late_rate_by_state")


# SECTION 5: REVIEW SCORE ANALYSIS

def review_analysis(reviews, delivered):
    header("Review Score Analysis")

    if reviews.empty:
        print("  No review data — skipping")
        return

    scores = reviews["review_score"].dropna()

    print(f"  Total reviews: {len(reviews):,}")
    print(f"  Score distribution:")
    vc = scores.value_counts().sort_index()
    for score, count in vc.items():
        bar = "█" * int(count / vc.max() * 30)
        print(f"    {int(score)} ★  {bar} {count:,} ({count/len(scores)*100:.1f}%)")

    print(f"\n  Mean score:   {scores.mean():.2f}")
    print(f"  Median score: {scores.median():.0f}")
    # bimodal distribution — most people give 5 or 1, not 3

    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#C0392B", "#E67E22", "#F1C40F", "#2ECC71", "#27AE60"]
    vc.plot(kind="bar", ax=ax, color=colors, edgecolor="white", rot=0)
    ax.set_title("Review Score Distribution")
    ax.set_xlabel("Score")
    ax.set_ylabel("Count")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    for bar in ax.patches:
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 200,
            f"{int(bar.get_height()):,}",
            ha="center", va="bottom", fontsize=8
        )
    plt.tight_layout()
    save_plot("08_review_score_distribution")

    # review score vs delivery delay — is late delivery hurting reviews?
    if not delivered.empty:
        merged = delivered.merge(
            reviews[["order_id", "review_score"]],
            on="order_id", how="inner"
        ).dropna(subset=["delivery_delay_days", "review_score"])

        # bin delay into buckets
        bins   = [-999, -7, 0, 3, 7, 14, 999]
        labels = ["Early >7d", "Early 1-7d", "On Time", "Late 1-3d", "Late 4-7d", "Late >7d"]
        merged["delay_bucket"] = pd.cut(merged["delivery_delay_days"], bins=bins, labels=labels)

        bucket_scores = merged.groupby("delay_bucket")["review_score"].mean()
        print(f"\n  Avg review score by delivery timing:")
        print(bucket_scores.round(2).to_string())

        fig, ax = plt.subplots(figsize=(9, 4))
        bucket_scores.plot(kind="bar", ax=ax, color="#5B8DB8", edgecolor="white", rot=30)
        ax.set_title("Avg Review Score by Delivery Timing")
        ax.set_xlabel("")
        ax.set_ylabel("Avg Review Score")
        ax.set_ylim(1, 5.5)
        ax.axhline(scores.mean(), color="gray", ls="--", lw=1, label=f"Overall avg: {scores.mean():.2f}")
        ax.legend(fontsize=9)
        for bar in ax.patches:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.05,
                f"{bar.get_height():.2f}",
                ha="center", va="bottom", fontsize=8
            )
        plt.tight_layout()
        save_plot("09_review_score_vs_delivery_timing")


# SECTION 6: PAYMENT ANALYSIS

def payment_analysis(payments):
    header("Payment Method Analysis")

    if payments.empty:
        print("  No payment data — skipping")
        return

    print(f"  Payment type breakdown:")
    pt = payments["payment_type"].value_counts()
    print(pt.to_string())

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # left: payment type count
    pt.plot(kind="bar", ax=axes[0], color=sns.color_palette("muted", len(pt)), edgecolor="white", rot=30)
    axes[0].set_title("Payment Method — Order Count")
    axes[0].set_ylabel("Count")
    axes[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    # right: payment value by type
    pv = payments.groupby("payment_type")["payment_value"].sum().sort_values(ascending=False)
    pv.plot(kind="bar", ax=axes[1], color=sns.color_palette("muted", len(pv)), edgecolor="white", rot=30)
    axes[1].set_title("Payment Method — Total Value (BRL)")
    axes[1].set_ylabel("Total BRL")
    axes[1].yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"R${x/1e6:.1f}M"))

    plt.suptitle("Payment Method Overview", y=1.01, fontsize=13)
    plt.tight_layout()
    save_plot("10_payment_method_overview")

    # installments distribution — credit cards only
    cc = payments[payments["payment_type"] == "credit_card"]
    if not cc.empty:
        inst = cc["payment_installments"].value_counts().sort_index().head(12)
        print(f"\n  Credit card installments (top 12 values):")
        print(inst.to_string())

        fig, ax = plt.subplots(figsize=(9, 4))
        inst.plot(kind="bar", ax=ax, color="#5B8DB8", edgecolor="white", rot=0)
        ax.set_title("Credit Card — Installments Distribution")
        ax.set_xlabel("Number of Installments")
        ax.set_ylabel("Count")
        plt.tight_layout()
        save_plot("11_credit_card_installments")


# SECTION 7: PRODUCT CATEGORY ANALYSIS

def category_analysis(items, products):
    header("Product Category Analysis")

    if items.empty or products.empty:
        print("  Skipping — items or products missing")
        return

    merged = items.merge(products[["product_id", "category_en"]], on="product_id", how="left")
    merged["category_en"] = merged["category_en"].fillna("unknown")

    # revenue by category
    cat_rev = (
        merged.groupby("category_en")
        .agg(revenue=("price", "sum"), orders=("order_id", "nunique"))
        .sort_values("revenue", ascending=False)
        .head(15)
    )
    print(f"  Top 15 categories by revenue:")
    print(cat_rev.round(0).to_string())

    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(cat_rev.index[::-1], cat_rev["revenue"][::-1], color="#5B8DB8")
    ax.set_title("Top 15 Categories by Revenue (BRL)")
    ax.set_xlabel("Total Revenue (BRL)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"R${x/1e6:.1f}M"))
    for bar in bars:
        ax.text(
            bar.get_width() + 5000, bar.get_y() + bar.get_height() / 2,
            f"R${bar.get_width()/1e6:.2f}M", va="center", fontsize=7.5
        )
    plt.tight_layout()
    save_plot("12_top_categories_by_revenue")

    # avg price per category — top 15
    cat_price = (
        merged.groupby("category_en")["price"]
        .mean()
        .sort_values(ascending=False)
        .head(15)
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    cat_price[::-1].plot(kind="barh", ax=ax, color="#8E6DBF")
    ax.set_title("Top 15 Categories by Avg Item Price")
    ax.set_xlabel("Avg Price (BRL)")
    plt.tight_layout()
    save_plot("13_top_categories_avg_price")


# SECTION 8: CORRELATION ANALYSIS

def correlation_analysis(items_agg, pay_agg, reviews, delivered):
    header("Correlation Analysis")

    if items_agg.empty or pay_agg.empty or reviews.empty:
        print("  Skipping — need items, payments, and reviews for this")
        return

    # build a per-order feature table
    df = (
        items_agg[["order_id", "order_value", "item_count", "total_freight"]]
        .merge(pay_agg, on="order_id", how="inner")
        .merge(reviews[["order_id", "review_score"]].dropna(), on="order_id", how="inner")
    )

    if not delivered.empty:
        df = df.merge(
            delivered[["order_id", "delivery_delay_days"]].dropna(),
            on="order_id", how="left"
        )

    # only numeric cols
    num_df = df.select_dtypes(include=[np.number]).drop(columns=["order_id"], errors="ignore")

    print(f"\n  Correlation matrix ({len(num_df):,} orders with all fields):")
    corr = num_df.corr().round(3)
    print(corr.to_string())

    print("\n  Correlation with review_score:")
    if "review_score" in corr.columns:
        rv_corr = corr["review_score"].drop("review_score").sort_values()
        for col, val in rv_corr.items():
            direction = "↑ positive" if val > 0 else "↓ negative"
            print(f"    {col:30s}: {val:+.3f}  {direction}")

    # heatmap
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(
        corr, annot=True, fmt=".2f",
        cmap="coolwarm", center=0,
        linewidths=0.5, ax=ax,
        annot_kws={"size": 9}
    )
    ax.set_title("Feature Correlation Matrix")
    plt.tight_layout()
    save_plot("14_correlation_heatmap")

# SECTION 9: BASIC STATISTICAL TESTS

def statistical_tests(delivered, reviews):
    header("Basic Statistical Tests")

    # ── T-TEST: Do late deliveries get lower review scores? ──
    if not delivered.empty and not reviews.empty:
        merged = delivered.merge(
            reviews[["order_id", "review_score"]].dropna(),
            on="order_id", how="inner"
        ).dropna(subset=["is_late"])

        on_time_scores = merged[merged["is_late"] == False]["review_score"]
        late_scores    = merged[merged["is_late"] == True]["review_score"]

        if len(on_time_scores) > 30 and len(late_scores) > 30:
            t_stat, p_val = stats.ttest_ind(on_time_scores, late_scores)

            print("  T-Test: On-time vs Late delivery review scores")
            print(f"    On-time: mean={on_time_scores.mean():.3f}, n={len(on_time_scores):,}")
            print(f"    Late:    mean={late_scores.mean():.3f}, n={len(late_scores):,}")
            print(f"    t-stat: {t_stat:.3f},  p-value: {p_val:.4f}")
            if p_val < 0.05:
                print("    → Statistically significant difference (p < 0.05)")
                print("      Late deliveries do get meaningfully lower scores.")
            else:
                print("    → No significant difference (p ≥ 0.05)")

    # ── PEARSON: delivery delay vs review score ──
    if not delivered.empty and not reviews.empty:
        m2 = delivered.merge(
            reviews[["order_id", "review_score"]].dropna(),
            on="order_id", how="inner"
        ).dropna(subset=["delivery_delay_days", "review_score"])

        if len(m2) > 50:
            r, p = stats.pearsonr(m2["delivery_delay_days"], m2["review_score"])
            print(f"\n  Pearson Correlation: delivery_delay_days × review_score")
            print(f"    r = {r:.4f},  p = {p:.4f}")
            if abs(r) < 0.1:
                strength = "very weak"
            elif abs(r) < 0.3:
                strength = "weak"
            elif abs(r) < 0.5:
                strength = "moderate"
            else:
                strength = "strong"
            print(f"    Interpretation: {strength} {'negative' if r < 0 else 'positive'} relationship")
            # usually weak-to-moderate negative: more delay → slightly lower score
            # the relationship isn't super tight because lots of other factors affect reviews

    # ── SHAPIRO-WILK: Is order value normally distributed? ──
    # (using a sample — Shapiro-Wilk struggles with large N)
    print("\n  Note: Shapiro-Wilk normally requires small samples.")
    print("  Skipping full normality test on order value — use the histogram instead.")
    print("  From the skewness value computed earlier, order value is clearly right-skewed,")
    print("  which is totally expected for e-commerce transaction data.")


# MAIN

def run_eda():
    print("\nOlist E-Commerce — EDA & Statistical Analysis")
    print("=" * 55)

    data = load_and_prep()

    orders_over_time(data["orders"])
    order_value_distribution(data["items_agg"], data["pay_agg"])
    delivery_analysis(data["delivered"])
    review_analysis(data["reviews"], data["delivered"])
    payment_analysis(data["payments"])
    category_analysis(data["items"], data["products"])
    correlation_analysis(data["items_agg"], data["pay_agg"], data["reviews"], data["delivered"])
    statistical_tests(data["delivered"], data["reviews"])

    print("\n" + "=" * 55)
    print(f"EDA complete. Plots saved to: /eda_plots/")
    print("=" * 55)


if __name__ == "__main__":
    run_eda()
