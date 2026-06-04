# F-03: TSI Auto-Grader

## Purpose
Present TSI v2.0 CA engine output — score, grade, components, leverage cap.

## Response Structure

### 1. Answer
Score + tier + leverage cap in one line:
> TSI: 72.5/100 → Grade B → Leverage cap 1.5x

### 2. Components
Table of all TSI components with weights, raw values, and weighted scores.

### 3. Tolerance Note
**MANDATORY:** If score is NOT from raw CSV data:
> "This score is reconstructed from summary statistics. Tolerance: ±2–3 points. Golden test reference: PLTR 93.99 ±0.02."

Never present a reconstructed score as exact.

### 4. DQ Triggers
List any data quality triggers that fired:
- PF12 < 1.3
- Sharpe1 < 0
- Net1 < -5%
- MDD > 20%

### 5. Governance
State the governance implications of the grade:
- Grade → leverage cap
- Any DQ triggers that affect eligibility

## Rules

- NEVER present reconstructed score as exact
- Always state tolerance if not from raw CSV
- Cross-check: if TSI is high but P&L is flat, flag the discrepancy
- Golden test reference: PLTR 93.99 ±0.02
