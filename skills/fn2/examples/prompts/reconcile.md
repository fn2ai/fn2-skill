# Reconcile GAAP and issuer-adjusted earnings

Research ticker $ticker for $period using information published on or before
$as_of. Identify the issuer, fiscal end date, exact GAAP starting measure, and
issuer's adjusted ending measure. Locate the issuer's own reconciliation. If
the period or reconciliation is unavailable by the cutoff, return the gap; do
not reconstruct missing adjustments from a headline. Flag later restatements
and any source whose historical availability cannot be established.

Produce one row per disclosed adjustment: issuer label; signed amount; unit;
tax basis; share-count basis if relevant; source location; explanatory note.
Keep GAAP first. Use the issuer's actual bridge, including explicit tax lines.
Do not add a pretax charge to after-tax EPS or count a tax effect twice. Do not
mix basic and diluted EPS, continuing and total operations, or currency units.
If only an income reconciliation is disclosed, preserve it; derive EPS only
when all necessary tax and denominator information is disclosed and consistent.

Show the arithmetic separately: GAAP starting amount + signed compatible
adjustments = computed ending amount. Compare with the issuer's reported ending
amount and show the residual. Explain rounding only when source precision
supports it. Never alter an adjustment merely to force the bridge to balance.

Compare definitions with the corresponding prior-year period, using recast
figures only when identified. Keep GAAP growth and adjusted growth separate;
avoid conventional growth percentages with a zero or negative denominator.
Record recurring categories without declaring an item one-time or illegal.
An earnings adjustment is not evidence of incremental cash generation.
Finish with unresolved tax, denominator, definition, or disclosure questions.
