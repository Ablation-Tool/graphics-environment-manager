# Unified analytical engine

GEM now has one analytical integration point for live forecasts, saved distributions, evidence memory, advisory policies, spatial alignment, and guarded proposals. It is a deterministic environment for model-assisted investigation, not a claim of consciousness or autonomous understanding.

## One kernel, two forecast providers

`gem.measurement` owns the shared measurement behavior:

- bounded, finite, normalized probability validation;
- strict accessible-volume thresholds and complementary counts;
- entropy, maximum probability, and top-ten probability mass;
- accessible momentum and target-volume suggestions;
- optional observed-token correctness, log loss, and Brier score;
- canonical document hashes and forecast-context binding.

The providers are:

- `gem.prediction.OnnxPredictor`: live local DistilGPT2 ONNX inference for the selected Lab context.
- `gem.volume.VolumeBridge`: saved full-vocabulary NPZ distributions, including independent current and previous keys and feedback from the latest saved observation.

Both use `measure_distribution`. Existing `predict`, `steer`, and `tournament` commands retain their interfaces while using the same kernel. Landmarks remain a separate spatial-analysis capability through `gem.landmarks` and `gem landmarks`.

## Analytical cycle

1. **Observe:** read the selected Lab context or a saved NPZ distribution.
2. **Measure:** record accessible volume, complement, entropy, momentum, and any available outcome metrics.
3. **Advise:** run the existing heuristic steering or equation-sensitivity experiments. Recommendations do not authorize actions.
4. **Propose:** supply a bounded JSON command proposal.
5. **Bind:** connect the forecast to the exact target, selected event, revision, proposal, and action ID.
6. **Review or approve:** deny invalid or stale proposals. Valid proposals remain review-only unless `--approve` is present.
7. **Record:** retain forecast artifacts, decisions, execution receipts, and separate Lab evidence.

The guard supports only:

| Command | Required proposal fields | Effect when approved |
|---|---|---|
| `snapshot` | `command` | Read the current GEM snapshot. |
| `resolve` | `command`, `reference` | Resolve an object in the current snapshot. |
| `begin_selected_work` | `command`, `expected_id`, `expected_revision`, optional `note` | Begin work on the exact selected event. |
| `export` | `command`, `expected_revision` | Export and verify current investigation geometry. |

Other commands, arbitrary shell execution, stale revisions, unknown references, duplicate action IDs, and mismatched forecast contexts are rejected. An approval never converts a failed execution into a successful receipt.

## Commands

Measure live context and optionally score an observed token:

```bash
gem predict --session /path/to/session --actual-token-id 0
```

Measure an NPZ distribution and compare it with an earlier distribution:

```bash
gem volume current.npz \
  --previous earlier.npz \
  --session /path/to/session \
  --key probabilities --previous-key probabilities \
  --min-volume 1 --max-volume 4 \
  --output volume-report.json
```

Review a proposal without executing it:

```bash
gem guard proposal.json \
  --action-id proposal-001 \
  --session /path/to/session \
  --distribution current.npz
```

Approve a valid proposal explicitly:

```bash
gem guard proposal.json \
  --action-id proposal-002 \
  --session /path/to/session \
  --distribution current.npz \
  --approve
```

A valid unapproved review returns zero. A denial or failed execution returns status 2. Every guard run writes a new report under `cognition-runs/` in the session and emits scoped evidence. Reusing an action ID is denied rather than replacing the earlier decision.

## Boundary for a future generative side

A future generative component may produce context, candidate distributions, landmark correspondences, or a proposal document. It must use the same measurement, evidence, and guard interfaces. It does not receive an unrestricted broker or a direct execution path.

That separation supports later hypothesis generation without confusing generated text with verified evidence. It does not establish a complete brain, learning, self-awareness, or general reasoning. Model weights are not trained or updated by this engine.

## Measurement limits

Accessible volume describes the breadth of a particular distribution. It does not establish correctness, safety, maliciousness, authorization, or understanding. Observed-token scoring reports correctness only when the caller supplies the actual token and its vocabulary mapping. A distribution from DistilGPT2 is not automatically a distribution from the embedded agent or a distribution over permitted actions.

Advisory modes and target bands are inspectable heuristics. Equation tournaments measure sensitivity, not superiority. Verified task outcomes and calibration data are required before selecting a policy or claiming improved reasoning.
