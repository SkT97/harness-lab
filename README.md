# harness-lab

Compare coding-agent runs from CSV and get JSON reports that show which runs counted, which tasks matched, and how much data was missing.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). From this repository:

```sh
uv run --locked harness-lab demo
```

Without cloning, `uvx --from git+https://github.com/SkT97/harness-lab harness-lab demo` runs the current main branch.

The offline synthetic example checks hand-calculated counts, outcomes and paired comparisons. It demonstrates evaluator correctness, not model performance.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/wave.svg">
  <img src="assets/wave.svg" alt="Section divider">
</picture>

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/workflow.svg">
  <img src="assets/workflow.svg" alt="Two completed coding-agent runs align by task and repeat before their counters are compared.">
</picture>

Comparisons match task and repeat. Ambiguous pairs are rejected. Missing counters stay missing, with a separate denominator per metric.

<details>
<summary>CSV format and reporting rules</summary>

```sh
uv run --locked harness-lab report --input runs.csv --json-out report.json
uv run --locked harness-lab compare --input runs.csv --left agent-a --right agent-b
```

The [example CSV](examples/synthetic_runs.csv) defines the 13-column input contract. `entry_id` is unique; `repeat` is a nonnegative campaign-local repetition label. Each task has one language. Missing token counters are blank, not zero. Invalid booleans, negative counters, non-finite timings and contradictory metadata fail validation.

| Question | Policy |
| --- | --- |
| Which rows enter metrics? | Completed runs: no network, infrastructure or timeout flag |
| Which outcomes count? | Recorded raw pass/fail; no adjusted success score |
| Which observations are compared? | Exact task/repeat pairs within the two selected variants |
| What if campaign labels collide? | Ambiguous cells with a counterpart are rejected |
| What if counters are missing? | Each metric reports its own paired denominator |
| How are p50/p95 calculated? | R type 7 linear interpolation |
| Is there a global winner? | No ranking across unequal workloads |

A ratio uses sums over the same available paired observations, with right-side zero denominators marked non-comparable. Timing includes completed failures: fast failure is not necessarily useful efficiency. Pair details and raw outcomes remain visible.

</details>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/wave.svg">
  <img src="assets/wave.svg" alt="Section divider">
</picture>

### Import a Harbor job

`harbor-report` reads trial result JSON from
[Harbor v0.26.0](https://github.com/harbor-framework/harbor/blob/v0.26.0/src/harbor/models/trial/result.py).
It looks for `result.json` in each immediate trial directory. The optional
manifest gives the intended trial set, task checksums and configuration names.
Trial directories and `result.json` files that are symlinks or junctions are
skipped and counted in `counts.skipped_links`.

```sh
uv run --locked harness-lab harbor-report --job-dir jobs/example --manifest plan.json
```

The offline example generates a four-trial plan with three observed trials,
two evaluable binary rewards and one success. It reports **1/2** success on
evaluable trials, **1/4** on the plan and **3/4** observed coverage.

```sh
uv run --locked python -m examples.harbor_demo
```

Without a plan, the planned counts and rates are null. Use `--reward-key` for
a different top-level verifier reward. Fractional and missing rewards remain
visible. Trials with exceptions or invalid rewards stay outside the quality
denominator. The adapter exports selected metadata and omits raw logs, URLs
and technical exception messages. Review your task and model labels before
publishing a report.

The [example](examples/harbor_demo.py) shows the manifest format. Its
`trials` list maps each Harbor `trial_name` to both task identity fields,
a configuration label and its repeat. Populate those names from the job
plan or scheduler when measuring coverage.

### Convert Inspect AI logs

```sh
uv run --locked harness-lab inspect-csv --language Python model-a=a.json model-b=b.json --out runs.csv
```

This reads Inspect JSON logs (EvalLog version 2; convert `.eval` logs with `inspect log convert --to json`) and writes the CSV that `compare` and `verdict` read. Inspect logs do not record a language, so `--language` assigns one to every task.

- `task_id` is `<task>/<sample id>`, `repeat` is the epoch, and the variant is the `LABEL` or else the log's model.
- A sample passes on score `C`, `true` or `1` and fails on `I`, `false` or `0`. Anything else, such as `P`, `N` or a fraction, stops the conversion and names the sample. With several scores, choose one with `--score`.
- Wall time is `total_time`, then `working_time`. A completed sample with neither is refused.
- `input_tokens` in Inspect already excludes cached tokens, so it is the fresh input. The prompt total adds cache reads and writes. Tokens are summed over every model in the sample, including a grader model.
- A sample error or an operator stop is an infrastructure exclusion. A `time` or `working` limit is a timeout. Other limits (tokens, messages, turns, cost, context) stay as failed runs.
- A log that did not finish is refused unless you pass `--allow-incomplete`.

Checked against Inspect's own fixture `tests/log/test_eval_log/log_read_sample.json` (repository commit `b392aec` on 19 November 2026) and against synthetic logs in the same shape.

### Compare a local hx run

The [cross-project example](examples/hx_comparison.py) runs the same fixed edit
and verification command on synthetic Python, Java and TypeScript tasks. It
compares running the commands directly with using hx to verify and accept the
patch. Install Git, a JDK with Java source-file support and a Node.js version
with built-in TypeScript stripping. Then run from this checkout:

```sh
uv run --locked python -m examples.hx_comparison --hx-src ../hx/src --out example-results
```

The comparison emits a CSV and the usual paired JSON report. Wall time
includes hx cloning and explicit acceptance for the hx variant. Each repo is
initialized outside the timed section. Runs use a deterministic script in
place of a model, so token fields are empty. This measures local workflow
overhead and checks that both paths deliver the fix. In one Windows run on
November 18, 2026, both paths passed all nine pairs. The mean was 0.425 s
for direct execution and 3.371 s for hx, including its clone and acceptance.

### Can the data tell two agents apart?

```sh
uv run --locked harness-lab verdict --input runs.csv --left agent-a --right agent-b
```

The command pairs pass/fail outcomes by task and repeat and returns one of
four verdicts. `distinguishable` needs both an exact McNemar test on pairs and
an exact sign test on tasks to reject equality, so repeats of one task cannot
fake significance. `bounded_null` means no difference was found and the
confidence interval lies inside the margin (default 0.10), so a larger effect is
ruled out. `underpowered` says the data cannot tell, with the number of tasks
that would be needed when it can be estimated. The estimate is attempted up to 3,000 tasks; beyond that the report says so instead of searching. `no_pairs` means nothing was shared.

`reliability` gives the unbiased pass^k for each variant, for k up to 10: for a task with
s passes in n completed runs it is the chance that k runs drawn without
replacement all pass, C(s, k) / C(n, k), averaged over the tasks with at least k
runs. A system that passes a task once in four tries and one that passes it every
time look the same at k = 1 and very different at k = 4.

The verdict is computed twice: with completed runs only, as in `compare`, and
with every excluded run counted as a failure. If the two differ, the report
says the conclusion depends on the exclusion policy. Options: `--alpha`
(0.05), `--margin` (0.10) and `--power` (0.80). Methods: exact binomial tests,
the [Newcombe (1998)](https://doi.org/10.1002/(SICI)1097-0258(19981130)17:22%3C2635::AID-SIM954%3E3.0.CO;2-C)
interval for paired proportions, and a sample-size search that raises Connor's
(1987) estimate until the exact power reaches the target.

On the [Qwen pilot](benchmarks/qwen-flash-next-pilot/README.md) it reports
`underpowered`: all three pairs passed on both sides, so no pair separates the
agents and no sample size can be estimated.

Time and token counters get their own paired result in `metrics`. Repeats of a
task are averaged on the log scale, then an exact sign test runs over tasks, with a
distribution-free interval for the median ratio (left over right). That interval
needs at least 6 tasks at the default level. Runs with a missing or zero value stay out
of that metric, and each metric reports its own task count. On the pilot, OpenCode
was faster and used fewer output tokens on all 3 tasks, which gives p = 0.25: the
direction is consistent, but 3 tasks cannot support a conclusion. The median of the
per-task ratios differs from the ratio of totals quoted in the pilot table, because
it weighs each task equally.

## Public benchmark example

The [Qwen 3.8 Flash Next pilot](benchmarks/qwen-flash-next-pilot/README.md)
compares Pi and OpenCode on three public tasks in Python, Java and TypeScript.
It includes the six measured observations and the command to reproduce the
paired report.

A second example uses public data: [SWE-bench Verified](benchmarks/swebench-verified/README.md), 135 submissions compared with `verdict`. None of the 29 adjacent pairs among the top 30 can be told apart.

## Verification

The repository includes [synthetic observations](examples/synthetic_runs.csv) for a reproducible walkthrough of validation, exclusions, and matching by task and repeat.

```sh
uv run --locked harness-lab report --input examples/synthetic_runs.csv --json-out report.json
```

The demo and the report illustrate the evaluator's rules. The input is synthetic and does not measure model performance.

<details>
<summary>Development checks</summary>

The runtime uses the Python standard library. A strict CSV contract keeps the evaluator independent of any agent provider or serving stack. Quantiles follow the [R stats definition](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/quantile.html), type 7. Sources reviewed 16 November 2026.

```sh
uv sync --locked --group dev
uv run --locked python -m unittest discover -s tests -t .
uv run --locked ruff check .
uv run --locked ruff format --check .
```

See [verification](docs/verification.md) for local results. CI is configured for Linux and Windows.

</details>

## Limits

This package evaluates recorded observations. It does not execute coding agents or provision models. A valid comparison still depends on matched tasks, comparable conditions, and the checks used to score each run.

The verdict assumes tasks are independent draws from the population you care about and treats the shared task set as the sample. Small paired samples, selection conditional on completion and reused campaign labels limit inference. Future public runs need licensed workloads, immutable revisions, a model/serving snapshot, budgets, independent test contracts and unique campaign identifiers.

<details>
<summary>The spare row · 97</summary>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/side-quest.svg">
  <img src="assets/side-quest.svg" alt="An extra row slides out of a pair and the report remains unchanged.">
</picture>

</details>

## License

[Apache-2.0](LICENSE). The offline demo uses synthetic data. Measured observations are documented in the linked pilot.
