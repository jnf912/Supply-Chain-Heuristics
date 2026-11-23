import pandas as pd
import numpy as np
import math
import os


def simulate_break_sensitivity_final_robust():
    print("--- Starting Sensitivity Analysis (Refined Scale: 0% - 80%, Robust Overflow) ---")

    # 1. CONFIGURATION
    STORE_PROD = {1: 125, 2: 100, 3: 50, 4: 25}
    MIN_PROD = 25
    STORE_COST_PER_H = 12.0

    NET_CAP_BIG = 32.0
    NET_CAP_SMALL = 16.0
    GROSS_CAP_BIG = 40.0
    GROSS_CAP_SMALL = 20.0

    THRESHOLDS = [0.0, 0.20, 0.40, 0.60, 0.80]

    # 2. DATA LOADING
    try:
        # Load Allocation
        if os.path.exists('optimal_allocation_monthly.csv'):
            df_alloc = pd.read_csv('optimal_allocation_monthly.csv')
        else:
            df_alloc = pd.read_csv('final_allocation.csv')

        df_sku = pd.read_csv('cleaned_portfolio_data.csv')

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

    # 3. PREPARATION
    df_sku['Vol_dm3'] = df_sku['Unit Volume cm3'] / 1000.0
    df_sku_enriched = df_sku.merge(df_alloc[['SKU', 'Area']], on='SKU', how='left').dropna(subset=['Area'])

    df_sku_enriched = df_sku_enriched.sort_values(['Family', 'Total_Lines'], ascending=[True, False])
    sku_seq_map = {sku: i for i, sku in enumerate(df_sku_enriched['SKU'])}

    df_merged = df_orders.merge(df_sku_enriched[['SKU', 'Family', 'Vol_dm3', 'Area']], on='SKU', how='inner')
    df_merged['Sequence'] = df_merged['SKU'].map(sku_seq_map)
    df_merged['Order_ID'] = df_merged['Store ID'].astype(str) + "_" + df_merged['Month Day'].astype(str)

    # 4. SIMULATION LOOP
    df_sim = df_merged.sort_values(['Order_ID', 'Area', 'Sequence'])

    arr_oids = df_sim['Order_ID'].values
    arr_areas = df_sim['Area'].values
    arr_vols = (df_sim['Vol_dm3'] * df_sim['Ordered Units']).values
    arr_fams = df_sim['Family'].values

    results = []

    for thresh in THRESHOLDS:
        print(f"Simulating Threshold: {thresh * 100:.0f}%...")

        tot_cost = 0
        tot_totes = 0
        tot_pure = 0
        tot_fill_acc = 0
        tot_replen_hours = 0

        cur_oid = None
        cur_area = None
        tote_vol = 0
        tote_fams = set()
        tote_fam1 = False
        tote_lines = 0

        def close_tote(lines, families, volume, is_final=False):
            nonlocal tot_cost, tot_totes, tot_pure, tot_fill_acc, tot_replen_hours
            if lines == 0: return

            if len(families) == 1: tot_pure += 1

            use_small = False
            if is_final and volume <= NET_CAP_SMALL: use_small = True
            gross_cap = GROSS_CAP_SMALL if use_small else GROSS_CAP_BIG
            tot_fill_acc += (volume / gross_cap)

            n_fam = len(families)
            prod = STORE_PROD.get(n_fam, MIN_PROD) if n_fam < 4 else MIN_PROD

            h = lines / prod
            tot_replen_hours += h
            tot_cost += h * STORE_COST_PER_H
            tot_totes += 1

        n = len(arr_oids)
        for i in range(n):
            oid = arr_oids[i]
            area = arr_areas[i]
            vol = arr_vols[i]
            fam = arr_fams[i]
            is_fam1 = (fam == 1)

            if oid != cur_oid or area != cur_area:
                close_tote(tote_lines, tote_fams, tote_vol, is_final=True)
                cur_oid, cur_area = oid, area
                tote_vol, tote_fams, tote_fam1, tote_lines = 0, set(), False, 0

            # --- NEW OVERFLOW LOGIC ---
            total_line_vol = vol  # from pre-calc array
            remaining_vol = total_line_vol

            while remaining_vol > 0:
                must_close = False

                # 1. Family Constraints
                if tote_fam1 and not is_fam1: must_close = True
                if len(tote_fams) > 0 and not tote_fam1 and is_fam1: must_close = True

                # 2. Threshold Logic
                if not must_close and len(tote_fams) > 0 and fam not in tote_fams:
                    current_fill = tote_vol / GROSS_CAP_BIG
                    if current_fill >= thresh: must_close = True

                # 3. Capacity Check (Space Left)
                space_left = NET_CAP_BIG - tote_vol
                if space_left <= 0.001: must_close = True

                if must_close:
                    close_tote(tote_lines, tote_fams, tote_vol, is_final=False)
                    tote_vol, tote_fams, tote_fam1, tote_lines = 0, set(), False, 0
                    space_left = NET_CAP_BIG  # Reset space

                # 4. Add Chunk
                vol_to_add = min(remaining_vol, space_left)

                # Safety for >32L items
                if vol_to_add <= 0:
                    close_tote(tote_lines, tote_fams, tote_vol, is_final=False)
                    tote_vol, tote_fams, tote_fam1, tote_lines = 0, set(), False, 0
                    vol_to_add = min(remaining_vol, NET_CAP_BIG)

                tote_vol += vol_to_add
                tote_fams.add(fam)
                if is_fam1: tote_fam1 = True
                tote_lines += 1

                remaining_vol -= vol_to_add
            # --- END NEW LOGIC ---

        close_tote(tote_lines, tote_fams, tote_vol, is_final=True)

        avg_fill = (tot_fill_acc / tot_totes) * 100 if tot_totes > 0 else 0
        results.append({
            'Threshold': f"{thresh * 100:.0f}%",
            'Store Cost (€)': tot_cost,
            'Replen Hours': tot_replen_hours,
            'Total Totes': tot_totes,
            'Fill Rate %': avg_fill,
            'Pure %': (tot_pure / tot_totes) * 100
        })

    df_res = pd.DataFrame(results)

    print("\n--- SENSITIVITY RESULTS (Refined Scale, Robust) ---")
    pd.options.display.float_format = '{:,.2f}'.format
    print(df_res.to_string(index=False))
    df_res.to_csv('break_threshold_sensitivity_refined.csv', index=False)


if __name__ == "__main__":
    simulate_break_sensitivity_final_robust()