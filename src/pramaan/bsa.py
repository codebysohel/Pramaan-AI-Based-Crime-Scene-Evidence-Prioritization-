"""Evidence authenticity & reliability under the Bharatiya Sakshya Adhiniyam, 2023 (BSA).

BSA replaced the Indian Evidence Act, 1872 from 1 July 2024. For electronic / digital records:

    §61     an electronic or digital record is not denied admissibility merely because it is electronic;
            subject to §63 it has the same legal effect as other documents
    §62     contents of electronic records may be proved in accordance with §63
    §63(1)  a computer output (printed, stored, recorded or copied) is deemed a document and admissible
            without further proof of the original if the conditions of §63 are satisfied
    §63(2)  (a) regular use of the device for an activity regularly carried on by the person in lawful control
            (b) information of that kind regularly fed in the ordinary course of those activities
            (c) the device operated properly, or any malfunction did not affect the record / its accuracy
            (d) the record reproduces or is derived from information fed in the ordinary course
    §63(4)  a certificate in the form in the Schedule (Part A by the person in charge of the device, Part B by an
            expert, both carrying the hash value) must accompany the record each time it is submitted

This module turns those requirements into deterministic, explainable checks. It does NOT decide admissibility —
that is for the court. It tells the law-enforcement team, before the charge sheet, which statutory facts are
proved, which are missing (curable) and which are adverse (at risk), and drafts the Schedule certificate.

Physical exhibits get the parallel "reliability" checks courts look at: sealing, chain of custody, seal
integrity, in-situ documentation, audio-video recording of search & seizure (BNSS 2023 §105), preservation, and
integrity of the stored triage result.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import (AuthenticityAssessment, CaseInput, ElectronicRecord, Flag, LegalCheck, TriageResult,
                     TriagedItem)

ELECTRONIC_CATEGORY = "digital"
NOT_AT_SCENE = {"viscera", "body_fluid_tox", "reference_blood", "sexual_assault_kit", "fingernail_scrapings", "gsr_kit"}
CREDIT = {"PASS": 1.0, "ADVISORY": 0.5, "MISSING": 0.0, "FAIL": 0.0}

DISCLAIMER = ("Decision support for the law-enforcement team, not legal advice. Admissibility and weight are decided by "
              "the court; confirm with the Public Prosecutor / legal cell.")

# Statutory map shown in reports, the dashboard and the legal-analysis PDF.
LAW: list[dict[str, str]] = [
    {"law": "BSA 2023 s.61", "title": "Electronic or digital record",
     "rule": "Admissibility of an electronic or digital record cannot be denied merely because it is electronic; subject to s.63 it has the same legal effect as other documents.",
     "pramaan": "Every exhibit of category 'digital' (mobile phone, CCTV/DVR, computer/storage) gets an electronic-record assessment; the s.61 check records its recognition."},
    {"law": "BSA 2023 s.62", "title": "Special provisions as to evidence relating to electronic record",
     "rule": "The contents of electronic records may be proved in accordance with s.63.",
     "pramaan": "The 'route' check decides whether the record is proved by producing the original device or by a s.63 computer output + certificate."},
    {"law": "BSA 2023 s.63(1)", "title": "Admissibility of electronic records",
     "rule": "A computer output (paper, stored, recorded or copied in optical/magnetic/semiconductor media) is deemed a document and admissible if the s.63 conditions are satisfied.",
     "pramaan": "Acquisition method is captured (original device / forensic image / exported copy / screen capture / printout) and graded for reliability."},
    {"law": "BSA 2023 s.63(2)(a)", "title": "Regular use", "rule": "Output produced while the device was regularly used for an activity regularly carried on by the person having lawful control over it.",
     "pramaan": "ElectronicRecord.regular_use -> check s63_2_a."},
    {"law": "BSA 2023 s.63(2)(b)", "title": "Ordinary course", "rule": "Information of the kind in the record was regularly fed into the device in the ordinary course of those activities.",
     "pramaan": "ElectronicRecord.ordinary_course -> check s63_2_b."},
    {"law": "BSA 2023 s.63(2)(c)", "title": "Proper operation", "rule": "The device was operating properly, or any malfunction did not affect the record or the accuracy of its contents.",
     "pramaan": "ElectronicRecord.operating_properly (+ CCTV clock offset) -> checks s63_2_c, clock_sync."},
    {"law": "BSA 2023 s.63(2)(d)", "title": "Derived from ordinary course", "rule": "The record reproduces or is derived from information fed in the ordinary course of the activities.",
     "pramaan": "ElectronicRecord.derived_from_ordinary_course -> check s63_2_d."},
    {"law": "BSA 2023 s.63(4) + Schedule", "title": "Certificate (Part A and Part B)",
     "rule": "A certificate in the Schedule form must accompany the electronic record each time it is submitted: Part A by the person in charge of the device, Part B by an expert, with the hash value(s).",
     "pramaan": "Checks cert_part_a, cert_part_b, hash_recorded; generate_bsa63_certificate drafts both parts pre-filled with device particulars and hashes."},
    {"law": "Integrity (hash)", "title": "Hash verification",
     "rule": "A hash recomputed at the laboratory must equal the hash recorded at acquisition; any difference means the record changed.",
     "pramaan": "hash_verified check; a mismatch raises HASH_MISMATCH and makes the record AT RISK."},
    {"law": "BNSS 2023 s.105", "title": "Audio-video recording of search and seizure",
     "rule": "The process of search and seizure, including preparation of the list of seized items, is to be recorded through audio-video electronic means.",
     "pramaan": "CaseInput.seizure_video_recorded -> check seizure_video for every exhibit."},
    {"law": "IT Act 2000 s.79A", "title": "Examiner of Electronic Evidence",
     "rule": "Government-notified examiners provide expert opinion on electronic-form evidence.",
     "pramaan": "Part B expert role is recorded (FSL cyber division / notified examiner / other qualified expert)."},
    {"law": "Case law (under IEA s.65B, predecessor of BSA s.63)", "title": "Anvar P.V. v. P.K. Basheer (2014); Arjun Panditrao Khotkar v. Kailash Kushanrao Gorantyal (2020)",
     "rule": "The certificate is a condition precedent when a copy/computer output is relied upon; it is not needed where the original device itself is produced as primary evidence.",
     "pramaan": "Route 'original_device' marks certificate checks as recommended rather than required; every other route makes them required."},
    {"law": "Pune Bar Association v. Union of India (SC, 2026, as reported)", "title": "Who may sign Part B",
     "rule": "Any individual with special skill and expertise in computer science / cyber forensics may sign Part B, if the court is satisfied.",
     "pramaan": "expert_role is free text; Pramaan asks for the designation and qualification basis, not only government notification."},
]


def is_electronic(item: TriagedItem) -> bool:
    return item.classification.category == ELECTRONIC_CATEGORY


def _score(checks: list[LegalCheck]) -> float:
    applicable = [c for c in checks if c.status != "NA" and c.weight > 0]
    total = sum(c.weight for c in applicable)
    return round(100.0 * sum(c.weight * CREDIT[c.status] for c in applicable) / total, 1) if total else 100.0


def _status(checks: list[LegalCheck], critical_ids: Iterable[str]) -> str:
    crit = set(critical_ids)
    if any(c.status == "FAIL" and (c.id in crit or c.required) for c in checks):
        return "AT_RISK"
    if any(c.status == "MISSING" and c.required for c in checks):
        return "CURABLE_GAPS"
    return "READY"


def _tri(value: bool | None) -> str:
    return "MISSING" if value is None else ("PASS" if value else "FAIL")


def _custody_checks(events: list[dict[str, Any]], weight_scale: float = 1.0) -> list[LegalCheck]:
    """Chain-of-custody checks from the hash-chained ledger events of one exhibit."""
    sealed = [e for e in events if e["action"] == "custody:sealed"]
    moved = [e for e in events if e["action"] in ("custody:handed_over", "custody:received")]
    seal_flags = [e["payload"].get("seal_intact") for e in events if e["payload"].get("seal_intact") is not None]
    broken = [e for e in events if e["payload"].get("seal_intact") is False]
    return [
        LegalCheck(id="sealed", law="Chain of custody", requirement="Exhibit sealed and the sealing recorded",
                   status="PASS" if sealed else "MISSING", weight=10 * weight_scale,
                   detail=f"{len(sealed)} sealing event(s) in the ledger",
                   remedy="Record the sealing with record_custody_event(event='sealed', seal_intact=true)."),
        LegalCheck(id="custody_chain", law="Chain of custody", requirement="Every transfer (IO -> Malkhana -> FSL) recorded",
                   status="PASS" if moved else "MISSING", weight=10 * weight_scale,
                   detail=f"{len(moved)} hand-over/receipt event(s)",
                   remedy="Record each hand-over and receipt with roles (never names)."),
        LegalCheck(id="seal_integrity", law="Chain of custody", requirement="Seal found intact at every hand-over",
                   status="FAIL" if broken else ("PASS" if seal_flags else "MISSING"), weight=15 * weight_scale,
                   detail="seal reported NOT intact at seq " + ", ".join(str(e["seq"]) for e in broken) if broken
                   else f"{len(seal_flags)} seal observation(s)",
                   remedy="Explain the broken seal in writing (who, when, why) and have the FSL re-verify the contents/hash." if broken
                   else "Note seal condition at every hand-over."),
    ]


# --------------------------------------------------------------- electronic
def assess_electronic(er: ElectronicRecord | None, item: TriagedItem, *, seizure_video: bool | None = None,
                      custody_events: list[dict[str, Any]] | None = None, result_ok: bool | None = None) -> AuthenticityAssessment:
    type_id = item.classification.type_id
    primary = er is not None and er.acquisition == "original_device"
    route = ("Original device produced (primary evidence route) — certificate recommended"
             if primary else "Computer output / copy proved under BSA s.63 with the s.63(4) certificate")
    checks: list[LegalCheck] = [
        LegalCheck(id="s61_recognition", law="BSA 2023 s.61", requirement="Electronic record recognised as a document",
                   status="PASS", required=False, weight=0, detail="Admissibility cannot be refused merely because it is electronic."),
        LegalCheck(id="s62_route", law="BSA 2023 s.62 / s.63(1)", requirement="Mode of proof identified",
                   status="PASS" if er else "MISSING", weight=5,
                   detail=route if er else "Acquisition method not recorded",
                   remedy="Record how the record reaches court: original device, forensic image, exported copy, screen capture or printout."),
    ]
    if er is None:
        conds = [None] * 4
    else:
        conds = [er.regular_use, er.ordinary_course, er.operating_properly, er.derived_from_ordinary_course]
    texts = [
        ("s63_2_a", "BSA 2023 s.63(2)(a)", "Device regularly used for the activity by the person in lawful control",
         "Obtain a statement from the person in charge (by designation) on regular use during the period."),
        ("s63_2_b", "BSA 2023 s.63(2)(b)", "Information of this kind regularly fed in the ordinary course",
         "Document the normal recording/entry practice (e.g. CCTV records continuously; phone used for messaging)."),
        ("s63_2_c", "BSA 2023 s.63(2)(c)", "Device operating properly, or malfunction did not affect the record",
         "Record device health/logs; for CCTV note any outage and that it did not affect the relevant period."),
        ("s63_2_d", "BSA 2023 s.63(2)(d)", "Record reproduces / is derived from information fed in the ordinary course",
         "State how the output was produced (export tool, image, file path) so derivation is traceable."),
    ]
    for (cid, law, req, remedy), val in zip(texts, conds):
        st = _tri(val)
        if primary and st == "MISSING":
            st = "ADVISORY"
        checks.append(LegalCheck(id=cid, law=law, requirement=req, status=st, required=not primary, weight=7.5,
                                 detail={"PASS": "Confirmed", "FAIL": "Stated NOT satisfied", "MISSING": "Not recorded",
                                         "ADVISORY": "Not recorded (original device route)"}[st], remedy=remedy))
    part_a = er is not None and er.certificate_part_a
    part_b = er is not None and er.certificate_part_b
    for cid, ok, who, extra in (("cert_part_a", part_a, "person in charge of the device / relevant activities",
                                 er.part_a_signatory_role if er else None),
                                ("cert_part_b", part_b, "an expert", er.expert_role if er else None)):
        st = "PASS" if ok else ("ADVISORY" if primary else "MISSING")
        checks.append(LegalCheck(
            id=cid, law="BSA 2023 s.63(4) + Schedule " + ("Part A" if cid.endswith("a") else "Part B"),
            requirement=f"Certificate signed by {who}", status=st, required=not primary, weight=12.5,
            detail=f"Signed ({extra})" if ok and extra else ("Signed" if ok else "Not yet signed"),
            remedy=("Draft with generate_bsa63_certificate; get it signed by " + who +
                    ("; any person with special skill in computer science / cyber forensics may sign if the court is satisfied"
                     if cid.endswith("b") else "") + ". Attach it every time the record is submitted.")))
    h1 = er.hash_at_acquisition if er else None
    h2 = er.hash_at_lab if er else None
    algo = er.hash_algorithm if er else "SHA-256"
    if h1 and not er.hash_valid(h1):
        hs, hd = "FAIL", f"Not a valid {algo} hex digest"
    elif h1:
        hs, hd = ("PASS" if algo in ("SHA-256", "SHA-512") else "ADVISORY"), f"{algo} {h1[:16]}…" + (
            "" if algo in ("SHA-256", "SHA-512") else " — prefer SHA-256 (MD5/SHA-1 are collision-prone)")
    else:
        hs, hd = "MISSING", "No hash recorded at acquisition"
    checks.append(LegalCheck(id="hash_recorded", law="BSA 2023 s.63(4) Schedule (hash value)",
                             requirement="Hash of the record computed and recorded at acquisition", status=hs, weight=15,
                             detail=hd, remedy="Compute SHA-256 of the image/export at seizure and record it in the seizure memo and Part A."))
    if h1 and h2:
        vs = "PASS" if h1 == h2 else "FAIL"
        vd = "Lab hash equals acquisition hash" if vs == "PASS" else f"MISMATCH: lab {h2[:16]}… vs acquisition {h1[:16]}…"
    else:
        vs, vd = "MISSING", "Lab verification pending"
    checks.append(LegalCheck(id="hash_verified", law="Integrity (hash verification)", requirement="FSL re-hash matches acquisition hash",
                             status=vs, required=False, weight=10, detail=vd,
                             remedy="Do not rely on the record until the difference is explained by the expert (Part B) — re-acquire from source if possible."
                             if vs == "FAIL" else "FSL cyber division re-computes the hash on receipt and records it."))
    acq_status = "MISSING" if er is None else {"original_device": "PASS", "forensic_image": "PASS", "exported_copy": "PASS" if h1 else "ADVISORY",
                                               "screen_capture": "ADVISORY", "printout": "ADVISORY"}[er.acquisition]
    checks.append(LegalCheck(id="acquisition_quality", law="BSA 2023 s.63(1) (computer output)", requirement="Reliable acquisition method",
                             status=acq_status, required=False, weight=5, detail=er.acquisition if er else "Not recorded",
                             remedy="Prefer a forensic image or native export with hash over screenshots/printouts."))
    storage_like = type_id in ("computer_storage", "mobile_phone")
    checks.append(LegalCheck(id="write_blocker", law="Forensic procedure", requirement="Write-blocking during acquisition",
                             status=("NA" if not storage_like else _tri(er.write_blocker_used if er else None)), required=False,
                             weight=5, detail="Storage/mobile acquisition" if storage_like else "Not applicable to this source",
                             remedy="Acquire through a hardware/software write blocker and note it in Part B."))
    cctv = type_id == "cctv_dvr"
    checks.append(LegalCheck(id="clock_sync", law="BSA 2023 s.63(2)(c) (accuracy)", requirement="Device clock offset documented",
                             status="NA" if not cctv else ("PASS" if er and er.clock_offset_s is not None else "MISSING"),
                             required=False, weight=3,
                             detail=(f"offset {er.clock_offset_s:+.0f} s" if cctv and er and er.clock_offset_s is not None else "CCTV/DVR only"),
                             remedy="Photograph the DVR clock beside a reference clock at seizure and record the offset."))
    checks.append(LegalCheck(id="seizure_video", law="BNSS 2023 s.105", requirement="Search & seizure recorded by audio-video means",
                             status=_tri(seizure_video), required=False, weight=5,
                             detail={True: "Recorded", False: "Not recorded", None: "Not stated"}[seizure_video],
                             remedy="Record seizure on video (mobile phone suffices) and preserve it with its own hash."))
    if custody_events is not None:
        checks += _custody_checks(custody_events, weight_scale=0.5)
    if result_ok is not None:
        checks.append(LegalCheck(id="result_integrity", law="Pramaan ledger", requirement="Stored triage result matches its recorded hash",
                                 status="PASS" if result_ok else "FAIL", required=False, weight=5,
                                 remedy="Investigate ledger tampering before relying on any output."))
    status = _status(checks, critical_ids=("hash_verified", "seal_integrity", "result_integrity", "hash_recorded",
                                           "s63_2_a", "s63_2_b", "s63_2_c", "s63_2_d"))
    gaps = [c for c in checks if c.status in ("MISSING", "FAIL") and c.required]
    summary = {"READY": "All statutory facts for proof under BSA s.63 are recorded.",
               "CURABLE_GAPS": f"{len(gaps)} required item(s) still to be completed before the record is relied on: " +
                               ", ".join(c.id for c in gaps),
               "AT_RISK": "Adverse fact recorded (" + ", ".join(c.id for c in checks if c.status == "FAIL") +
                          ") — authenticity is open to challenge."}[status]
    return AuthenticityAssessment(kind="electronic", route=route, status=status, score=_score(checks), checks=checks, summary=summary)


def electronic_flags(a: AuthenticityAssessment, er: ElectronicRecord | None) -> list[Flag]:
    out: list[Flag] = []
    by = {c.id: c for c in a.checks}
    if er is None:
        out.append(Flag(code="BSA63_DETAILS_MISSING", severity="medium", message=(
            "Electronic record: record acquisition method, hash (SHA-256), s.63(2) facts and certificate status — "
            "needed to prove it under BSA 2023 s.63.")))
    if by["hash_verified"].status == "FAIL":
        out.append(Flag(code="HASH_MISMATCH", severity="critical", message=by["hash_verified"].detail + ". " + by["hash_verified"].remedy))
    if any(by[k].status == "FAIL" for k in ("s63_2_a", "s63_2_b", "s63_2_c", "s63_2_d")):
        out.append(Flag(code="BSA63_CONDITION_NOT_MET", severity="high", message=(
            "A s.63(2) condition is recorded as not satisfied — the computer-output route may fail; consider producing the original device.")))
    if er is not None and er.acquisition != "original_device" and not (er.certificate_part_a and er.certificate_part_b):
        out.append(Flag(code="BSA63_CERTIFICATE_PENDING", severity="high", message=(
            "s.63(4) certificate (Schedule Part A + Part B with hash) must accompany this record every time it is submitted.")))
    return out


# ----------------------------------------------------------------- physical
def assess_physical(item: TriagedItem, *, captions: list[str], seizure_video: bool | None,
                    custody_events: list[dict[str, Any]], result_ok: bool | None) -> AuthenticityAssessment:
    scene_item = item.classification.type_id not in NOT_AT_SCENE
    window_passed = any(f.code == "COLLECTION_WINDOW_PASSED" for f in item.flags)
    photo = any(item.label.lower() in c.lower() for c in captions)
    checks = [
        LegalCheck(id="collection", law="BNSS 2023 s.176(3) / scene practice", requirement="Collected and documented within its field window",
                   status="FAIL" if window_passed else ("PASS" if item.collected else "MISSING"), weight=10,
                   detail="collected" if item.collected else "still at the scene",
                   remedy="Collect now and record the time; explain any delay in the case diary."),
        LegalCheck(id="in_situ_photo", law="Scene documentation", requirement="In-situ photograph with scale linked to the exhibit",
                   status="NA" if not scene_item else ("PASS" if photo else "MISSING"), required=False, weight=10,
                   remedy="Link the exhibit label to its scene photograph in the photo log."),
        LegalCheck(id="seizure_video", law="BNSS 2023 s.105", requirement="Search & seizure recorded by audio-video means",
                   status="NA" if not scene_item else _tri(seizure_video), required=False, weight=10,
                   remedy="Record seizure on video and preserve the file with its hash."),
    ]
    checks += _custody_checks(custody_events)
    d = item.degradation
    checks.append(LegalCheck(id="preservation", law="Handling standard", requirement="Stored in the recommended condition",
                             status="ADVISORY" if d.better_condition and d.hours_to_risk is not None and d.hours_to_risk < 72 else "PASS",
                             required=False, weight=10, detail=f"{d.condition}" + (f" -> {d.better_condition} recommended" if d.better_condition else ""),
                             remedy=item.handling))
    if result_ok is not None:
        checks.append(LegalCheck(id="result_integrity", law="Pramaan ledger", requirement="Stored triage result matches its recorded hash",
                                 status="PASS" if result_ok else "FAIL", required=False, weight=10))
    status = _status(checks, critical_ids=("seal_integrity", "result_integrity", "collection"))
    return AuthenticityAssessment(kind="physical", route="Physical exhibit — proved through seizure memo, custody record and expert report",
                                  status=status, score=_score(checks), checks=checks,
                                  summary={"READY": "Custody and documentation complete.",
                                           "CURABLE_GAPS": "Custody/documentation still to be recorded.",
                                           "AT_RISK": "Adverse custody or collection fact — reliability open to challenge."}[status])


# --------------------------------------------------------------------- case
def assess_case(result: TriageResult, case_input: CaseInput, ledger_entries: list[dict[str, Any]],
                result_ok: bool | None) -> dict[str, Any]:
    by_item: dict[str, list[dict[str, Any]]] = {}
    for e in sorted(ledger_entries, key=lambda e: e["seq"]):
        if e.get("item_id") and e["action"].startswith("custody:"):
            by_item.setdefault(e["item_id"], []).append(e)
    inputs = {f"E-{n:03d}": it for n, it in enumerate(case_input.items, start=1)}
    rows = []
    for it in result.items:
        events = by_item.get(it.item_id, [])
        if is_electronic(it):
            er = inputs.get(it.item_id).electronic if inputs.get(it.item_id) else None
            a = assess_electronic(er, it, seizure_video=case_input.seizure_video_recorded, custody_events=events, result_ok=result_ok)
        else:
            a = assess_physical(it, captions=case_input.photo_captions, seizure_video=case_input.seizure_video_recorded,
                                custody_events=events, result_ok=result_ok)
        er_in = inputs.get(it.item_id).electronic if (is_electronic(it) and inputs.get(it.item_id)) else None
        rows.append({"item_id": it.item_id, "label": it.label, "type": it.classification.type_name, "tier": it.tier,
                     "assessment": a.model_dump(), "electronic_input": er_in.model_dump(mode="json") if er_in else None})
    counts = {k: sum(r["assessment"]["status"] == k for r in rows) for k in ("READY", "CURABLE_GAPS", "AT_RISK")}
    elec = [r for r in rows if r["assessment"]["kind"] == "electronic"]
    return {"case_id": result.case_id, "case_ref": result.case_ref, "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts, "electronic_records": len(elec),
            "electronic_ready": sum(r["assessment"]["status"] == "READY" for r in elec),
            "items": rows, "law": LAW, "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------------- PDF
def _pdf_base():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    from .reports import _fonts
    regular, bold, uni = _fonts()
    ink = colors.HexColor("#1d2330")
    base = ParagraphStyle("b", fontName=regular, fontSize=9, leading=12, textColor=ink)
    return {
        "colors": colors, "uni": uni, "base": base,
        "small": ParagraphStyle("s", parent=base, fontSize=7.6, leading=9.6, textColor=colors.HexColor("#5b6475")),
        "cell": ParagraphStyle("c", parent=base, fontSize=7.8, leading=9.8),
        "cellb": ParagraphStyle("cb", parent=base, fontName=bold, fontSize=7.8, leading=9.8),
        "h1": ParagraphStyle("h1", parent=base, fontName=bold, fontSize=15, leading=19, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName=bold, fontSize=11, leading=14, spaceBefore=10, spaceAfter=4),
    }


def _p(text: str, style, uni: bool):
    from reportlab.platypus import Paragraph

    from .reports import _esc
    return Paragraph(_esc(str(text), uni), style)


def _table(rows, widths, st):
    from reportlab.platypus import Table, TableStyle
    colors = st["colors"]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9ced8")),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecf2")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return t


STATUS_WORDS = {"READY": "READY", "CURABLE_GAPS": "CURABLE GAPS", "AT_RISK": "AT RISK"}


def authenticity_report_pdf(report: dict[str, Any], result: TriageResult) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer
    st = _pdf_base()
    uni = st["uni"]
    P = lambda t, s="base": _p(t, st[s], uni)  # noqa: E731
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=13 * mm, bottomMargin=13 * mm,
                            title=f"Authenticity report {result.case_id}", author="Pramaan")
    W = page[0] - 28 * mm
    c = report["counts"]
    story = [P("EVIDENCE AUTHENTICITY & RELIABILITY REPORT — BSA 2023 ss.61-63 / BNSS 2023 s.105", "small"),
             P(result.case_ref, "h1"),
             P(f"Case {result.case_id} · {result.crime_label} · generated {report['generated_at'][:16].replace('T', ' ')} UTC · "
               f"READY {c['READY']} · CURABLE GAPS {c['CURABLE_GAPS']} · AT RISK {c['AT_RISK']} · electronic records "
               f"{report['electronic_records']} ({report['electronic_ready']} ready)"),
             P(report["disclaimer"], "small"), P("1. Summary by exhibit", "h2")]
    rows = [[P(h, "cellb") for h in ("Exhibit", "Type", "Kind", "Status", "Score", "Route", "Open items")]]
    for r in report["items"]:
        a = r["assessment"]
        open_items = "; ".join(f"{ch['id']} ({ch['status']})" for ch in a["checks"] if ch["status"] in ("FAIL", "MISSING"))
        rows.append([P(r["label"], "cellb"), P(r["type"], "cell"), P(a["kind"], "cell"), P(STATUS_WORDS[a["status"]], "cellb"),
                     P(f"{a['score']:.0f}", "cell"), P(a["route"], "cell"), P(open_items or "-", "cell")])
    story.append(_table(rows, [W * .07, W * .14, W * .07, W * .09, W * .05, W * .25, W * .33], st))
    elec = [r for r in report["items"] if r["assessment"]["kind"] == "electronic"]
    if elec:
        story += [PageBreak(), P("2. Electronic records — statutory checklist", "h2")]
        for r in elec:
            a = r["assessment"]
            story.append(P(f"{r['label']} — {r['type']} — {STATUS_WORDS[a['status']]} ({a['score']:.0f}/100). {a['summary']}", "cellb"))
            rows = [[P(h, "cellb") for h in ("Check", "Law", "Requirement", "Status", "Detail", "Remedy")]]
            for ch in a["checks"]:
                rows.append([P(ch["id"], "cell"), P(ch["law"], "cell"), P(ch["requirement"], "cell"), P(ch["status"], "cellb"),
                             P(ch["detail"], "cell"), P(ch["remedy"], "cell")])
            story += [_table(rows, [W * .1, W * .14, W * .2, W * .07, W * .18, W * .31], st), Spacer(1, 8)]
    story += [P("3. Statutory basis", "h2")]
    rows = [[P(h, "cellb") for h in ("Provision", "Subject", "Rule (summary)", "How Pramaan implements it")]]
    for L in LAW:
        rows.append([P(L["law"], "cellb"), P(L["title"], "cell"), P(L["rule"], "cell"), P(L["pramaan"], "cell")])
    story.append(_table(rows, [W * .15, W * .17, W * .34, W * .34], st))
    story.append(P(f"Integrity: KB {result.kb_hash} · result {result.result_sha256}", "small"))
    doc.build(story)
    return buf.getvalue()


SOURCE_LABELS = {"computer_storage": "Computer / Storage Media", "dvr": "DVR", "mobile": "Mobile", "flash_drive": "Flash Drive",
                 "cd_dvd": "CD/DVD", "server": "Server", "cloud": "Cloud", "other": "Other"}
_TYPE_SOURCE = {"cctv_dvr": "dvr", "mobile_phone": "mobile", "computer_storage": "computer_storage"}


def certificate_pdf(result: TriageResult, item: TriagedItem, er: ElectronicRecord | None) -> bytes:
    """Draft of the BSA s.63(4) Schedule certificate, pre-filled from recorded facts, with blanks for signatures."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Spacer
    st = _pdf_base()
    uni = st["uni"]
    P = lambda t, s="base": _p(t, st[s], uni)  # noqa: E731
    er = er or ElectronicRecord()
    src = er.source_kind or _TYPE_SOURCE.get(item.classification.type_id, "other")
    ticks = "   ".join(("[X] " if k == src else "[  ] ") + v for k, v in SOURCE_LABELS.items())
    blank = "______________________"
    h1 = er.hash_at_acquisition or blank
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"BSA s.63(4) certificate draft {item.label}", author="Pramaan")
    W = A4[0] - 36 * mm
    story = [P("DRAFT — for completion and signature. Pre-filled by Pramaan from recorded facts; the Schedule to the "
               "Bharatiya Sakshya Adhiniyam, 2023 governs the final form.", "small"),
             P("CERTIFICATE UNDER SECTION 63(4)(c) OF THE BHARATIYA SAKSHYA ADHINIYAM, 2023", "h1"),
             P(f"Case reference: {result.case_ref} · Exhibit {item.label} ({item.classification.type_name}) · Pramaan case {result.case_id}"),
             P("PART A (to be filled by the party / person in charge of the device)", "h2"),
             P(f"I, {blank} (name), {er.part_a_signatory_role or blank} (designation), employed at {blank}, do hereby solemnly "
               "affirm and state that I have produced the electronic record / output of the digital record described below, taken "
               "from the following device / digital record source:"),
             Spacer(1, 4), P(ticks, "cell"), Spacer(1, 4)]
    rows = [[P("Field", "cellb"), P("Value", "cellb")],
            [P("Make & model", "cell"), P(er.device or blank, "cell")],
            [P("Serial / IMEI / UIN / UID / MAC / Cloud ID", "cell"), P(er.device_id or blank, "cell")],
            [P("Record produced", "cell"), P(er.record_description or item.description, "cell")],
            [P("Manner of production", "cell"), P(er.acquisition.replace("_", " "), "cell")],
            [P(f"Hash value ({er.hash_algorithm})", "cell"), P(h1, "cell")],
            [P("Date/time of acquisition", "cell"), P(er.acquired_at.isoformat() if er.acquired_at else blank, "cell")]]
    story.append(_table(rows, [W * .35, W * .65], st))
    conds = [("(a)", er.regular_use, "the device was regularly used to create, store or process information for the purposes of "
              "activities regularly carried on by the person having lawful control over it during the relevant period;"),
             ("(b)", er.ordinary_course, "information of the kind contained in the record was regularly fed into it in the ordinary "
              "course of those activities;"),
             ("(c)", er.operating_properly, "throughout the material part of that period the device was operating properly or, if not, "
              "any malfunction did not affect the electronic record or the accuracy of its contents;"),
             ("(d)", er.derived_from_ordinary_course, "the information in the record reproduces or is derived from information fed "
              "into the device in the ordinary course of those activities.")]
    story.append(Spacer(1, 6))
    story.append(P("I further state, in terms of section 63(2) of the Adhiniyam, that:"))
    for tag, val, text in conds:
        mark = {True: "[confirmed]", False: "[NOT CONFIRMED — do not sign without explanation]", None: "[to be confirmed]"}[val]
        story.append(P(f"{tag} {text} {mark}", "cell"))
    story += [Spacer(1, 6), P("The above is true to the best of my information and belief. Place: ________ Date: ________ "
                              "Time: ________   Signature: ____________________"), P("PART B (to be filled by the expert)", "h2"),
              P(f"I, {blank} (name), {er.expert_role or blank} (designation / expertise), state that the electronic record "
                f"described in Part A has been examined and that the hash value of the record, computed using {er.hash_algorithm}, is:")]
    rows = [[P("Hash computed by expert", "cellb"), P(er.hash_at_lab or blank, "cell")],
            [P("Matches Part A hash", "cellb"), P("—" if not (er.hash_at_lab and er.hash_at_acquisition) else
                                                 ("YES" if er.hash_at_lab == er.hash_at_acquisition else "NO — explain below"), "cell")],
            [P("Write-blocker / method", "cellb"), P({True: "write blocker used", False: "no write blocker", None: blank}[er.write_blocker_used], "cell")],
            [P("Device clock offset (CCTV)", "cellb"), P(f"{er.clock_offset_s:+.0f} s" if er.clock_offset_s is not None else blank, "cell")]]
    story += [_table(rows, [W * .35, W * .65], st), Spacer(1, 6),
              P("Place: ________ Date: ________ Time: ________   Signature: ____________________"), Spacer(1, 10),
              P(DISCLAIMER + " The certificate must accompany the electronic record each time it is submitted for admission.", "small")]
    doc.build(story)
    return buf.getvalue()


def legal_analysis_pdf() -> bytes:
    """Standing legal analysis of how Pramaan implements BSA ss.61-63 (and how the system itself stays lawful)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate
    st = _pdf_base()
    uni = st["uni"]
    P = lambda t, s="base": _p(t, st[s], uni)  # noqa: E731
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Pramaan — BSA 2023 electronic evidence compliance analysis", author="Pramaan")
    W = A4[0] - 34 * mm
    story = [P("PRAMAAN · LAW-ENFORCEMENT TEAM MODULE", "small"),
             P("Authenticity, reliability and admissibility of evidence under the Bharatiya Sakshya Adhiniyam, 2023", "h1"),
             P(DISCLAIMER, "small"),
             P("1. Legal framework", "h2"),
             P("The Bharatiya Sakshya Adhiniyam, 2023 (BSA) replaced the Indian Evidence Act, 1872 with effect from 1 July 2024 "
               "(proceedings pending on that date continue under the old Act). Electronic and digital records are governed by "
               "ss.61-63. Section 61 prevents a court from refusing an electronic record merely because it is electronic and gives it, "
               "subject to s.63, the same legal effect as other documents. Section 62 routes proof of its contents through s.63. "
               "Section 63(1) deems a computer output to be a document admissible without further proof of the original when the "
               "conditions of s.63 are met. Section 63(2) lists four reliability conditions (regular use, ordinary course, proper "
               "operation, derivation from ordinary-course input). Section 63(4) requires a certificate in the form in the Schedule — "
               "Part A by the person in charge of the device and Part B by an expert, carrying the hash value — to accompany the "
               "record each time it is submitted."),
             P("2. How the code implements each provision", "h2")]
    rows = [[P(h, "cellb") for h in ("Provision", "Rule (summary)", "Pramaan implementation")]]
    for L in LAW:
        rows.append([P(L["law"] + " — " + L["title"], "cellb"), P(L["rule"], "cell"), P(L["pramaan"], "cell")])
    story.append(_table(rows, [W * .25, W * .38, W * .37], st))
    story += [P("3. Scoring and status (deterministic)", "h2"),
              P("Each check returns PASS, ADVISORY (half credit), MISSING, FAIL or NA. The authenticity score is the weighted "
                "share of credit over applicable checks (weights in pramaan/bsa.py: s.63(2)(a)-(d) 7.5 each; Part A and Part B 12.5 "
                "each; hash recorded 15; hash verified 10; mode of proof 5; acquisition quality 5; write-blocking 5; clock offset 3; "
                "BNSS s.105 video 5; custody checks from the hash-chained ledger). Status is AT RISK when an adverse fact is recorded "
                "(hash mismatch, a s.63(2) condition stated unmet, a broken seal, a tampered result), CURABLE GAPS when a required "
                "item is missing (e.g. certificate not yet signed), and READY otherwise. For the original-device route the certificate "
                "items are recommended rather than required, reflecting Arjun Panditrao Khotkar (2020) under the predecessor s.65B."),
              P("4. Lawfulness of the system itself", "h2"),
              P("(a) Data minimisation and victim protection: the privacy gate rejects names, phone, Aadhaar and e-mail patterns on "
                "every surface (BNS 2023 s.72; Digital Personal Data Protection Act, 2023). Certificate signatories are stored by "
                "designation only; names are written by hand on the signed certificate. (b) No automated legal determination: the "
                "module reports readiness and remedies; the court decides admissibility and the prosecutor advises. (c) Integrity: every "
                "recorded fact, triage and custody event is appended to a SHA-256 hash-chained ledger, and each output carries the "
                "knowledge-base and result hashes, so the assessment itself can be audited. (d) Human in the loop: officers record "
                "facts; overrides need reasons; nothing is filed automatically. (e) Transparency: rules, weights and statutory mapping "
                "are in source code and this document."),
              P("5. Law-enforcement team workflow", "h2"),
              P("Investigating Officer: records acquisition method, device particulars, hash at seizure, s.63(2) facts and BNSS s.105 "
                "video status (record_electronic_evidence / dashboard form). Person in charge of the device: signs Part A (drafted by "
                "generate_bsa63_certificate). FSL cyber division / qualified expert: re-computes the hash (hash_at_lab) and signs Part B. "
                "Legal cell / Public Prosecutor: reviews the authenticity report (READY / CURABLE GAPS / AT RISK) before the charge "
                "sheet. SHO: ensures custody events are recorded at every hand-over."),
              P("6. Limitations", "h2"),
              P("Statutory text is summarised, not reproduced; verify against the official BSA text and the Schedule. Case law cited "
                "was decided under the Indian Evidence Act s.65B and is applied by analogy. Recent decisions (e.g. the 2026 Supreme Court "
                "ruling on who may sign Part B, as reported) should be confirmed from official reports.")]
    doc.build(story)
    return buf.getvalue()
