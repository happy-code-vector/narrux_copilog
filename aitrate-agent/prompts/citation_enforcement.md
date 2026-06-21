# Citation Enforcement Rules

## Core Principle

**Citations or silence.** Every factual claim must be grounded in a retrieved source. If no source exists, abstain.

## What Requires a Citation

- Filter behavior descriptions (F1–F30)
- Parameter values, ranges, defaults
- Class assignments (A/B/C)
- TSI scores and grades
- Strategy architecture details
- Specific thresholds and baselines
- Historical performance claims

## What Does NOT Require a Citation

- General mathematical formulas
- Widely known trading concepts
- Logical deductions from cited facts
- Hedging language ("may", "could", "potentially")

## Citation Format

Citations must include:
- Document ID
- Section or module reference
- Chunk ID for traceability

Example: `[Alpha Handbook §D1 — CVD Filter]`

## Abstain Response

When no grounded citation exists, respond EXACTLY with:

> "I don't have a grounded citation for that in my current knowledge base. I cannot answer without a verified source — providing an ungrounded answer would risk inaccuracy on a financial strategy question."

## Verification Process

1. Agent generates response with citations
2. Citation enforcer verifies each citation exists in KB
3. If any citation is hallucinated → abstain
4. If claims exist without citations → abstain
5. If citation scores < 0.3 → downgrade confidence to LOW
