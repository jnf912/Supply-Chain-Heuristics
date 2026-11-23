import pandas as pd
import numpy as np
import math
import os


def simulate_batch_picking_v2_robust():
    print("--- Starting BATCH PICKING Simulation (Robust Overflow Logic) ---")

    # ==========================================
    # 1. CONFIGURATION
    # ==========================================

    BATCH_SIZES = {
        'Forward Picking': 1,
        'Shelves': 6,
        'Racks': 15
    }

    STORE_PROD = {1: 125, 2: 100, 3: 50, 4: 25}
    MIN_PROD = 25
    STORE_COST_PER_H = 12.0

    NET_CAP_BIG = 32.0
    NET_CAP_SMALL = 16.0
    GROSS_CAP_BIG = 40.0
    GROSS_CAP_SMALL = 20.0

    # ==========================================
    # 2. DATA LOADING
    # ==========================================
    try:
        # Load Allocation
        if os.path.exists('optimal_allocation_monthly.csv'):
            df_alloc = pd.read_csv('optimal_allocation_monthly.csv')
        elif os.path.exists('final_allocation.csv'):
            df_alloc = pd.read_csv('final_allocation.csv')
        else:
            print("Error: Allocation file not found. Run optimization first.")
            return

        # Load SKU Master
        df_sku = pd.read_csv('cleaned_portfolio_data.csv')

        # Load Orders
        df_orders = None
        if os.path.exists('Orders from stores.xlsx - Store Orders p.1.csv'):
            o1 = pd.read_csv('Orders from stores.xlsx - Store Orders p.1.csv')
            o2 = pd.read_csv('Orders from stores.xlsx - Store Orders p.2.csv')
            df_orders = pd.concat([o1, o2], ignore_index=True)
        elif os.path.exists('data/orders1.csv'):
            o1 = pd.read_csv('data/orders1.csv')
            o2 = pd.read_csv('data/orders2.csv')
            df_orders = pd.concat([o1, o2], ignore_index=True)
        else:
            # Fallback
            files = [f for f in os.listdir('.') if 'order' in f.lower() and f.endswith('.xlsx')]
            if files:
                print(f"Loading {files[0]}...")
                df_orders = pd.concat(pd.read_excel(files[0], sheet_name=None, engine='openpyxl').values())
            elif os.path.exists('data'):
                files = [f for f in os.listdir('data') if 'order' in f.lower() and f.endswith('.xlsx')]
                if files:
                    print(f"Loading data/{files[0]}...")
                    df_orders = pd.concat(
                        pd.read_excel(os.path.join('data', files[0]), sheet_name=None, engine='openpyxl').values())

        if df_orders is None:
            print("CRITICAL: No order file found.")
            return

    except Exception as e:
        print(f"Error loading: {e}")
        return

    # ==========================================
    # 3. PREPARATION
    # ==========================================
    print("Preparing Batch Data...")

    df_sku['Vol_dm3'] = df_sku['Unit Volume cm3'] / 1000.0
    df_sku_enriched = df_sku.merge(df_alloc[['SKU', 'Area']], on='SKU', how='left').dropna(subset=['Area'])

    # Sort
    df_sku_enriched = df_sku_enriched.sort_values(['Family', 'Total_Lines'], ascending=[True, False])
    sku_seq_map = {sku: i for i, sku in enumerate(df_sku_enriched['SKU'])}

    # Merge
    df_merged = df_orders.merge(df_sku_enriched[['SKU', 'Family', 'Vol_dm3', 'Area']], on='SKU', how='inner')
    df_merged['Sequence'] = df_merged['SKU'].map(sku_seq_map)
    df_merged['Order_ID'] = df_merged['Store ID'].astype(str) + "_" + df_merged['Month Day'].astype(str)

    # ==========================================
    # 4. BATCH SIMULATION ENGINE
    # ==========================================

    areas = df_merged['Area'].unique()

    global_cost = 0
    global_totes = 0
    global_hours = 0
    global_small = 0
    global_big = 0
    global_pure = 0
    total_fill_acc = 0

    print("\nProcessing Areas...")

    for area in areas:
        batch_size = BATCH_SIZES.get(area, 6)
        # print(f"  > Area: {area} (Batch Size: {batch_size})")

        area_data = df_merged[df_merged['Area'] == area].copy()
        unique_orders = area_data['Order_ID'].unique()
        num_batches = math.ceil(len(unique_orders) / batch_size)

        for b in range(num_batches):
            start_idx = b * batch_size
            end_idx = start_idx + batch_size
            batch_orders = unique_orders[start_idx:end_idx]

            batch_lines = area_data[area_data['Order_ID'].isin(batch_orders)].sort_values('Sequence')

            # State
            active_totes = {oid: {'vol': 0, 'fams': set(), 'has_fam1': False, 'lines': 0} for oid in batch_orders}

            # Helper
            def close_tote(tote_state, is_final=False):
                nonlocal global_cost, global_totes, global_hours, global_small, global_big, global_pure, total_fill_acc

                if tote_state['lines'] == 0: return

                n_fam = len(tote_state['fams'])
                if n_fam == 1: global_pure += 1

                vol = tote_state['vol']
                use_small = False
                if is_final and vol <= NET_CAP_SMALL: use_small = True

                if use_small:
                    global_small += 1
                    gross_cap = GROSS_CAP_SMALL
                else:
                    global_big += 1
                    gross_cap = GROSS_CAP_BIG

                total_fill_acc += (vol / gross_cap)

                prod = STORE_PROD.get(n_fam, MIN_PROD) if n_fam < 4 else MIN_PROD
                h = tote_state['lines'] / prod

                global_hours += h
                global_cost += h * STORE_COST_PER_H
                global_totes += 1

                # Reset
                tote_state['vol'] = 0
                tote_state['fams'] = set()
                tote_state['has_fam1'] = False
                tote_state['lines'] = 0

            # --- NEW LOOP LOGIC (Handles Overflow) ---
            for _, line in batch_lines.iterrows():
                oid = line['Order_ID']

                total_line_vol = line['Ordered Units'] * line['Vol_dm3']
                fam = line['Family']
                is_fam1 = (fam == 1)

                remaining_vol = total_line_vol

                while remaining_vol > 0:
                    tote = active_totes[oid]
                    must_close = False

                    # 1. Constraints (Pharma)
                    if tote['has_fam1'] and not is_fam1: must_close = True
                    if len(tote['fams']) > 0 and not tote['has_fam1'] and is_fam1: must_close = True

                    # 2. Capacity Check
                    space_left = NET_CAP_BIG - tote['vol']
                    if space_left <= 0.001: must_close = True

                    if must_close:
                        close_tote(tote, is_final=False)
                        tote = active_totes[oid]
                        space_left = NET_CAP_BIG

                    # 3. Add Chunk
                    vol_to_add = min(remaining_vol, space_left)

                    # Safety valve for items > 32L (should be fixed in cleaning, but just in case)
                    if vol_to_add <= 0:
                        close_tote(tote, is_final=False)
                        tote = active_totes[oid]
                        vol_to_add = min(remaining_vol, NET_CAP_BIG)

                    tote['vol'] += vol_to_add
                    tote['fams'].add(fam)
                    if is_fam1: tote['has_fam1'] = True
                    tote['lines'] += 1

                    remaining_vol -= vol_to_add
            # --- END NEW LOGIC ---

            for oid in batch_orders:
                close_tote(active_totes[oid], is_final=True)

    # ==========================================
    # 5. RESULTS
    # ==========================================

    avg_fill = (total_fill_acc / global_totes) * 100 if global_totes > 0 else 0
    pure_perc = (global_pure / global_totes) * 100 if global_totes > 0 else 0

    print("\n" + "=" * 40)
    print(" FINAL RESULTS (BATCH PICKING - ROBUST V2)")
    print("=" * 40)
    print(f"Total Store Cost:      €{global_cost:,.2f}")
    print(f"Total Replen Hours:    {global_hours:,.1f} h")
    print("-" * 20)
    print(f"Total Totes Shipped:   {global_totes:,}")
    print(f"  > Small Totes:       {global_small:,}")
    print(f"  > Big Totes:         {global_big:,}")
    print("-" * 20)
    print(f"Pure Totes:            {global_pure:,} ({pure_perc:.1f}%)")
    print(f"Gross Fill Rate:       {avg_fill:.1f}%")

    pd.DataFrame([{
        'Metric': 'Batch Picking (Robust V2)',
        'Cost': global_cost,
        'Totes': global_totes,
        'Fill Rate': avg_fill
    }]).to_csv('final_batch_results_robust.csv', index=False)


if __name__ == "__main__":
    simulate_batch_picking_v2_robust()