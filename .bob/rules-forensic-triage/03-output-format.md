# Output format

- Lead with a one-line summary: case id, exhibits, P1 count, ACT NOW count.
- Use a Markdown table for ranked exhibits; copy numbers verbatim from tool results.
- Put ACT NOW actions in a numbered list with the exhibit label first.
- End with the integrity line: `KB <first 12 of kb_hash> · result <first 12 of result_sha256> · ledger seq <n>`.
- Case notes go to `case-notes/<case_id>.md` only.
