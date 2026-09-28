---
name: exhibit-classification
description: Use when a parsed or triaged exhibit has classification confidence below 0.60, method "fallback" ("Other object"), a parser warning, or when the officer says an exhibit was mis-typed. Confirms the evidence type from the closed Pramaan vocabulary and applies the correction through tools.
user-invocable: true
---

# Exhibit classification

1. Take the head noun and Indian usage terms from the exhibit text (e.g. *beedi*, *gutka packet*, *scooty*, *dupatta*, *DVR*, *FTA card*).
2. Call `lookup_evidence_type(query=<noun>)`. Choose the id whose name and examinations match; never invent an id.
3. Apply it:
   - before triage → `triage_scene(items=[{description, label, type_hint: <id>}], ...)`;
   - after triage → `update_item(case_id, item, changes={"type_hint": "<id>"}, reason="type confirmed with officer")`.
4. Report old type → new type and the new tier/EPI from the tool result.

Cues the engine already uses (explain, do not override): *bloodstained / semen / saliva* add examinations; *burnt* lowers DNA individualisation; "N m from the body" raises probative value (≤ 10 m counts as near the body); "recovered from the accused" adds linkage; "not yet collected/seized" starts a field window.

If no type fits, keep `other_object` and tell the officer the exhibit needs manual scoping by the FSL scene expert.
