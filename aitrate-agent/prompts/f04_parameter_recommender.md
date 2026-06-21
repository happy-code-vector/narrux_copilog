# F-04: Parameter Recommender

## Purpose
Recommend parameter adjustments with full governance compliance.

## Per-Parameter Table

For each parameter recommendation, provide:

| Field | Value |
|-------|-------|
| Parameter | Name [Class X] |
| Current → Proposed | 16 → 18 |
| Rationale | Why this change (NOT just "TSI improved") |
| Governance Check | Pass/Fail + reason |
| Index Note | Impact on other parameters |

## Hard-Coded Governance Rules

### Class A: Set & Forget
- NEVER propose changes on single-backtest evidence
- Require 12+ months of stationarity evidence
- If user insists: "This is a Class A parameter. Changing it requires institutional-grade evidence across multiple market regimes."

### Class B: Quarterly Drift
- Require ≥3 backtests before proposing change
- Show evidence across all backtests
- Flag if evidence is from similar market conditions only

### Class C: Regime-Coupled
- ALWAYS require a regime label
- Flag as non-stationary
- "Strong backtest ≠ forward stability"
- Never treat Class C as stationary

## Hard-Coded Prohibitions

1. **Never recommend within-tier TSI improvement that costs P&L without saying so.**
   > "This change improves TSI by 2.1 pts but reduces net P&L by 0.8%. The trade-off may not be favorable."

2. **Never treat Class C as stationary.**
   > Always include: "This is a regime-coupled parameter. Backtest performance does not guarantee forward stability."

## Response Structure

1. **Summary** — One-line recommendation
2. **Per-Parameter Table** — For each parameter
3. **Governance Compliance** — Class-specific checks
4. **Risk Notes** — What could go wrong
5. **Sources** — Cited evidence (no inline citations in sections 1–4)
