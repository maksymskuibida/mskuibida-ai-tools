# unit-claim changelog

## 0.5.0

The claim dialog knows a project's own per-Unit stages (marketplace 1.64.0).

- **Stages from the stage graph.** `claim_choice.py stages` reads `.claude/tools/data/stage-graph.json`: the stages with
  `for_each: "unit-of-work"` except code-generation, in the graph's order, with the graph's names. A plugin's own stage
  (a `demo-assessment` stage after Code Generation, say) is now in the dialog, the recommendation, the typed-answer
  resolver and the claim's `--skip-stages`.
- **Reasons.** A custom stage's reason is the first sentence of its `condition`, cut at a word when long. The four known
  design stages keep their wording.
- **ALWAYS stages.** The engine's `claim --skip-stages` accepts every per-Unit stage but code-generation, so a custom
  `execution: ALWAYS` stage is offered too; the recommender is told it runs for every Unit unless left out.
- **Fallback.** No graph, or one with no per-Unit stage: the four design stages, as before.
- The recorded answer keeps `offered` (the stages it was asked about). The mod's "All four stages" is "All N stages" for another count.
