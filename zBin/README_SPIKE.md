# Van Rental Driver Scheduler - Spike

## Architecture

```
CSV Data → Data Models → LLM Heuristics → [Intermediary Output] → OR-Tools Optimizer → Final Schedule
                              ↓
                    (Optional: Claude API)
                    Parse free-text notes
```

## Running the Spike

### Without LLM Notes Parsing (Free)
```bash
python3 main.py
```

### With LLM Notes Parsing (Requires API Key)
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
python3 main.py
```

## What It Does

### Phase 1: LLM Heuristics (Current)

1. **Geographical Clustering** (Algorithmic)
   - Groups jobs into 14 regions based on postcode areas
   - Calculates cluster centroids

2. **Job Pair Suggestions** (Algorithmic)
   - Identifies 16 potential job chains
   - Finds same-vehicle collection→delivery pairs (high value)
   - Finds nearby delivery→collection pairs (medium value)

3. **Driver-Region Affinity** (Algorithmic)
   - Calculates 164 driver-region affinity scores
   - Based on distance from home + notes matching

4. **Notes Parsing** (LLM-based) 🆕
   - **Requires Anthropic API key**
   - Extracts structured data from free-text notes:
     - Urgency level (low/medium/high/urgent)
     - Constraints (e.g., "vehicle is SORN")
     - Vehicle restrictions (e.g., "must be manual")
     - Special instructions (e.g., "needs cleaning")
     - Warnings (e.g., "flat tyre", "MOT due")
     - Location hints (e.g., "at Putney", "FELTHAM")
   - Cost: ~$0.10-0.50 per run (single API call for all notes)

5. **Impossible Assignments** (Algorithmic)
   - Pre-filters 108 job-driver pairs due to certification mismatches

### Outputs

All outputs are written to `output/` directory with timestamps:

- `llm_01_job_clusters_*.csv` - Geographical groupings
- `llm_02_job_pair_suggestions_*.csv` - Potential job chains
- `llm_03_driver_region_affinity_*.csv` - Driver-region matching
- `llm_04_parsed_notes_*.csv` - **LLM-parsed notes** (only if API key provided)
- `llm_05_impossible_assignments_*.csv` - Pre-filtered assignments

## Example: Notes Parsing Output

**Input (free text):**
```
"FIND A VAN!!"
"SORN Nottingham"
"Needs cleaning - COLL HP18 9UB"
"MOT due"
"at Putney"
```

**Output (structured):**
```csv
job_ref,urgency,warnings,special_instructions,location_hints,summary
#35995475,urgent,"","","","Customer urgently needs vehicle assigned"
#35979670,high,"Vehicle is SORN - cannot be driven on public roads","","Nottingham","Vehicle off-road, must transport on trailer"
#35927198,medium,"","Needs cleaning before delivery","HP18 9UB collection","Clean vehicle after collecting from HP18 9UB"
#35990436,medium,"MOT expiring soon","Check MOT date before long trips","","Vehicle MOT due - avoid long journeys"
#35893131,low,"","","at Putney","Vehicle currently stored at Putney location"
```

## Cost Estimate

- **Algorithmic heuristics**: Free, instant
- **LLM notes parsing**: ~$0.10-0.50 per scheduling run
  - Single API call processes all job notes in batch
  - Uses Claude Sonnet 4.5 (~4000 tokens output)

## Next Steps

- [ ] Add constraint validation module
- [ ] Integrate OR-Tools optimizer
- [ ] Generate final schedule CSV
- [ ] Update product spec with learnings
