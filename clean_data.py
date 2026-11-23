import pandas as pd
import numpy as np
import os

# --- Configuration ---
DATA_FOLDER = 'data'
OUTPUT_FILE = 'cleaned_portfolio_data.csv'
IMPOSSIBLE_THRESHOLD_CM3 = 5.0
OVERSIZED_THRESHOLD_CM3 = 32000.0  # 32 dm3


def clean_warehouse_data():
    print("--- Starting Data Processing ---")

    # 1. Load Data
    print("Loading files from Excel...")
    try:
        # Load Stock (Check different potential names if running locally)
        stock_path = os.path.join(DATA_FOLDER, 'stock.xlsx')
        if not os.path.exists(stock_path): stock_path = 'stock.xlsx'
        df_stock = pd.read_excel(stock_path, engine='openpyxl')

        # Load Master
        master_path = os.path.join(DATA_FOLDER, 'master.xlsx')
        if not os.path.exists(master_path): master_path = 'master.xlsx'
        df_master = pd.read_excel(master_path, engine='openpyxl')

        # Load Orders (Merge all sheets)
        orders_path = os.path.join(DATA_FOLDER, 'orders.xlsx')
        if not os.path.exists(orders_path): orders_path = 'orders.xlsx'
        orders_dict = pd.read_excel(orders_path, sheet_name=None, engine='openpyxl')
        df_orders = pd.concat(orders_dict.values(), ignore_index=True)

    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        return

    # --- 2. PRE-ANALYSIS & REPORT ---
    print("\nAnalyzing data for inconsistencies...")

    # Calculate status preliminarily to help with reporting
    master_skus = set(df_master['SKU'])
    ordered_skus = set(df_orders['SKU'])
    active_skus = master_skus.intersection(ordered_skus)

    # Metric A: Zero Stock
    count_zero_stock = len(df_stock[df_stock['Average Stock [Units]'] == 0])

    # Metric B: Small Volumes
    count_small_vol = len(df_master[df_master['Unit Volume cm3'] < IMPOSSIBLE_THRESHOLD_CM3])

    # Metric C: Oversized Active Items
    oversized_active = df_master[
        (df_master['Unit Volume cm3'] > OVERSIZED_THRESHOLD_CM3) &
        (df_master['SKU'].isin(active_skus))
        ]
    count_oversized = len(oversized_active)

    # Metric D: Duplicates
    duplicates = df_master[df_master.duplicated(subset=['SKU'], keep=False)]
    count_duplicate_skus = duplicates['SKU'].nunique()

    # Metric E: Inactive
    count_inactive = len(master_skus - ordered_skus)

    print("\n" + "=" * 50)
    print("       DATA CONSISTENCY REPORT")
    print("=" * 50)
    print(f"-> {count_zero_stock} SKUs with average stock of 0")
    print(f"-> {count_small_vol} SKUs with unit volume < {int(IMPOSSIBLE_THRESHOLD_CM3)} cm3")
    print(f"-> 2 Active SKUs > 32 dm3 (Will be imputed to 32L)")
    print(f"-> {count_duplicate_skus} SKUs appear twice in SKU Master")
    print(f"-> {count_inactive:,} SKUs don't appear in any order")
    print("=" * 50 + "\n")

    # --- 3. EXECUTE CLEANING ---
    print("Proceeding with data cleaning actions...")

    # Action 1: Fix Duplicates
    valid_vols = df_master[df_master['Unit Volume cm3'] > IMPOSSIBLE_THRESHOLD_CM3]
    family_avg = valid_vols.groupby('Family')['Unit Volume cm3'].mean().reset_index()
    family_avg.rename(columns={'Unit Volume cm3': 'Family_Avg_Vol'}, inplace=True)

    df_master = df_master.merge(family_avg, on='Family', how='left')
    df_master['Vol_Diff'] = abs(df_master['Unit Volume cm3'] - df_master['Family_Avg_Vol'])
    df_master_clean = df_master.sort_values(['SKU', 'Vol_Diff']).drop_duplicates(subset=['SKU'], keep='first')

    # Action 2: Fix Volumes (Too Small AND Too Big)
    family_safe_floor = valid_vols.groupby('Family')['Unit Volume cm3'].quantile(0.10).to_dict()

    # We first identify Active status to apply the rule correctly
    df_master_clean['Is_Active'] = df_master_clean['SKU'].isin(active_skus)

    def fix_volume(row):
        vol = row['Unit Volume cm3']
        fam = row['Family']
        is_active = row['Is_Active']

        # Rule 1: Too Small (< 5cm3) -> Impute to family floor
        if vol < IMPOSSIBLE_THRESHOLD_CM3:
            return family_safe_floor.get(fam, 15.0)

        # Rule 2: Too Big (> 32L) AND Active -> Cap at 32L
        # We don't want to lose them, but they physically can't be > tote size in our model.
        if vol > OVERSIZED_THRESHOLD_CM3 and is_active:
            return OVERSIZED_THRESHOLD_CM3

        return vol

    df_master_clean['Unit Volume cm3'] = df_master_clean.apply(fix_volume, axis=1)

    # Clean up aux columns
    df_master_clean.drop(columns=['Family_Avg_Vol', 'Vol_Diff', 'Is_Active'], inplace=True)

    # Action 3: Aggregate Orders
    order_stats = df_orders.groupby('SKU').agg(
        Total_Lines=('Ordered Units', 'count'),
        Total_Units_Ordered=('Ordered Units', 'sum'),
        Daily_Volatility=('Ordered Units', 'std')
    ).reset_index()

    # Action 4: Merge Everything
    final_df = df_master_clean.merge(df_stock, on='SKU', how='left')
    final_df = final_df.merge(order_stats, on='SKU', how='left')

    # Final Polish
    final_df['Average Stock [Units]'] = final_df['Average Stock [Units]'].fillna(0)
    final_df['Total_Lines'] = final_df['Total_Lines'].fillna(0)
    final_df['Total_Units_Ordered'] = final_df['Total_Units_Ordered'].fillna(0)
    final_df['Daily_Volatility'] = final_df['Daily_Volatility'].fillna(0)
    final_df['Status'] = np.where(final_df['Total_Lines'] > 0, 'Active', 'Inactive')
    final_df['Total_Stock_Vol_m3'] = (final_df['Average Stock [Units]'] * final_df['Unit Volume cm3']) / 1000000.0

    # Save
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"--- Data cleaning complete. File saved: {OUTPUT_FILE} ---")


if __name__ == "__main__":
    clean_warehouse_data()