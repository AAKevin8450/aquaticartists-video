# Nova Combined Analysis Prompt

Use this prompt to run a single-pass Nova analysis that returns a unified JSON
payload covering summary, chapters, elements, and waterfall classification.

## Full Instruction (Combined Prompt)

Analyze this video and return a SINGLE JSON object that includes all four analysis sections.

SUMMARY REQUIREMENTS:
- 2-3 sentences, under 50 words. (brief)
- 1-2 paragraphs, around 150 words, include main topic, key points, takeaways. (standard)
- 3-5 paragraphs, around 400 words, include overview, main topics, key points, notable events, conclusions, and timestamps when relevant. (detailed)
- Provide the summary in the target language if specified; otherwise use the video's original language.

CHAPTERS REQUIREMENTS:
- Title (3-8 words), start/end timecodes (MM:SS or HH:MM:SS), summary (2-3 sentences), key points (2-5).
- Chapters should be contiguous and cover the full video without gaps when possible.

ELEMENTS REQUIREMENTS:
- Equipment: name, category, time_ranges, discussed (true/false), confidence (high/medium/low).
- Topics: topic, time_ranges, importance (high/medium/low), description, keywords (3-8 terms).
- People: max_count, multiple_speakers.
- Speakers: speaker_id, role, time_ranges, speaking_percentage.

WATERFALL CLASSIFICATION REQUIREMENTS:
- Follow the sequential 4-step decision process and the spec below.
- Apply Unknown rules and include confidence, evidence, unknown_reasons.

OUTPUT JSON SCHEMA (return ONLY JSON, no markdown):
{
  "summary": {
    "text": "...",
    "depth": "<brief|standard|detailed>",
    "language": "<auto|ISO code>"
  },
  "chapters": {
    "chapters": [
      {
        "index": 1,
        "title": "...",
        "start_time": "00:00",
        "end_time": "03:00",
        "summary": "...",
        "key_points": ["point1", "point2"]
      }
    ]
  },
  "elements": {
    "equipment": [
      {
        "name": "...",
        "category": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "discussed": true,
        "confidence": "high"
      }
    ],
    "topics_discussed": [
      {
        "topic": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "importance": "high",
        "description": "...",
        "keywords": ["..."]
      }
    ],
    "people": {
      "max_count": 2,
      "multiple_speakers": true
    },
    "speakers": [
      {
        "speaker_id": "Speaker_1",
        "role": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "speaking_percentage": 65
      }
    ]
  },
  "waterfall_classification": {
    "family": "...",
    "tier_level": "...",
    "functional_type": "...",
    "sub_type": "...",
    "confidence": {
      "family": 0.0,
      "tier_level": 0.0,
      "functional_type": 0.0,
      "sub_type": 0.0,
      "overall": 0.0
    },
    "evidence": ["..."],
    "unknown_reasons": {}
  }
}

## Waterfall Decision Tree

See:
- docs/Nova_Waterfall_Classification_Decision_Tree.md
- docs/Nova_Waterfall_Classification_Spec.json
