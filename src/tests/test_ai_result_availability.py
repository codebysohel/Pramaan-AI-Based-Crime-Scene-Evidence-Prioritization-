from pramaan.guardrail import evaluate_guardrail

def test_needs_review_allows_provisional_triage_but_not_submission():
    rec = {
        'counts': {'m1': 1, 'rules': 2},
        'missing_from_m1': [{'id':'RULE-2','description':'cigarette butt'}],
        'missing_from_rules': [], 'type_conflicts': [], 'quantity_conflicts': [],
        'condition_conflicts': [], 'unclassified_rule_candidates': []
    }
    g = evaluate_guardrail(rec).to_dict()
    assert g['state'] == 'NEEDS_REVIEW'
    assert g['triage_allowed'] is True
    assert g['submission_allowed'] is False

def test_blocked_still_prevents_triage():
    g = evaluate_guardrail(None).to_dict()
    assert g['state'] == 'BLOCKED'
    assert g['triage_allowed'] is False
    assert g['submission_allowed'] is False
