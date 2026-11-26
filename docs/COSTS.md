# Usage and cost estimates

[English README](../README.md) · [中文说明](../README.zh-CN.md)

The response footer totals usage returned by each main generation and separate video, Maps or Python call. A Raycast tool handoff continues the same task; a new user follow-up starts a new task total. Output includes thinking tokens. Tool-use tokens are reconciled against total usage to avoid counting them twice.

## Price book

Checked **2026-11-26** against [Google's official pricing](https://aistudio.google.com/docs/pricing). USD per million tokens, Standard tier:

| Model / effective date | Input | Output including thinking | Cached input |
| --- | ---: | ---: | ---: |
| Carbon through 2026-11-30 | 2.00 | 10.00 | 0.10 |
| Carbon from 2026-12-01 | 4.00 | 20.00 | 0.20 |
| Neon | 3.00 | 15.00 | 0.15 |
| Hydrogen | 1.50 | 7.50 | 0.075 |

The implementation's review window ends on **2026-12-26**. Beyond that date it still reports usage, but stops numeric price estimates until the price book is reviewed. Update `usage_cost.py` and its tests together with this table.

```text
estimate = ((input - cached_input) × input_rate
            + cached_input × cache_rate
            + output_including_thinking × output_rate) / 1,000,000
```

Missing cache counts produce a range. Unreported usage, unknown prices or unreconciled token categories are excluded from the numeric estimate and labelled as unknown. A failed request can incur charges even when no usage is returned.

## What the estimate covers

It estimates **tokens at the dated Standard rates**. Search/Maps query charges, shared free allowances and other unavailable billing details are not included. Check Google's current tool-pricing section and the project's Google billing page for those amounts. A single model request may issue multiple search queries.

Static video normally reads the selected sampled frames and audio. Agentic navigates on demand and may use additional thinking and tool tokens. Which costs less depends on the material and question. Select a short interval when the task is limited to that interval.

Reusing a Files upload avoids sending the file again. Returned cache-token counts determine whether cached-input pricing applies. Follow-ups send stored context; re-analyzing a new video interval creates another video call. The footer is an estimate alongside actual reported token counts; the Google bill remains the authoritative charge record.
