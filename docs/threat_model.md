# Threat model

Mirrors Section 2 of the paper. Authoritative for the artifact: every
mock server, every fixture, every CapGuard module is consistent with
the definitions below.

## Principals

A deployment involves a set of principals
$\mathcal{P} = \{P_1, \dots, P_n\}$. Each principal owns resources
(mailboxes, calendars, documents, payment accounts) and credentials
that authenticate operations on those resources to the resource owner.

## Agent

A single agent operates on behalf of an invoking principal $P_0$.
The agent has access to tools $\mathcal{T} = \{T_1, \dots, T_m\}$.
Each tool call is authenticated to a resource owner via a credential
held by the agent for the session. This is *ambient authority* and is
the deployment pattern of MCP (Model Context Protocol) tool servers.

## Inputs

The agent consumes the initial instruction from $P_0$ plus data
returned from tool calls. Tool-returned data may originate from
arbitrary principals — emails from anyone, document comments from
collaborators, calendar events from any inviter, knowledge-base
entries authored by other tenants.

## Adversary

A principal $P_{\text{adv}} \neq P_0$ who can cause strings to enter
the agent's context through legitimate channels:

* sending an email to $P_0$,
* commenting on a document shared with them,
* creating a calendar event $P_0$ is invited to,
* publishing a knowledge-base entry $P_0$'s tenant subscribes to.

The adversary **cannot** forge credentials, modify the agent's code,
or directly invoke tools. The adversary can only get strings into the
agent's reasoning context.

## Goal

Cause the agent to execute a tool call exercising $P_0$'s (or another
legitimate principal's) authority for an action $P_0$ did not and
would not authorize. We call this a *confused-deputy attack*.

## Out of scope

* Direct prompt injection that overwrites goals outright (orthogonal).
* Credential theft.
* Code execution on the agent host.

## Mapping to the artifact

| Threat-model element | Artifact realization |
|---|---|
| Principals $\mathcal{P}$ | Email addresses with `@example.test` (internal) and other `*.test` TLDs (external). |
| Tools $\mathcal{T}$ | Mock MCP servers in `mock_mcp/{gmail,calendar,drive,payments}_server.py`. |
| Ambient authority | The orchestrator presents one capability token (or none, baseline) for every tool call; the underlying server has no further check. |
| Adversary string-injection | Calendar invite descriptions (scenario A), document comments (B), cross-tenant doc bodies (C). |
| Attack success | Mechanically scored by `harness.run_attack.score_run` against `success.json` predicates. |
