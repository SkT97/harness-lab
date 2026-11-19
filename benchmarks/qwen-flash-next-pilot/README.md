# Qwen 3.8 Flash Next pilot

November 18, 2026. A paired comparison of Pi and OpenCode across three public
Exercism tasks, with one run per task and harness. Six of six attempts completed
and passed the independent verifier.

| Harness | Tasks passed | Total wall time (s) | Fresh input tokens | Prompt tokens incl. cache | Output tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pi 1.1.0 | 3/3 | 254.3 | 11,167 | 140,862 | 14,812 |
| OpenCode 2.0.29 | 3/3 | 193.3 | 10,679 | 81,583 | 4,710 |

Across these pairs, OpenCode took 24.0% less wall time and reported 68.2% fewer
output tokens. Fresh input differed by 4.4%. Prompt and output counters describe
usage reported by the harnesses. They are not cost estimates.

## Recompute the comparison

From the repository root:

```sh
uv run --locked harness-lab compare --input benchmarks/qwen-flash-next-pilot/trials.csv --left pi --right opencode
```

The command reads the [six observations](trials.csv) and reproduces the paired
totals without running a model. See the [manifest](manifest.json) for the pinned
data revision, versions, limits and run order.

## How the pilot ran

- Hamming (Python) passed 9 active canonical cases per harness. Raindrops
  (Java) passed 18. Luhn (TypeScript) passed 22.
- For each pair, both harnesses started from the same stub and received the same
  task description. The profile order alternated across tasks.
- Both profiles used the requested model alias `Qwen3.8-Flash-Next`, reasoning
  level `xhigh`, a 131,072-token context and a 32,768-token output limit.
- A verifier outside the agent checkout confirmed the starting stub failed,
  then ran the canonical cases on each candidate. Each passing diff changed
  only the expected source file.
- Wall time comes from the runner and includes service latency. All six
  attempts are included. No network, infrastructure or timeout exclusions
  occurred in this pilot.

The [Exercism problem specifications](https://github.com/exercism/problem-specifications/tree/4812c213a2647e2034ad5ac78155ce9265cdd171)
are the source of the task definitions and canonical cases. This directory
ships the measured observations, so the comparison can be reproduced from
them. It contains neither model weights nor a pinned build of the serving
backend. The sample has one run per pair and public tasks may be familiar to
the model. The results describe this pilot and do not support a general
ranking of harnesses.
