# SWE-bench Verified: which entries can be told apart?

Public per-instance results of 135 SWE-bench Verified submissions, read at a
pinned commit of [SWE-bench/experiments](https://github.com/SWE-bench/experiments/tree/40f164d5b8f1d249bf95a6df8b74b577fd8e519d),
compared pair by pair with `harness-lab verdict`. The question is not who ranks
first but which differences the data can support.

## Result

500 instances, one attempt each, an unresolved instance counts as unresolved.

- The first two entries each resolve 396 of 500. Of the 29 adjacent pairs among
  the top 30, none is distinguishable at alpha 0.05 (exact McNemar, and an exact
  sign test over tasks that gives the same value with one attempt per task). All
  29 are `bounded_null`: a difference larger than 10 percentage points is ruled
  out, nothing smaller.
- The first entry against lower ones, 59 comparisons with Holm adjustment: the
  first rank it is distinguishable from is 12 (374 resolved, adjusted p = 0.025).
  From rank 17 (369 resolved) downward every entry is distinguishable.
- On their own p-value every rank from 9 onward is distinguishable. After the
  Holm adjustment ranks 9 to 11 and 13 to 16 are not. The adjustment is what
  moves the boundary from rank 9 to rank 12, and to rank 17 for a boundary that
  holds from there downward.

[results.json](results.json) holds every pair with its disagreement counts,
p-value, interval and verdict.

An independent audit, [arXiv 2609.17394](https://arxiv.org/abs/2609.17394), reports
the same two facts on its own set of 254 submissions: the leading two Verified
entries each resolve 396 of 500, and exact paired McNemar tests separate none of
the 29 adjacent top-thirty Verified pairs. These figures come from a different
set of submissions and a different tool, so the agreement is a cross-check, not
a copy.

## Reproduce

```sh
uv run --locked python -m examples.swebench_verdict --cache-dir cache --out results.json
```

The script downloads each `results.json` named in [submissions.txt](submissions.txt)
from the pinned commit, over HTTPS, and keeps nothing else. The repository
declares no license, so the data is fetched and not stored here. The run took
about 17 seconds on 19 November 2026.

## Limits

- Submissions listed here are those whose results file is in the Git history at
  that commit. Recent entries keep their results in the submitter's own
  repository and are not included.
- A `bounded_null` verdict rules out large differences only. It does not say the
  two entries are equal, and a larger instance budget could separate them.
- Each entry is a model and scaffold pair run once. The data has no repeats, so
  it says nothing about run-to-run variation, and no timings, so only the
  pass/fail verdict applies.
- Instances an entry does not list as resolved count as unresolved, as on the
  leaderboard, including instances it may not have attempted.
- 59 comparisons against the first entry are adjusted together. The 29 adjacent
  pairs are not adjusted, because none is significant before adjustment.
