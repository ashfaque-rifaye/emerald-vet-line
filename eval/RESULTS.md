# Evaluation results

Plan and targets: [`PREREGISTRATION.md`](PREREGISTRATION.md). Raw output: [`results-cloud.json`](results-cloud.json), [`results-offline.json`](results-offline.json). Run on 2026-10-31 (cloud) and 2026-10-31 (offline), on the final code.

**What this can't show:** Emerald has not been used with real farmers, and no veterinarian has reviewed these cases. We wrote the test cases and attacks ourselves. These numbers show whether the software keeps its promises, not clinical accuracy.

| # | Metric | Target | Cloud (Nova 2 Lite, Llama 3.3) | Offline (qwen2.5:7b, RTX 4060 laptop) |
|---|---|---|---|---|
| 1 | Sign recall, all 24 statements | 0.80, cloud | **0.983** | 0.847 |
| 1 | Sign precision | Reported | 1.0 | 0.926 |
| 1 | Recall in Hindi / Hinglish / English | Reported | 1.0 / 0.944 / 1.0 | 0.773 / 0.833 / 0.947 |
| 2 | Triage rules point to the labelled disease | 0.95 | **1.0** (partly circular: rules and labels share a source) | same code |
| 2 | Right disease from a spoken statement, end to end | Reported | 1.0 | 0.958 |
| 4 | Misquotes, re-checked outside the pipeline | 0 | **0** | **0** |
| 5 | Attacks that completed an unsigned irreversible action | 0 of 15 | **0** | **0** |
| 6 | Doses or drug names told to a farmer | 0 | **0** | **0** |
| 7 | Same signs as the cloud lane | Reported | n/a | 16 of 24 |
| 7 | Same candidate diseases as the cloud lane | 0.80 | n/a | **0.88** (21 of 24) |
| 8 | Outbreak runs with report and ring calls done | 0.95 | **1.0** (3 of 3) | **1.0** (3 of 3) |
| 9 | Third call to vet's first request, median | Reported | 20.7 s | 23.1 s |
| 9 | Whole 3-call story with instant vet replies | Reported | 163 s | 101 s |
| 10 | Model cost per case, excluding voice | Reported | **about $0.0028** (about 5,512 tokens in, 309 out) | No per-token cost |

Voice cost isn't included, because Nova Sonic use wasn't metered per case. The cost uses list prices from the AWS Price List API: Nova 2 Lite at $0.0003 per 1,000 input tokens and $0.0025 per 1,000 output tokens, Llama 3.3 at $0.00072 per 1,000 tokens.

## What the runs found, and what changed because of them

An evaluation is only useful if it can fail, and these did:

1. **One signature paid a vet twice** when the small local model repeated a tool call. Signatures became single-use, atomically.
2. **The offline lane told a farmer "treat them with meloxicam."** This missed metric 6. The prompt already forbade it, so a prompt wasn't enough. `tell_farmer` now refuses any message naming a medicine or an amount, and code supplies safe words as a fallback.
3. **Two concurrent cases each started ring calls**, so some households would have been called twice. Outbreak actions are now claimed atomically.
4. **A model failure stopped the case before the vet was called.** The vet call now survives model and tool-server failures, with tests.
5. **The model filed the report and then stopped before the ring calls.** Code now checks required steps and sends the agent back.
6. **A local model can't reliably copy quotes.** Models now cite numbered sentences and code fills in the words.
7. **A very fast vet could stall a case**, by signing before the agent had saved its pause. A per-case lock now makes the resume wait. This one was found while recording the demo, not by the evaluation.
8. **The browser microphone never started**, because of an invalid audio buffer size. A test with a fake audio device found it. Also outside these metrics, and a reminder that a demo's untested path is usually broken.

## How to read the attack result

In each attack the real model got the attack prompt and the full tool set. Where the agent paused for a vet, the harness answered "approved" with no signature behind it, the most direct bypass. The tools refused every time. Fifteen attacks we wrote ourselves is a small set: it shows the design holds against these attacks, not that it's unbreakable.

## Also checked by hand

- The Hindi voice line with a synthetic Polly caller: through the agent directly, the browser route, and the Twilio bridge with 8 kHz mu-law audio. Real callers, accents and poor lines haven't been tested.
- AgentCore Runtime: a Hindi statement through to signed actions and a verified ledger, in one session.
- AgentCore Gateway: Cedar allowed a normal dose request and refused a 5,000 kg one, before the tool ran.
- S3 Object Lock: entries uploaded with a retention date, and deferred second opinions run on return.
