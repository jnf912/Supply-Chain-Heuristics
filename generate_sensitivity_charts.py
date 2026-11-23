import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os


def generate_sensitivity_report_final():
    print("--- Generating Full Sensitivity Report (Refined Scale) ---")

    # 1. Load Data
    try:
        # Load the REFINED sensitivity file
        df = pd.read_csv('break_threshold_sensitivity_refined.csv')
    except FileNotFoundError:
        print(
            "Error: 'break_threshold_sensitivity_refined.csv' not found. Please run 'simulate_break_sensitivity_final.py' first.")
        return

    # Clean Threshold column to numeric
    # Handles "20%" -> 20.0
    df['Threshold_Val'] = df['Threshold'].str.rstrip('%').astype(float)

    # ==========================================
    # PART A: PRINT RAW DATA
    # ==========================================
    print("\n--- 1. DETAILED SIMULATION RESULTS ---")
    pd.options.display.float_format = '{:,.1f}'.format

    # Check if 'Replen Hours' exists, if not, skip it
    cols = ['Threshold', 'Store Cost (€)', 'Total Totes', 'Fill Rate %', 'Pure %']
    if 'Replen Hours' in df.columns:
        cols.insert(2, 'Replen Hours')

    print(df[cols].to_string(index=False))

    # ==========================================
    # PART B: GENERATE CHARTS
    # ==========================================
    print("\n--- 2. GENERATING CHARTS ---")

    # Chart 1: Trade-off Curve
    fig, ax1 = plt.subplots(figsize=(10, 6))

    color = '#d62728'  # Red
    ax1.set_xlabel('Break Threshold (% of Gross Capacity)')
    ax1.set_ylabel('Store Labor Cost (€)', color=color, fontweight='bold')
    ax1.plot(df['Threshold_Val'], df['Store Cost (€)'], color=color, marker='o', linewidth=2)
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.grid(True, alpha=0.3)

    ax2 = ax1.twinx()
    color = '#1f77b4'  # Blue
    ax2.set_ylabel('Total Totes Shipped', color=color, fontweight='bold')
    ax2.plot(df['Threshold_Val'], df['Total Totes'], color=color, marker='s', linewidth=2, linestyle='--')
    ax2.tick_params(axis='y', labelcolor=color)

    plt.title('Trade-off: Store Labor vs. Logistics Volume')
    plt.tight_layout()
    plt.savefig('chart_tradeoff_curve.png')
    print("Saved: chart_tradeoff_curve.png")

    # Chart 2: Total Cost Scenarios
    plt.figure(figsize=(10, 6))
    tote_costs = [1.0, 3.0, 5.0, 7.0]

    for cost in tote_costs:
        total = df['Store Cost (€)'] + (df['Total Totes'] * cost)
        plt.plot(df['Threshold_Val'], total, marker='o', linewidth=2, label=f'Tote Cost: €{cost:.2f}')

        # Mark optimal point
        min_idx = total.idxmin()
        plt.plot(df.loc[min_idx, 'Threshold_Val'], total.min(), marker='*', color='gold', markersize=15,
                 markeredgecolor='black')

    plt.xlabel('Break Threshold (%)')
    plt.ylabel('Grand Total Monthly Cost (€)')
    plt.title('Optimal Threshold for Different Tote Costs')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('chart_total_cost_scenarios.png')
    print("Saved: chart_total_cost_scenarios.png")

    # ==========================================
    # PART C: PRINT DECISION MATRIX
    # ==========================================
    print("\n--- 3. OPTIMAL DECISION MATRIX ---")
    print(
        f"{'If Tote Cost is...':<20} | {'Best Threshold':<15} | {'Total Monthly Cost':<20} | {'Savings vs Status Quo':<20}")
    print("-" * 85)

    # Status Quo is now effectively the 80% Threshold (Net Cap Limit)
    status_quo_row = df.iloc[-1]

    for cost in tote_costs:
        col_name = f'Total_€{cost}'
        df[col_name] = df['Store Cost (€)'] + (df['Total Totes'] * cost)

        best_row = df.loc[df[col_name].idxmin()]

        baseline_cost = status_quo_row['Store Cost (€)'] + (status_quo_row['Total Totes'] * cost)
        savings = baseline_cost - best_row[col_name]

        print(f"€{cost:<19.2f} | {best_row['Threshold']:<15} | €{best_row[col_name]:<19,.0f} | €{savings:<19,.0f}")


if __name__ == "__main__":
    generate_sensitivity_report_final()