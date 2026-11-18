"""Synthetic demonstration with hand-calculated expectations."""

from .compare import compare
from .model import parse_csv_text
from .summarize import summarize

DEMO_CSV_TEXT = "entry_id,task_id,language,variant,repeat,passed,wall_s,tokens_input,tokens_prompt_total,tokens_output,network_error,infra_error,timed_out\n1,T01,Python,agent-a,1,true,10.0,100,200,50,false,false,false\n2,T02,Java,agent-a,1,false,20.0,200,400,100,false,false,false\n3,T03,TypeScript,agent-a,1,true,30.0,300,600,150,false,false,false\n4,T04,Python,agent-a,2,true,40.0,,,,false,false,false\n5,T01,Python,agent-a,2,false,99.0,900,900,900,false,false,true\n6,T01,Python,agent-b,1,true,20.0,120,240,60,false,false,false\n7,T02,Java,agent-b,1,true,10.0,100,200,50,false,false,false\n8,T03,TypeScript,agent-b,1,false,60.0,,500,200,false,false,false\n9,T05,Python,agent-b,2,true,5.0,30,60,15,false,false,false\n10,T05,Python,agent-b,1,true,8.0,40,80,20,false,true,false\n11,T06,Java,agent-b,0,true,1.0,10,20,5,true,false,false\n"
DEMO_EXPECTED = {
    "synthetic": True,
    "summarize.counts.rows_total": 11,
    "summarize.counts.rows_completed": 8,
    "summarize.counts.rows_excluded": 3,
    "summarize.counts.tasks_total": 6,
    "summarize.counts.tasks_completed": 5,
    "summarize.counts.variants_total": 2,
    "summarize.counts.exclusions.network_error": 1,
    "summarize.counts.exclusions.infra_error": 1,
    "summarize.counts.exclusions.timed_out": 1,
    "summarize.overall.passed": 6,
    "summarize.overall.failed": 2,
    "summarize.overall.pass_fraction": 0.75,
    "summarize.overall.wall_s.n": 8,
    "summarize.overall.wall_s.missing": 0,
    "summarize.overall.wall_s.p50": 20.0,
    "summarize.variants.agent-a.rows_total": 5,
    "summarize.variants.agent-a.rows_completed": 4,
    "summarize.variants.agent-a.passed": 3,
    "summarize.variants.agent-a.failed": 1,
    "summarize.variants.agent-a.tokens_input.missing": 1,
    "summarize.variants.agent-b.rows_total": 6,
    "summarize.variants.agent-b.rows_completed": 4,
    "summarize.variants.agent-b.passed": 3,
    "summarize.variants.agent-b.failed": 1,
    "summarize.variants.agent-b.tokens_input.missing": 1,
    "compare.pairing.pairs": 3,
    "compare.pairing.left_unpaired_completed": 1,
    "compare.pairing.right_unpaired_completed": 1,
    "compare.paired_success.left_passed": 2,
    "compare.paired_success.right_passed": 2,
    "compare.comparable": True,
}


def demo_rows():
    return parse_csv_text(DEMO_CSV_TEXT)


def demo_report():
    rows = demo_rows()
    return {
        "synthetic": True,
        "notice": "Synthetic evaluator check; not model performance.",
        "summarize": summarize(rows),
        "compare": compare(rows, "agent-a", "agent-b"),
    }


def self_check(report=None):
    report = demo_report() if report is None else report
    errors = []
    for path, expected in DEMO_EXPECTED.items():
        actual = report
        for key in path.split("."):
            actual = actual[key]
        if actual != expected:
            errors.append(f"{path}: expected {expected!r}, got {actual!r}")
    return errors
