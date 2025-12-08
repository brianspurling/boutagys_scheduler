#!/usr/bin/env python3
"""
Van Rental Driver Scheduler - Spike

Entry point for the scheduling system.
Demonstrates the hybrid LLM + Optimizer approach.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from data_loader import load_all_data
from distance import DistanceCalculator
from llm_heuristics import LLMHeuristics
from optimizer import ScheduleOptimizer
from output import write_llm_heuristics_output, write_final_schedule


def main():
    """
    Main execution flow:
    1. Load data from CSVs
    2. Run LLM heuristics (geographical analysis, job pairing, notes parsing)
    3. Output intermediary results (5 CSV files)
    4. Run OR-Tools optimizer (job-driver assignments)
    5. Output final schedule
    """
    print("=" * 70)
    print("🚐 VAN RENTAL DRIVER SCHEDULER - SPIKE")
    print("=" * 70)

    # Step 1: Load Data
    print("\n📂 Step 1: Loading data from CSVs...")
    try:
        data = load_all_data('data')
        print(f"  ├─ Loaded {len(data['drivers'])} drivers")
        print(f"  ├─ Loaded {len(data['locations'])} storage locations")
        print(f"  ├─ Loaded {len(data['vehicles'])} vehicles in inventory")
        print(f"  └─ Loaded {len(data['jobs'])} jobs from bookings")
    except Exception as e:
        print(f"  ❌ Error loading data: {e}")
        return 1

    # Step 2: Initialize Distance Calculator
    print("\n📍 Step 2: Initializing distance calculator (mock mode)...")
    distance_calc = DistanceCalculator(use_mock=True)
    print("  └─ Using mock distance calculations (haversine + estimates)")

    # Step 3: Run LLM Heuristics
    print("\n🧠 Step 3: Running LLM Heuristics Analysis...")
    llm = LLMHeuristics(distance_calc)

    try:
        heuristics_result = llm.analyze_jobs(
            data['jobs'],
            data['drivers'],
            data['locations'],
            data['vehicles']
        )
    except Exception as e:
        print(f"  ❌ Error in LLM analysis: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 4: Output LLM Heuristics Results
    print("\n📊 Step 4: Writing LLM Heuristics Output (Intermediary Results)...")
    try:
        write_llm_heuristics_output(heuristics_result, 'output')
    except Exception as e:
        print(f"  ❌ Error writing output: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 5: Run OR-Tools Optimizer
    print("\n🔧 Step 5: Running OR-Tools Optimizer...")
    try:
        optimizer = ScheduleOptimizer(
            data['jobs'],
            data['drivers'],
            data['locations'],
            data['vehicles'],
            distance_calc,
            heuristics_result
        )

        assignments = optimizer.optimize(time_limit_seconds=60)

        if not assignments:
            print("  ❌ Optimizer could not find a feasible schedule")
            return 1

    except Exception as e:
        print(f"  ❌ Error in optimization: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 6: Output Final Schedule
    print("\n📋 Step 6: Writing Final Schedule...")
    try:
        write_final_schedule(assignments, 'output', 'final_schedule_spike.csv')
    except Exception as e:
        print(f"  ❌ Error writing schedule: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 7: Summary
    print("\n" + "=" * 70)
    print("✅ SPIKE COMPLETE - END TO END")
    print("=" * 70)
    print(f"\nGenerated schedule with {len(assignments)} job assignments")
    print("\nOutputs:")
    print("  • LLM Heuristics: output/llm_*_*.csv (5 files)")
    print("  • Final Schedule: output/final_schedule_spike.csv")
    print("\nNext Steps:")
    print("  1. Review final schedule")
    print("  2. Validate against business rules")
    print("  3. Compare with manager's manual schedule")
    print("  4. Identify areas for refinement")
    print("\n")

    return 0


if __name__ == '__main__':
    sys.exit(main())
