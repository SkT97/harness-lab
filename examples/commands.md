# Reproduce the example

All example observations are synthetic. They test the evaluator, not model quality.

```sh
uv run harness-lab demo --csv-out synthetic.csv
uv run harness-lab report --input synthetic.csv
uv run harness-lab compare --input synthetic.csv --left agent-a --right agent-b
```
