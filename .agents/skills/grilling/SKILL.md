---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Each question should be formatted like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment, inspect it with the available tools; don't ask the user for anything you can look up yourself. Only questions downstream of an unresolved fact should wait; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

Start with the prompt and facts already in context; do not inventory the environment before Round 1. Ambiguity about what the user means or which scope they intend is a decision question, not a fact gap: ask it on the current frontier and defer its dependent branches. Do not inspect the environment to identify an unspecified subject or guess which project the user meant; when no path, symbol, command, or source is named, ask for one in Round 1. Inspect the environment only when a recommendation on the current frontier materially depends on a concrete, verifiable fact. Use the narrowest named source and stop as soon as it answers that question; do not search unrelated repositories, history, policy, or CI merely to manufacture context. Cite only evidence that changes a question or recommendation.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.
