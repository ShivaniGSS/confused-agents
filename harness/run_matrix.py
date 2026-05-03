"""Entry-point alias for run_observability_matrix.

``python -m harness.run_matrix`` is the canonical sweep command used in
RESEARCH_PLAN.md and the evaluation scripts.  All logic lives in
run_observability_matrix; this module just re-exports it so both names work.
"""

from harness.run_observability_matrix import _main

if __name__ == "__main__":
    _main()
