# Problem Statement

## The situation

A serious crime scene in India routinely yields **hundreds of physical exhibits and thousands of photographs**. In the 2019 Hyderabad veterinarian case, investigators seized **more than 200 items and took 3,000+ photographs**; a **DNA-bearing cigarette butt** that later helped link the accused was nearly lost among roadside litter. The exhibits then travel to a **State Forensic Science Laboratory (FSL)** that is already overloaded, where testing is commonly delayed by **weeks**.

The pressure is structural and growing:

* **BNSS 2023 §176(3)** makes a forensic expert's visit mandatory for offences punishable with seven years or more — more scenes, more exhibits, same laboratories.
* **BNSS §187(3)** gives the police **60 or 90 days** of custody before default bail; a DNA or toxicology report that arrives late can sink a charge sheet.
* **BNSS §184** mandates prompt medical examination (including DNA samples) of sexual-assault survivors; the samples are perishable.
* Courts have repeatedly remarked on inadequate FSL capacity. Examiners are scarce; bench hours are the bottleneck.

## Who has the problem

| Stakeholder | Pain |
|---|---|
| **Investigating Officer (IO)** | Must decide in hours what to seize, preserve and forward — with no structured guidance, under public pressure, often at night. |
| **FSL Director / division heads** | Receive long forwarding letters listing exhibits in seizure order; no signal of which items are decisive, perishable or tied to a custody deadline. |
| **Public prosecutor & court** | Need to know *why* an exhibit was prioritised, that the chain of custody is intact, and what a result does **not** prove. |
| **Victims and the accused** | Delayed or degraded evidence means delayed justice, wrongful suspicion, or acquittal of the guilty. |

## Why it is hard

1. **Volume with needles.** Most exhibits are low-value litter; a handful are decisive. They look alike on a seizure list.
2. **Perishability differs by orders of magnitude.** A wet swab degrades in a day; viscera at room temperature in two; a knife is stable for years. CCTV DVRs overwrite in days; rain destroys tyre marks in hours.
3. **Examinations interfere.** Powdering for fingerprints can destroy touch DNA; destructive tests must come last.
4. **Capacity is shared.** One DNA division serves many cases; "first come, first served" lets perishable evidence rot behind stable items.
5. **Everything must be defensible.** A black-box AI ranking is unusable in court. Decisions must be explainable, reproducible and logged.
6. **Privacy.** Survivor identity is protected by **BNS 2023 §72**; personal data must be minimised (DPDP Act 2023).

## The gap

There is no tool that lets an IO turn a free-text seizure list into a **ranked, flagged, sequenced and scheduled** FSL submission — with the reasoning visible, the laboratory's capacity respected, and every action on a tamper-evident record. Pramaan fills that gap.

## Success criteria we set ourselves

* Decisive "needle" exhibits surface at the top even when listed last among hundreds of items.
* Perishable and time-critical items produce concrete **act-now** instructions (collect, seal airtight, refrigerate) with the time bought.
* Schedules measurably beat first-in-first-out on evidential value retained, late exhibits and time-to-result for critical items.
* Every score is explainable factor by factor and bit-for-bit reproducible from a knowledge-base hash.
* No personal identifiers ever enter the system.
