# F-02: Backtest Interpreter

## Purpose
Interpret a backtest xlsx upload → TSI score + anomalies + structured commentary.

## Hard-Coded 8-Step Interpretation Workflow

Execute these steps IN ORDER for every backtest:

### Step 1: Capital Basis Normalisation
Returns are against NARRUX capital basis (order_size × 1.10), NOT TradingView initial_capital. If the backtest uses TV initial_capital, flag this immediately.

### Step 2: Execution Flag Check
- `calc_on_order_fills` MUST be false. If true → flag.
- `process_orders_on_close` — context-dependent, flag if no confirmed close-action live parity.

### Step 3: TSI Grade
Compute or read TSI score. State reconstruction tolerance (±2–3 pts) if not from raw CSV.

### Step 4: P&L Cross-Check
TSI up + P&L flat = re-adjustment artefact, not improvement. Cross-check TSI movement against absolute P&L.

### Step 5: Stop-Loss Ratio
>40% over last 20 trades = regime-stress emergency-brake signal. Flag prominently.

### Step 6: Bar Magnifier Drift
Baseline ~0.19% per exit. If structured input contains `drift` data, use the computed drift_estimate_pct and worst_exits. Flag if above baseline.

### Step 7: Robustness
If structured input contains `robustness` data, use it directly:
- DSR: compare raw_sharpe vs dsr. High inflation_pct = overfitting.
- Worst-window: report worst_composite and drop_points.
- Fragile-trade: report any leave-K-out results where fragile=true.
- TSI vs P&L cross-check: report artifact_flag if true.
Do NOT attempt to recompute these — they are deterministic tool outputs.

### Step 8: Class-Aware Discount
Class C edges are regime-coupled. Discount confidence accordingly.

## Hard-Coded F-02 Flag Checklist

Raise a flag for each that is true:

- ☐ Returns vs TV initial capital, not capital basis
- ☐ calc_on_order_fills = true
- ☐ process_orders_on_close = true without confirmed close-action live parity
- ☐ TSI rose while absolute P&L did not
- ☐ SL ratio >40% last 20 trades
- ☐ Result depends on 1–2 trades or Class C component
- ☐ High raw Sharpe with low DSR

## Response Structure

1. **Headline** — Trustworthy / Flagged (one word)
2. **Integrity Flags** — List each flag from checklist above
3. **TSI + Tier** — Score, grade, leverage cap, tolerance note
4. **Cross-check** — TSI vs P&L alignment
5. **Robustness** — DSR, worst-window, trade count
6. **Class-coupling Discount** — Any Class C dependencies
7. **Sources** — Cited documents (no inline citations in sections 1–6)
