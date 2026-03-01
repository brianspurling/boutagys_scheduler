"""
LLM-based notes parser using Claude API.

Extracts structured constraints and metadata from free-text job notes.
"""
import os
import json
from typing import List, Dict, Optional
from dataclasses import dataclass

from models import Job


@dataclass
class ParsedNote:
    """Structured information extracted from a job note"""
    job_ref: str
    original_note: str
    urgency: str  # "low", "medium", "high", "urgent"
    constraints: List[str]  # List of constraints extracted
    vehicle_restrictions: List[str]  # e.g., "manual transmission required"
    special_instructions: List[str]  # e.g., "needs cleaning"
    warnings: List[str]  # e.g., "SORN - cannot drive"
    location_hints: List[str]  # e.g., "at Putney", "FELTHAM"
    confidence: str  # "high", "medium", "low"
    summary: str  # One-line summary


class NotesParser:
    """
    Parse job notes using Claude API to extract structured information.

    Batches all notes into a single API call for efficiency.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the notes parser.

        Args:
            api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )

    def parse_all_notes(self, jobs: List[Job]) -> List[ParsedNote]:
        """
        Parse notes for all jobs in a single API call.

        Returns:
            List of ParsedNote objects with structured information
        """
        # Filter jobs with non-empty notes
        jobs_with_notes = [j for j in jobs if j.notes and j.notes.strip()]

        if not jobs_with_notes:
            print("  └─ No notes to parse")
            return []

        print(f"  ├─ Parsing {len(jobs_with_notes)} job notes with Claude API...")

        # Build prompt with all notes
        prompt = self._build_batch_prompt(jobs_with_notes)

        # Call Claude API
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            response_text = response.content[0].text
            parsed_notes = self._parse_response(response_text, jobs_with_notes)

            print(f"  └─ Successfully parsed {len(parsed_notes)} notes")
            return parsed_notes

        except Exception as e:
            print(f"  └─ ⚠️  Error calling Claude API: {e}")
            print(f"      Falling back to empty parse results")
            # Return empty parse results as fallback
            return [self._empty_parse(job) for job in jobs_with_notes]

    def _build_batch_prompt(self, jobs: List[Job]) -> str:
        """Build a prompt that includes all job notes for batch processing"""

        notes_list = []
        for i, job in enumerate(jobs, 1):
            notes_list.append(f"{i}. Job {job.booking_ref}: \"{job.notes}\"")

        notes_text = "\n".join(notes_list)

        prompt = f"""You are analyzing notes from a van rental scheduling system. Each note contains information about a delivery or collection job.

Your task: Extract structured information from each note.

Job Notes:
{notes_text}

For each note, extract:
1. **Urgency**: low/medium/high/urgent (based on caps, exclamation marks, words like "urgent", "asap")
2. **Constraints**: Any restrictions or requirements (e.g., vehicle must be manual, vehicle is SORN, needs cleaning)
3. **Vehicle Restrictions**: Specific vehicle requirements (e.g., manual transmission, towbar needed)
4. **Special Instructions**: Actions needed (e.g., "needs cleaning", "use RRV", "call customer")
5. **Warnings**: Critical issues (e.g., "SORN - cannot drive on road", "flat tyre", "MOT due")
6. **Location Hints**: Storage location mentions (e.g., "at Putney", "FELTHAM location")
7. **Summary**: One-line plain English summary

Return your analysis as a JSON array with this structure:
```json
[
  {{
    "job_number": 1,
    "job_ref": "#35937429",
    "urgency": "low",
    "constraints": ["example constraint"],
    "vehicle_restrictions": [],
    "special_instructions": [],
    "warnings": [],
    "location_hints": [],
    "confidence": "high",
    "summary": "Brief summary of the note"
  }},
  ...
]
```

IMPORTANT: Return ONLY the JSON array, no other text. If a note is empty or unclear, still include an entry with empty arrays."""

        return prompt

    def _parse_response(self, response_text: str, jobs: List[Job]) -> List[ParsedNote]:
        """Parse Claude's JSON response into ParsedNote objects"""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_text = response_text.strip()
            if json_text.startswith('```'):
                # Remove markdown code block markers
                lines = json_text.split('\n')
                json_text = '\n'.join(lines[1:-1])  # Remove first and last line

            parsed_data = json.loads(json_text)

            # Convert to ParsedNote objects
            results = []
            for item in parsed_data:
                # Find corresponding job
                job_ref = item.get('job_ref', '')
                job = next((j for j in jobs if j.booking_ref == job_ref), None)

                if job:
                    results.append(ParsedNote(
                        job_ref=job_ref,
                        original_note=job.notes,
                        urgency=item.get('urgency', 'medium'),
                        constraints=item.get('constraints', []),
                        vehicle_restrictions=item.get('vehicle_restrictions', []),
                        special_instructions=item.get('special_instructions', []),
                        warnings=item.get('warnings', []),
                        location_hints=item.get('location_hints', []),
                        confidence=item.get('confidence', 'medium'),
                        summary=item.get('summary', 'No summary available')
                    ))

            return results

        except json.JSONDecodeError as e:
            print(f"  └─ ⚠️  Failed to parse JSON response: {e}")
            print(f"      Response was: {response_text[:200]}...")
            return [self._empty_parse(job) for job in jobs]

    def _empty_parse(self, job: Job) -> ParsedNote:
        """Create an empty ParsedNote for a job (fallback)"""
        return ParsedNote(
            job_ref=job.booking_ref,
            original_note=job.notes,
            urgency='medium',
            constraints=[],
            vehicle_restrictions=[],
            special_instructions=[],
            warnings=[],
            location_hints=[],
            confidence='low',
            summary='Unable to parse note'
        )
