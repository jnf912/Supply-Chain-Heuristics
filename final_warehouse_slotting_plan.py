import pandas as pd
import os


def create_slotting_plan(allocation_file, output_filename, scenario_name):
    print(f"\n--- Generating Slotting Plan for: {scenario_name} ---")

    # 1. Load Data
    try:
        if not os.path.exists(allocation_file):
            print(f"Skipping: '{allocation_file}' not found.")
            return

        df_alloc = pd.read_csv(allocation_file)

        if os.path.exists('cleaned_portfolio_data.csv'):
            df_sku = pd.read_csv('cleaned_portfolio_data.csv')
        else:
            print("Error: 'cleaned_portfolio_data.csv' not found.")
            return

    except Exception as e:
        print(f"Error: {e}")
        return

    # 2. Merge Data
    # We need Family and Velocity to apply the sorting logic
    df_merged = df_alloc.merge(df_sku[['SKU', 'Family', 'Total_Lines', 'Unit Volume cm3', 'Average Stock [Units]']],
                               on='SKU', how='left')

    # 3. Define Sorting Heuristic (The "Smart Family" Logic)
    # Priority 1: Physical Zone (You can't jump between zones instantly)
    # Priority 2: Family (Keep families together within the zone)
    # Priority 3: Velocity (Put fast movers at the start of the family block)

    area_order = {'Forward Picking': 1, 'Shelves': 2, 'Racks': 3}
    df_merged['Area_Rank'] = df_merged['Area'].map(area_order)

    df_sorted = df_merged.sort_values(
        by=['Area_Rank', 'Family', 'Total_Lines'],
        ascending=[True, True, False]
    )

    # 4. Generate Physical Addresses (Slot IDs)
    area_codes = {'Forward Picking': 'FP', 'Shelves': 'SH', 'Racks': 'RK'}
    final_plan = []

    for area in ['Forward Picking', 'Shelves', 'Racks']:
        area_df = df_sorted[df_sorted['Area'] == area].copy()
        if area_df.empty: continue

        # Sequence Counter 1..N per zone
        area_df['Sequence_No'] = range(1, len(area_df) + 1)

        # Generate ID: e.g., SH-00125
        code = area_codes.get(area, 'XX')
        area_df['Slot_ID'] = area_df['Sequence_No'].apply(lambda x: f"{code}-{x:05d}")

        final_plan.append(area_df)

    df_final = pd.concat(final_plan)

    # 5. Export
    cols = ['Slot_ID', 'SKU', 'Family', 'Area', 'Bin', 'Total_Lines', 'Unit Volume cm3']
    df_export = df_final[cols]

    df_export.to_csv(output_filename, index=False)
    print(f"[OK] Saved: {output_filename} ({len(df_export)} Slots)")

    # 6. Verify Family 1 Placement
    fam1 = df_final[df_final['Family'] == 1]
    unique_zones = fam1['Area'].unique()
    print(f"   > Verification: Family 1 is located in: {unique_zones}")


def generate_all_slotting_plans():
    # Plan A: Baseline (Optimization only)
    create_slotting_plan(
        allocation_file='optimal_allocation_monthly.csv',
        output_filename='final_slotting_plan_base.csv',
        scenario_name='Baseline (Split Zones)'
    )

    # Plan B: Recommended (Fam 1 -> Shelves)
    create_slotting_plan(
        allocation_file='optimal_allocation_fam1_shelves.csv',
        output_filename='final_slotting_plan_fam1_shelves.csv',
        scenario_name='Recommended (Fam 1 Consolidated)'
    )


if __name__ == "__main__":
    generate_all_slotting_plans()