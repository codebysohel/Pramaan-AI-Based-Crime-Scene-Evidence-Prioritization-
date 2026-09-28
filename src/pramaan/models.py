"""Typed domain model shared by the engine, REST API, MCP server and CLI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Condition = Literal["ambient", "hot", "wet", "sunlight", "refrigerated", "frozen", "dry_sealed"]
Tier = Literal["P1", "P2", "P3", "P4"]
Severity = Literal["critical", "high", "medium", "low", "info"]

TIER_LABELS = {
    "P1": "Critical — examine immediately",
    "P2": "High — examine in first batch",
    "P3": "Routine — standard queue",
    "P4": "Hold — store; examine only if case theory needs it",
}


# --------------------------------------------------------------------- inputs
class SceneContext(BaseModel):
    setting: Literal["outdoor", "indoor", "vehicle", "mixed"] = "outdoor"
    ambient_temp_c: Optional[float] = Field(None, description="Temperature at the scene, °C")
    weather: Literal["dry", "rain", "humid"] = "dry"


HashAlgo = Literal["SHA-256", "SHA-512", "SHA-1", "MD5"]
Acquisition = Literal["original_device", "forensic_image", "exported_copy", "screen_capture", "printout"]
_HEX_LEN = {"SHA-256": 64, "SHA-512": 128, "SHA-1": 40, "MD5": 32}


class ElectronicRecord(BaseModel):
    """Facts needed to prove an electronic record under BSA 2023 §§61-63 (+ Schedule certificate).

    Device identifiers only — never personal names. Signatories are recorded by ROLE/designation."""
    acquisition: Acquisition = Field("exported_copy", description="How the record reaches the court")
    source_kind: Optional[Literal["computer_storage", "dvr", "mobile", "flash_drive", "cd_dvd", "server", "cloud", "other"]] = Field(
        None, description="Device/source category as ticked in Schedule Part A")
    device: Optional[str] = Field(None, max_length=120, description="Make & model / description of the device")
    device_id: Optional[str] = Field(None, max_length=80, description="Serial / IMEI / UIN / UID / MAC / Cloud ID")
    record_description: Optional[str] = Field(None, max_length=300, description="What the record is, e.g. 'camera 3, 21:00-23:30'")
    hash_algorithm: HashAlgo = "SHA-256"
    hash_at_acquisition: Optional[str] = Field(None, description="Hash computed when the record/image was acquired")
    hash_at_lab: Optional[str] = Field(None, description="Hash recomputed at the FSL on receipt")
    acquired_at: Optional[datetime] = None
    regular_use: Optional[bool] = Field(None, description="§63(2)(a) device regularly used for the activity by the person in lawful control")
    ordinary_course: Optional[bool] = Field(None, description="§63(2)(b) information of this kind regularly fed in the ordinary course")
    operating_properly: Optional[bool] = Field(None, description="§63(2)(c) device operating properly, or malfunction did not affect the record")
    derived_from_ordinary_course: Optional[bool] = Field(None, description="§63(2)(d) record reproduces/derives from information fed in ordinary course")
    clock_offset_s: Optional[float] = Field(None, description="Device clock minus true time (seconds), for CCTV/DVR")
    write_blocker_used: Optional[bool] = None
    certificate_part_a: bool = Field(False, description="Schedule Part A signed by the person in charge of the device")
    part_a_signatory_role: Optional[str] = Field(None, max_length=80, description="Designation only, e.g. 'Manager, toll plaza'")
    certificate_part_b: bool = Field(False, description="Schedule Part B signed by an expert")
    expert_role: Optional[str] = Field(None, max_length=120, description="e.g. 'FSL Cyber Division examiner' / 'IT Act s.79A Examiner'")

    @model_validator(mode="after")
    def _normalise_hashes(self) -> "ElectronicRecord":
        for name in ("hash_at_acquisition", "hash_at_lab"):
            v = getattr(self, name)
            if v:
                object.__setattr__(self, name, v.strip().lower().replace(" ", ""))
        return self

    def hash_valid(self, value: Optional[str]) -> bool:
        return bool(value) and len(value) == _HEX_LEN[self.hash_algorithm] and all(c in "0123456789abcdef" for c in value)


class ItemInput(BaseModel):
    description: str = Field(..., min_length=2, description="What the exhibit is, in the IO's words")
    label: Optional[str] = Field(None, description="Exhibit label as marked by the IO, e.g. 'Ex-A1'")
    location: Optional[str] = Field(None, description="Where it was found")
    quantity: int = Field(1, ge=1)
    collected: bool = Field(True, description="False if the item is still at the scene")
    collected_at: Optional[datetime] = None
    condition: Optional[Condition] = Field(None, description="Current storage condition if known")
    type_hint: Optional[str] = Field(None, description="Force a knowledge-base evidence type id")
    override_tier: Optional[Tier] = Field(None, description="Officer-set tier; requires override_reason")
    override_reason: Optional[str] = Field(None, max_length=300)
    electronic: Optional[ElectronicRecord] = Field(None, description="BSA §63 facts for electronic/digital exhibits")

    @model_validator(mode="after")
    def _override_needs_reason(self) -> "ItemInput":
        if self.override_tier and not (self.override_reason and len(self.override_reason.strip()) >= 5):
            raise ValueError("override_tier requires an override_reason (at least 5 characters)")
        return self


class CaseInput(BaseModel):
    case_ref: str = Field(..., min_length=1, description="FIR / crime number or local case reference")
    crime_type: str = Field(..., description="Crime profile id, e.g. 'homicide'")
    title: Optional[str] = None
    incident_time: Optional[datetime] = None
    reference_time: Optional[datetime] = Field(None, description="'Now' for the triage (defaults to current time)")
    scene: SceneContext = Field(default_factory=SceneContext)
    accused_in_custody: bool = False
    custody_start: Optional[datetime] = None
    max_punishment_years: Optional[int] = None
    items: list[ItemInput] = Field(default_factory=list)
    seizure_video_recorded: Optional[bool] = Field(None, description="BNSS 2023 §105: search & seizure recorded by audio-video means")
    description: Optional[str] = Field(None, description="Free-text scene / exhibit list to be parsed into items")
    photo_captions: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- outputs
class Classification(BaseModel):
    type_id: str
    type_name: str
    category: str
    confidence: float
    method: Literal["hint", "rules", "llm", "fallback"]
    matched_keywords: list[str] = Field(default_factory=list)
    modifiers: list[str] = Field(default_factory=list)
    context_signals: list[str] = Field(default_factory=list)
    distance_m: Optional[float] = None


class Degradation(BaseModel):
    profile: str
    condition: str
    elapsed_hours: float
    quality_now: float
    hours_to_risk: Optional[float] = Field(None, description="None = effectively stable")
    at_risk: bool
    better_condition: Optional[str] = None
    hours_to_risk_if_preserved: Optional[float] = None
    field_window_remaining_h: Optional[float] = None


class ScoreBreakdown(BaseModel):
    relevance: float
    individualizing: float
    context_boost: float
    probative: float
    urgency: float
    irreplaceable: float
    weights: dict[str, float]
    legal_floor_applied: bool = False
    epi: float


class Flag(BaseModel):
    code: str
    severity: Severity
    message: str

    @property
    def urgent(self) -> bool:
        return self.severity in ("critical", "high")


class ExamStep(BaseModel):
    exam_id: str
    name: str
    division: str
    hours: float
    stage: int
    destructive: bool


CheckStatus = Literal["PASS", "FAIL", "MISSING", "ADVISORY", "NA"]


class LegalCheck(BaseModel):
    id: str
    law: str = Field(..., description="Statutory provision or standard, e.g. 'BSA 2023 s.63(2)(a)'")
    requirement: str
    status: CheckStatus
    required: bool = True
    weight: float = 0.0
    detail: str = ""
    remedy: str = ""


class AuthenticityAssessment(BaseModel):
    kind: Literal["electronic", "physical"]
    route: str = Field("", description="How the evidence is to be proved")
    status: Literal["READY", "CURABLE_GAPS", "AT_RISK"]
    score: float = Field(..., ge=0, le=100, description="Reliability & authenticity readiness 0-100 (weighted checks)")
    checks: list[LegalCheck] = Field(default_factory=list)
    summary: str = ""


class TriagedItem(BaseModel):
    item_id: str
    label: str
    description: str
    location: Optional[str] = None
    quantity: int = 1
    collected: bool = True
    rank: int = 0
    tier: Tier = "P3"
    engine_tier: Optional[Tier] = Field(None, description="Tier from the EPI and flags alone, before staging/promotion/override")
    stage: int = Field(1, description="1 = first FSL submission, 2 = held pending stage-1 results")
    classification: Classification
    degradation: Degradation
    score: ScoreBreakdown
    flags: list[Flag] = Field(default_factory=list)
    exam_sequence: list[ExamStep] = Field(default_factory=list)
    divisions: list[str] = Field(default_factory=list)
    caveat: str = ""
    corroborate_with: list[str] = Field(default_factory=list)
    handling: str = ""
    rationale: str = ""
    notes: list[str] = Field(default_factory=list)
    authenticity: Optional["AuthenticityAssessment"] = Field(None, description="BSA §§61-63 admissibility readiness (electronic records)")

    @property
    def urgent(self) -> bool:
        return any(f.urgent for f in self.flags)


class GapAlert(BaseModel):
    id: str
    severity: Severity
    message: str
    action: str


class ScheduledOp(BaseModel):
    item_id: str
    label: str
    exam_id: str
    exam_name: str
    division: str
    examiner: int
    start_h: float
    end_h: float
    quality_at_start: float


class ItemSchedule(BaseModel):
    item_id: str
    label: str
    tier: Tier
    epi: float
    first_start_h: float
    completion_h: float
    due_h: Optional[float]
    late: bool
    quality_at_analysis: float


class DivisionLoad(BaseModel):
    division: str
    name: str
    examiners: int
    total_hours: float
    busy_until_h: float
    working_days: float


class ScheduleResult(BaseModel):
    policy: str
    ops: list[ScheduledOp]
    items: list[ItemSchedule]
    divisions: list[DivisionLoad]
    makespan_h: float
    makespan_days: float
    value_retained: float = Field(..., description="EPI-weighted evidential quality at time of analysis (0..1)")
    perishable_value_retained: Optional[float] = Field(
        None, description="Same metric restricted to exhibits that degrade in lab storage (where ordering matters)")
    late_count: int
    p1_mean_completion_days: Optional[float]


class ScheduleComparison(BaseModel):
    recommended: ScheduleResult
    baselines: dict[str, ScheduleResult]
    summary: str
    held_items: int = 0
    bench_hours_held: float = 0.0


class TriageResult(BaseModel):
    case_id: str
    case_ref: str
    title: Optional[str] = None
    crime_type: str
    crime_label: str
    created_at: datetime
    reference_time: datetime
    engine_version: str
    kb_hash: str
    llm_provider: str
    items: list[TriagedItem]
    gaps: list[GapAlert]
    schedule: ScheduleComparison
    custody_deadline: Optional[datetime] = None
    parse_warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    narrative: str = ""
    result_sha256: str = ""

TriagedItem.model_rebuild()
