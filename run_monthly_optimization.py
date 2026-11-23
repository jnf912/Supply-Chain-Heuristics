import pandas as pd
import pulp
import math
import os


def run_monthly_optimization():
    print("--- 1. STARTING MONTHLY OPTIMIZATION (22 Working Days Capacity) ---")

    # --- CONFIGURATION ---
    WORKING_DAYS = 22.0
    COST_PER_HOUR = 10.0

    # Workforce Capacity (Total Monthly Hours)
    HOURS_PER_DAY = 12
    MONTHLY_HOURS_PER_WORKER = HOURS_PER_DAY * WORKING_DAYS

    EMPLOYEES = {
        'Forward Picking': 12,
        'Shelves': 35,
        'Racks': 12
    }

    # Productivity (Lines/Hour)
    PICK_PROD = {'Forward Picking': 200, 'Shelves': 160, 'Racks': 140}
    REPLEN_RESERVE_PROD = 5.0
    REPLEN_INBOUND_PROD = {'Forward Picking': 10, 'Shelves': 15, 'Racks': 10}

    # Bin Definitions (dm3)
    locations_config = [
        {'j': 'FP_Small', 'Area': 'Forward Picking', 'L_j': 350, 'Q_gross_dm3': 37.26},
        {'j': 'FP_Med', 'Area': 'Forward Picking', 'L_j': 700, 'Q_gross_dm3': 52.33},
        {'j': 'FP_Large', 'Area': 'Forward Picking', 'L_j': 1500, 'Q_gross_dm3': 84.24},
        {'j': 'Shelf_Small', 'Area': 'Shelves', 'L_j': 27000, 'Q_gross_dm3': 26.125},
        {'j': 'Shelf_Large', 'Area': 'Shelves', 'L_j': 4000, 'Q_gross_dm3': 52.25},
        {'j': 'Rack_Small', 'Area': 'Racks', 'L_j': 1500, 'Q_gross_dm3': 336.0},
        {'j': 'Rack_Med', 'Area': 'Racks', 'L_j': 1000, 'Q_gross_dm3': 672.0},
        {'j': 'Rack_Large', 'Area': 'Racks', 'L_j': 150, 'Q_gross_dm3': 1152.0}
    ]
    df_loc = pd.DataFrame(locations_config)
    df_loc['Q_j'] = df_loc['Q_gross_dm3'] * 0.8

    # --- DATA LOADING ---
    try:
        df_sku = pd.read_csv('cleaned_portfolio_data.csv')
    except:
        print("Error: 'cleaned_portfolio_data.csv' not found.")
        return

    # Filter
    df_sku = df_sku[df_sku['Average Stock [Units]'] > 0].copy()

    # Unit Conversions
    df_sku['V_dm3'] = df_sku['Unit Volume cm3'] / 1000.0

    # INDICES
    skus = df_sku['SKU'].tolist()
    locs = df_loc['j'].tolist()
    areas = df_loc['Area'].unique()

    # Lookup dictionaries
    sku_props = df_sku.set_index('SKU')[
        ['V_dm3', 'Total_Lines', 'Total_Units_Ordered', 'Average Stock [Units]']].to_dict('index')
    loc_props = df_loc.set_index('j')[['Q_j', 'Area', 'L_j']].to_dict('index')

    print(f"Allocating {len(skus)} SKUs...")

    # --- MODEL BUILD ---
    prob = pulp.LpProblem("Warehouse_Opt_Monthly", pulp.LpMinimize)
    x = {}
    costs = {}
    hours_impact = {}

    print("Building variables and costs...")
    for i in skus:
        data_i = sku_props[i]
        v_i = data_i['V_dm3']
        monthly_lines = data_i['Total_Lines']
        total_units = data_i['Total_Units_Ordered']
        s_i = data_i['Average Stock [Units]']

        for j in locs:
            data_j = loc_props[j]
            q_j = data_j['Q_j']
            area = data_j['Area']

            if v_i > q_j: continue

            x[(i, j)] = pulp.LpVariable(f"x_{i}_{j}", cat='Binary')

            # Picking
            p_rate = PICK_PROD[area]
            h_pick = monthly_lines / p_rate if p_rate > 0 else 0

            # Replenishment
            total_vol_flow = total_units * v_i
            num_replens = math.floor(total_vol_flow / q_j)

            stock_vol = s_i * v_i
            from_reserve = 1 if stock_vol <= q_j else 0

            r_rate = REPLEN_RESERVE_PROD if from_reserve else REPLEN_INBOUND_PROD[area]
            h_replen = num_replens / r_rate if r_rate > 0 else 0

            total_hours = h_pick + h_replen
            costs[(i, j)] = COST_PER_HOUR * total_hours
            hours_impact[(i, j)] = total_hours

    # Objective
    prob += pulp.lpSum([costs[(i, j)] * x[(i, j)] for (i, j) in costs])

    # Constraints
    print("Adding constraints...")
    # C1: Assign Once
    for i in skus:
        valid_locs = [j for j in locs if (i, j) in x]
        prob += pulp.lpSum([x[(i, j)] for j in valid_locs]) == 1

    # C2: Bin Limits
    for j in locs:
        limit = loc_props[j]['L_j']
        valid_items = [i for i in skus if (i, j) in x]
        prob += pulp.lpSum([x[(i, j)] for i in valid_items]) <= limit

    # C3: Workforce Limits
    for area in areas:
        limit_hours = EMPLOYEES[area] * MONTHLY_HOURS_PER_WORKER
        area_vars = [x[(i, j)] * hours_impact[(i, j)] for (i, j) in x if loc_props[j]['Area'] == area]
        prob += pulp.lpSum(area_vars) <= limit_hours

    print("Solving... (Time Limit 300s)")
    solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=300, gapRel=0.01)
    prob.solve(solver)

    status_str = pulp.LpStatus[prob.status]
    print(f"Optimization Status: {status_str}")

    if status_str not in ['Optimal', 'Not Solved']:
        if status_str == 'Infeasible':
            print("Optimization Failed: Infeasible.")
            return

    # --- SAVE RESULTS ---
    res = []
    print("Extracting results...")
    for (i, j), var in x.items():
        if var.varValue == 1:
            res.append({'SKU': i, 'Bin': j, 'Area': loc_props[j]['Area'], 'Monthly_Cost': costs[(i, j)]})

    df_results = pd.DataFrame(res)
    df_results.to_csv('optimal_allocation_monthly.csv', index=False)
    print(f"Optimization results saved.")

    # ==========================================
    # REPORT GENERATION
    # ==========================================
    print("\n--- GENERATING MONTHLY REPORT ---")

    df_report = df_results.merge(df_sku, on='SKU', how='left')

    report_data = []

    # Metrics Accumulators for final summary
    total_pick_hours = 0
    total_replen_inbound_hours = 0
    total_replen_reserve_hours = 0


    # ... inside your report generation section ...

    total_lines_shipped = df_report['Total_Lines'].sum()
    total_units_shipped = df_report['Total_Units_Ordered'].sum()

    # KPI 1: Cost Per Order Line (The most critical efficiency metric)
    cost_per_line = total_cost / total_lines_shipped if total_lines_shipped > 0 else 0

    # KPI 2: Cost Per Unit (Useful for volume-heavy operations)
    cost_per_unit = total_cost / total_units_shipped if total_units_shipped > 0 else 0

    print("\n--- Efficiency KPIs ---")
    print(f"Total Lines Processed: {total_lines_shipped:,.0f}")
    print(f"Cost Per Order Line:   €{cost_per_line:.4f}")
    print(f"Cost Per Unit:         €{cost_per_unit:.4f}")



    for _, row in df_report.iterrows():
        bin_type = row['Bin']
        area = bins_config_dict(bin_type, locations_config)['Area']
        q_net = bins_config_dict(bin_type, locations_config)['Q_gross_dm3'] * 0.8

        v_dm3 = row['Unit Volume cm3'] / 1000.0
        monthly_lines = row['Total_Lines']
        total_units = row['Total_Units_Ordered']
        avg_stock = row['Average Stock [Units]']

        # Hours Calc
        p_rate = PICK_PROD[area]
        h_pick = monthly_lines / p_rate if p_rate > 0 else 0
        total_pick_hours += h_pick

        total_vol_flow = total_units * v_dm3
        total_replens = math.floor(total_vol_flow / q_net)

        stock_vol = avg_stock * v_dm3
        from_reserve = 1 if stock_vol <= q_net else 0

        if from_reserve:
            r_rate = REPLEN_RESERVE_PROD
            h_replen = total_replens / r_rate if r_rate > 0 else 0
            total_replen_reserve_hours += h_replen
        else:
            r_rate = REPLEN_INBOUND_PROD[area]
            h_replen = total_replens / r_rate if r_rate > 0 else 0
            total_replen_inbound_hours += h_replen

        report_data.append({
            'Area': area,
            'Bin': bin_type,
            'H_Pick': h_pick,
            'H_Replen': h_replen,
            'Total_Hours': h_pick + h_replen
        })

    df_final = pd.DataFrame(report_data)

    print("\n" + "=" * 50)
    print("      WAREHOUSE OPTIMIZATION REPORT (MONTHLY)")
    print("=" * 50)

    # 1. Storage Utilization
    print("\n--- Storage Utilization (Bin Count) ---")
    bin_summary = []
    for loc in locations_config:
        b_name = loc['j']
        capacity = loc['L_j']
        used = len(df_final[df_final['Bin'] == b_name])
        perc = (used / capacity) * 100 if capacity > 0 else 0
        bin_summary.append({'Bin Type': b_name, 'Used': used, 'Capacity': capacity, 'Utilization': f"{perc:.1f}%"})
    print(pd.DataFrame(bin_summary).to_string(index=False))

    # 2. Workforce Utilization
    print("\n--- Workforce Utilization (Monthly Hours) ---")
    area_metrics = df_final.groupby('Area')[['H_Pick', 'H_Replen', 'Total_Hours']].sum().reset_index()
    wf_summary = []
    for _, row in area_metrics.iterrows():
        area = row['Area']
        limit = EMPLOYEES[area] * MONTHLY_HOURS_PER_WORKER
        used = row['Total_Hours']
        perc = (used / limit) * 100 if limit > 0 else 0
        wf_summary.append({
            'Area': area,
            'Limit Hours': limit,
            'Used Hours': f"{used:.1f}",
            'Utilization': f"{perc:.1f}%"
        })
    print(pd.DataFrame(wf_summary).to_string(index=False))

    # 3. Cost Breakdown (NEW SECTION)
    print("\n--- Operational Breakdown ---")
    total_hours = total_pick_hours + total_replen_inbound_hours + total_replen_reserve_hours
    total_cost = total_hours * COST_PER_HOUR

    print(f"Total Monthly Cost: €{total_cost:,.2f}")
    print("-" * 30)
    print(f"Picking:              {total_pick_hours / total_hours:.1%}  (€{total_pick_hours * COST_PER_HOUR:,.2f})")
    print(
        f"Replenishment Total:  {(total_replen_inbound_hours + total_replen_reserve_hours) / total_hours:.1%}  (€{(total_replen_inbound_hours + total_replen_reserve_hours) * COST_PER_HOUR:,.2f})")
    print(
        f"  > From Inbound:     {total_replen_inbound_hours / total_hours:.1%}  (€{total_replen_inbound_hours * COST_PER_HOUR:,.2f})")
    print(
        f"  > From Reserve:     {total_replen_reserve_hours / total_hours:.1%}  (€{total_replen_reserve_hours * COST_PER_HOUR:,.2f})")

    df_final.to_csv('detailed_report_monthly.csv', index=False)
    print("\n[✔] Detailed report saved to 'detailed_report_monthly.csv'")


def bins_config_dict(name, config_list):
    for c in config_list:
        if c['j'] == name: return c
    return None


if __name__ == "__main__":
    run_monthly_optimization()