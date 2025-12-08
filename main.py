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
from output import write_llm_heuristics_output


def main():
    """
    Main execution flow:
    1. Load data from CSVs
    2. Run LLM heuristics (geographical analysis, job pairing)
    3. Output intermediary results
    4. [TODO] Run OR-Tools optimizer
    5. [TODO] Output final schedule
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

    # Step 5: Summary
    print("\n" + "=" * 70)
    print("✅ SPIKE PHASE 1 COMPLETE")
    print("=" * 70)
    print("\nNext Steps:")
    print("  1. Review LLM heuristics output in output/ directory")
    print("  2. Implement constraint validation")
    print("  3. Integrate OR-Tools optimizer")
    print("  4. Generate final schedule")
    print("\n")

    return 0


if __name__ == '__main__':
    sys.exit(main())
