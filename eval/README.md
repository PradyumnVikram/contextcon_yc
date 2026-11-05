# End-use extraction eval (task B5)

`replies.jsonl` holds **hand-written** buyer replies to an end-use request, one JSON object per line, with the fields a correct extraction should produce. Design rule: a person writes these, never a model, so the eval measures Claude against human judgement.

```json
{"id": "r01", "reply": "...", "parts_needs": ["rf","radar"], "expected": {"end_user_name": "...", "end_user_country": "IN", "evasive": false, "use_specific": true}}
```

- `parts_needs`: the `needs` tags of the parts ordered (what the vocabulary is built from).
- `expected.use_specific`: true if the reply names a real application, false for blank or vague answers ("civilian use").
- Cover these kinds of reply: honest, vague, evasive, forwarded chains, transliterated names, mixed-language (Hindi/English), and a freight forwarder named as the end user. Aim for 30–40 rows.

The 3 rows already in the file are format examples only. Replace or extend them with your own.

Run (needs `ANTHROPIC_API_KEY`; responses are cached in `clearance.db`, so re-runs are free):

```bash
python eval/score.py            # field-level accuracy, plus a list of misses
```

Report only the numbers this script prints.
