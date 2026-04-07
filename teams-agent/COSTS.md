# MayiHear Teams Agent — Cost Analysis

## Test baseline

Largest transcription file: `recordings/transcripcion_2026-03-06.txt`
- **~2 hour meeting** in Spanish
- 138,660 characters · 25,373 words · **~36,000–40,000 tokens**

---

## Token breakdown per workflow

### Workflow 1 — Insights generation (per meeting)
| | Tokens |
|---|---|
| Input: transcription (2h) | ~36,000 |
| Input: system prompt | ~250 |
| **Total input** | **~36,250** |
| Output: JSON insights | ~1,000 |

### Workflow 2 — Q&A Monday (per question)
| Board size | Input tokens | Output tokens |
|---|---|---|
| Small (~50 items) | ~2,500 | ~400 |
| Large (~200 items) | ~10,000 | ~400 |

---

## Cost per call — Model comparison

### Workflow 1: Insights generation (2h meeting)

| Model | Tier | $/MTok in | $/MTok out | Cost/meeting |
|---|---|---|---|---|
| **Claude Haiku 4.5** | Lite | $0.80 | $4.00 | **$0.033** |
| **Claude Sonnet 4.6** ← current | Standard | $3.00 | $15.00 | **$0.124** |
| **Gemini 2.5 Flash** | Lite | $0.15 | $0.60 | **$0.006** |
| **Gemini 2.5 Pro** | Standard | $1.25 | $10.00 | **$0.055** |
| **GPT-4o mini** | Lite | $0.15 | $0.60 | **$0.006** |
| **GPT-4o** | Standard | $2.50 | $10.00 | **$0.101** |

> Equivalent tiers:
> - **Lite:** Claude Haiku 4.5 ≈ Gemini 2.5 Flash ≈ GPT-4o mini
> - **Standard:** Claude Sonnet 4.6 ≈ Gemini 2.5 Pro ≈ GPT-4o

### Workflow 2: Q&A per question (200-item board)

| Model | Cost/question | 5 questions/session |
|---|---|---|
| **Claude Haiku 4.5** | $0.010 | **$0.050** |
| **Claude Sonnet 4.6** ← current | $0.036 | **$0.180** |
| **Gemini 2.5 Flash** | $0.0018 | **$0.009** |
| **GPT-4o mini** | $0.0018 | **$0.009** |

---

## Monthly estimate (10 meetings + 50 Q&A questions/month)

| Model | Insights (10×) | Q&A (50×) | **Total/month** |
|---|---|---|---|
| Claude Haiku 4.5 | $0.33 | $0.50 | **$0.83** |
| **Claude Sonnet 4.6** ← current | $1.24 | $1.80 | **$3.04** |
| Gemini 2.5 Flash | $0.06 | $0.09 | **$0.15** |
| GPT-4o mini | $0.06 | $0.09 | **$0.15** |

---

## Notes

- **Q&A is cheap regardless** of model — board data is small. Cost bottleneck is always insights on long transcripts.
- Gemini 2.5 Flash and GPT-4o mini are ~20× cheaper than Claude Sonnet 4.6.
- For a 2h meeting with dense technical content, lite models may miss nuance — test before switching.
- **Recommended next step:** run Claude Haiku 4.5 vs Sonnet 4.6 on `transcripcion_2026-03-06.txt` and compare output quality. If Haiku holds up, monthly cost drops from ~$3 → ~$0.83 at current usage.
- All estimates assume non-thinking/non-reasoning mode. Gemini 2.5 Flash with thinking enabled costs $3.50/MTok output.
