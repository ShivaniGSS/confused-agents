# Limitations

- **Corpus size:** The observability catalog is intentionally compact (18 scenarios across eight axes). Rates are reported with Wilson confidence intervals; wide intervals indicate limited `n` per cell.
- **Mock MCP:** Tool execution is simulated. Latency, partial failures, and adversarial servers are not modeled unless a scenario encodes them.
- **Model dependence:** Live LLM behavior varies by provider, model version, and prompt. Cached runs replay recorded completions; new models require new runs for valid comparison.
- **Enforcement scope:** The gate applies to tool calls issued by this orchestrator. It does not cover raw network exfiltration, compromised credentials, or hosts outside the mock tool surface.
- **Model safety diagnostic:** `model_safety` summarizes refusal vs. execution from text and tools; it is not a substitute for policy enforcement and can disagree with the execution gate.
- **Token and timing:** Prompt/completion token totals are summed when the provider returns usage; scripted runs report zero tokens. Wall time includes local orchestration and mock servers, not production-scale infrastructure.
- **Adaptive attacker:** Axis E mutates scripted metadata within the harness; it does not implement unconstrained adversarial search over arbitrary prompts.
