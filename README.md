# Confused Agents

Reproducible artifact for the paper *Confused Agents*

The artifact contains:

- Four mock MCP servers (gmail, calendar, drive, payments), all
  synthetic and offline. No external services are contacted.
- Two orchestrators (a minimal hand-rolled tool-calling loop and a
  LangGraph-based agent) sharing one tool surface.
- **CapGuard**, a capability-token middleware enforcing
  authority-consistent invocation through data-provenance labels.
- An 18-attack adversarial corpus (3 scenarios × 6 attacks each, 3×3
  factorial: injection style × target irreversibility) plus a
  commit-race case study and a benign workload of 30 tasks.
- A deterministic harness (`k=10`, `temperature=0`, snapshot/restore)
  that runs every attack against every configuration and writes
  JSONL traces.
- A notebook that emits the paper's Tables 1–3 from `results/`.

## Reproduction

```bash
git clone <anonymous-url> && cd confused-agents
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in API keys
bash scripts/run_all.sh
```

`run_all.sh` runs every experiment, generates every table, and writes
final outputs to `paper_outputs/`. Total runtime budget: under 4 hours
on a single machine with API access. LLM responses are cached in
`results/llm_cache/` keyed by hash of (prompt, model, settings).


## Threat model and authority calculus

`docs/threat_model.md` and `docs/authority_calculus.md` mirror Sections
2 and 4 of the paper.

## Anonymity

This artifact is double-blind. Run `bash scripts/verify_anonymity.sh`
before any upload; one hit is desk rejection.
