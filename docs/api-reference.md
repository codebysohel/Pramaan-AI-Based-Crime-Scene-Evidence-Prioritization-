# REST API reference

Base URL `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs`. All bodies are JSON; times ISO-8601 (IST offsets accepted).

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Engine version, KB hash, LLM provider, counts, ledger head, bench hours/day |
| GET | `/api/knowledge/crime-profiles` | Crime profiles |
| GET | `/api/knowledge/evidence-types?q=` | Evidence types (optionally searched) |
| GET | `/api/scenarios`, `/api/scenarios/{name}` | Bundled synthetic scenarios |
| POST | `/api/triage` | Body = `CaseInput` → full `TriageResult` (422 on privacy violation, 400 on bad input) |
| GET | `/api/cases` | Case list with counts |
| GET | `/api/cases/{id}` | `{result, ledger, verify}` |
| POST | `/api/cases/{id}/items/{item}/update` | `{changes, reason}` → re-triaged result |
| POST | `/api/cases/{id}/items/{item}/simulate` | `{condition}` → what-if (not saved) |
| POST | `/api/cases/{id}/items/{item}/custody` | `{event, from_party, to_party, seal_intact, note}` → ledger entry |
| GET | `/api/cases/{id}/packet.pdf` / `packet.md` | FSL submission packet |
| GET | `/api/ledger?case_id=&limit=` | Ledger entries (newest first) |
| GET | `/api/ledger/verify` | Recompute the whole hash chain |
| GET | `/api/lab-queue` | Lab-wide schedule across all cases |
| GET | `/api/benchmark?n=200&seed=2019` | Synthetic benchmark |
| GET | `/api/mcp/tools` | MCP tool catalog |
| POST | `/mcp` | MCP streamable-HTTP endpoint |

`CaseInput` essentials: `case_ref`, `crime_type`, `description` (free text) and/or `items[]` (`description`, `label`, `location`, `quantity`, `collected`, `collected_at`, `condition`, `type_hint`, `override_tier`, `override_reason`), `incident_time`, `reference_time`, `scene {setting, weather, ambient_temp_c}`, `accused_in_custody`, `custody_start`, `max_punishment_years`, `photo_captions[]`.

```bash
curl -s -X POST localhost:8000/api/triage -H 'content-type: application/json' \
  -d @src/scenarios/01_roadside_homicide.json | python -m json.tool | head -40
```
