# Olist E-Commerce ETL Pipeline

An end-to-end data pipeline built on the Olist Brazilian E-Commerce public dataset from Kaggle.
The goal was to take a bunch of messy, interconnected CSVs and turn them into something actually useful for analysis.

## What This Project Does

Olist is a Brazilian marketplace that connects small sellers to larger e-commerce platforms.
The dataset covers about 100k orders from 2016 to 2018, across multiple files — orders, customers, products, payments, reviews, sellers, and geolocation.

This pipeline:
1. Loads all the CSV files
2. Cleans them (handles nulls, fixes text formats, converts timestamps)
3. Joins everything into a star schema (fact + dimensions)
4. Creates derived features like delivery delay, is_late flag, and total order value
5. Loads it all into a SQLite database
6. Includes a separate data quality check script you can run before or after

The output is something you can connect Power BI (or any BI tool) to and actually build dashboards from.

## Dataset

Brazilian E-Commerce Public Dataset by Olist
Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

Files used:
- olist_orders_dataset.csv
- olist_customers_dataset.csv
- olist_order_items_dataset.csv
- olist_order_payments_dataset.csv
- olist_order_reviews_dataset.csv
- olist_products_dataset.csv
- olist_sellers_dataset.csv
- olist_geolocation_dataset.csv (loaded but not heavily used)
- product_category_name_translation.csv

## Project Structure

```
/Ecommerce
  pipeline.py              <- main ETL script (load → clean → transform → load to DB)
  schema.sql               <- star schema DDL (tables, indexes, views)
  data_quality_checks.py   <- run this to investigate the raw data
  dashboard_guide.txt      <- Power BI visual specs (what to build and where)
  README.md                <- this file
  /data                    <- put your CSVs here (not included, download from Kaggle)
  olist_warehouse.db       <- output SQLite database (created by pipeline.py)
  pipeline.log             <- runtime log (created when you run the pipeline)
```

---

## How to Run

```bash
# install dependencies
pip install pandas numpy

# put your CSVs in the /data folder, then:
python data_quality_checks.py   # optional but recommended — spot issues early
python pipeline.py              # runs the full ETL
```

After that, `olist_warehouse.db` will have all the tables ready to query or connect to Power BI.

---

## Schema


```
fact_orders (central fact table)
  ├── dim_customers
  ├── dim_products
  ├── dim_sellers
  └── dim_time

Supporting detail tables:
  ├── order_items  (line-level detail, joins to products + sellers)
  ├── payments     (one or more per order)
  └── reviews      (one per order mostly)
```

Key derived columns in `fact_orders`:
- `delivery_delay_days` — actual delivery minus estimated delivery (positive = late)
- `is_late` — 1 if delivered after estimated date
- `total_order_value` — items + freight (from payment aggregation)
- `review_score` — pulled in from latest review per order

---


## Dependencies

- Python 3.8+
- pandas
- numpy
- sqlite3 (built-in)
- logging (built-in)

