"""
PRAMAAN-X M2
Pretrained YOLO-World Visual Evidence Candidate Detector

Model:
    yolov8s-worldv2.pt

Purpose:
    Detect visible crime-scene object candidates from photographs
    using open-vocabulary object detection.

IMPORTANT:
    M2 detections are CANDIDATES only.

    M2 does NOT:
    - confirm that an object is forensic evidence
    - calculate EPI
    - assign forensic priority
    - determine guilt
    - automatically add evidence to the case
    - replace investigator confirmation

Pipeline:

    Scene photograph
          |
          v
    YOLO-World
          |
          v
    Visual candidate
          |
          v
    PRAMAAN type mapping
          |
          v
    GuardRail / Digital Twin
          |
          v
    Investigator confirmation
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import torch
from ultralytics import YOLOWorld


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "yolov8s-worldv2.pt"

DEFAULT_CONFIDENCE = 0.20

IMAGE_SIZE = 640

OUTPUT_FILE = Path(
    r"D:\ibm\m2_visual_output.json"
)


# ============================================================
# OPEN-VOCABULARY FORENSIC PROMPTS
# ============================================================

# These are VISUAL prompts, not PRAMAAN evidence types.
#
# Do not put concepts here that are inherently invisible
# in an ordinary scene photograph, e.g. DNA profile.

FORENSIC_CLASSES = [

    # Weapons
    "knife",
    "handgun",
    "pistol",
    "revolver",
    "rifle",
    "shotgun",
    "hammer",
    "baseball bat",
    "rope",

    # Biological / scene material
    "blood stain",
    "blood stained clothing",
    "hair",

    # Trace / physical objects
    "broken glass",
    "glass fragment",
    "cigarette butt",

    # Ballistics
    "bullet",
    "cartridge case",

    # Containers / chemical context
    "bottle",
    "chemical container",
    "fuel container",

    # Digital evidence
    "mobile phone",
    "smartphone",
    "laptop",
    "computer",
    "hard drive",
    "USB drive",
    "camera",
    "CCTV camera",

    # Documents
    "document",
    "paper",

    # Clothing / impressions
    "shoe",
    "footwear",
    "clothing",
    "shirt",

    # Vehicles / miscellaneous
    "car",
    "motorcycle",
    "bag",
    "backpack",
]


# ============================================================
# PRAMAAN TYPE MAPPING
# ============================================================

# Visual labels are mapped into the EXISTING deterministic
# PRAMAAN evidence taxonomy.
#
# This mapping does NOT mean YOLO has forensically confirmed
# the evidence type. It is simply a candidate mapping.

PRAMAAN_TYPE_MAP = {

    # --------------------------------------------------------
    # WEAPONS
    # --------------------------------------------------------

    "knife":
        "sharp_weapon",

    "handgun":
        "firearm",

    "pistol":
        "firearm",

    "revolver":
        "firearm",

    "rifle":
        "firearm",

    "shotgun":
        "firearm",

    "hammer":
        "blunt_weapon",

    "baseball bat":
        "blunt_weapon",

    "rope":
        "ligature",

    # --------------------------------------------------------
    # BIOLOGICAL
    # --------------------------------------------------------

    "blood stain":
        "bloodstain",

    "blood stained clothing":
        "clothing",

    "hair":
        "hair",

    "cigarette butt":
        "cigarette_butt",

    # --------------------------------------------------------
    # TRACE / PHYSICAL
    # --------------------------------------------------------

    "broken glass":
        "glass_fragments",

    "glass fragment":
        "glass_fragments",

    # --------------------------------------------------------
    # BALLISTICS
    # --------------------------------------------------------

    "bullet":
        "projectile",

    "cartridge case":
        "cartridge_case",

    # --------------------------------------------------------
    # CONTAINERS
    # --------------------------------------------------------

    "bottle":
        "other_object",

    "chemical container":
        "poison_container",

    "fuel container":
        "accelerant_container",

    # --------------------------------------------------------
    # DIGITAL
    # --------------------------------------------------------

    "mobile phone":
        "mobile_phone",

    "smartphone":
        "mobile_phone",

    "laptop":
        "computer_storage",

    "computer":
        "computer_storage",

    "hard drive":
        "computer_storage",

    "USB drive":
        "computer_storage",

    "camera":
        "other_object",

    "CCTV camera":
        "cctv_dvr",

    # --------------------------------------------------------
    # DOCUMENTS
    # --------------------------------------------------------

    "document":
        "questioned_document",

    "paper":
        "questioned_document",

    # --------------------------------------------------------
    # CLOTHING / FOOTWEAR
    # --------------------------------------------------------

    "shoe":
        "footwear_item",

    "footwear":
        "footwear_item",

    "clothing":
        "clothing",

    "shirt":
        "clothing",

    # --------------------------------------------------------
    # VEHICLES / MISC
    # --------------------------------------------------------

    "car":
        "vehicle",

    "motorcycle":
        "vehicle",

    "bag":
        "other_object",

    "backpack":
        "other_object",
}


# ============================================================
# HELPERS
# ============================================================

def choose_device() -> str:
    """
    Automatically select CUDA when available.

    Your current machine can run CPU-only, so CPU is a valid
    fallback.
    """

    if torch.cuda.is_available():
        return "cuda:0"

    return "cpu"


def normalise_label(
    value: str,
) -> str:

    return (
        value
        .strip()
        .lower()
    )


def map_to_pramaan(
    label: str,
) -> str:

    return PRAMAAN_TYPE_MAP.get(
        normalise_label(label),
        "other_object",
    )


# ============================================================
# M2 DETECTOR
# ============================================================

class ForensicYOLOWorldDetector:
    """
    PRAMAAN-X M2 open-vocabulary visual detector.
    """

    def __init__(
        self,
        *,
        model_name: str = MODEL_NAME,
        confidence: float = DEFAULT_CONFIDENCE,
        image_size: int = IMAGE_SIZE,
        classes: list[str] | None = None,
    ) -> None:

        print("=" * 70)
        print(
            "PRAMAAN-X M2 — YOLO-WORLD VISUAL DETECTOR"
        )
        print("=" * 70)

        self.model_name = model_name

        self.confidence = confidence

        self.image_size = image_size

        self.classes = (
            list(classes)
            if classes
            else list(FORENSIC_CLASSES)
        )

        self.device = choose_device()

        print(
            f"Model: {self.model_name}"
        )

        print(
            f"Device: {self.device}"
        )

        print(
            f"Visual prompts: {len(self.classes)}"
        )

        print(
            "\nLoading pretrained YOLO-World..."
        )

        # First execution may download the pretrained
        # yolov8s-worldv2.pt weights.
        self.model = YOLOWorld(
            self.model_name
        )

        print(
            "Setting forensic visual vocabulary..."
        )

        # YOLO-World supports dynamically supplied classes.
        self.model.set_classes(
            self.classes
        )

        print(
            "\nM2 loaded successfully."
        )

        print("=" * 70)


    # ========================================================
    # DETECTION
    # ========================================================

    def detect(
        self,
        image_path: str | Path,
        *,
        save_annotated: bool = True,
        annotated_dir: str | Path | None = None,
    ) -> dict[str, Any]:

        image_path = Path(
            image_path
        )

        if not image_path.exists():

            raise FileNotFoundError(
                f"Scene image not found: {image_path}"
            )

        print(
            f"\nAnalyzing scene image:"
        )

        print(
            image_path
        )

        print(
            "\nRunning M2 visual detection..."
        )

        start = time.perf_counter()

        # ----------------------------------------------------
        # YOLO INFERENCE
        # ----------------------------------------------------

        results = self.model.predict(

            source=str(
                image_path
            ),

            conf=self.confidence,

            imgsz=self.image_size,

            device=self.device,

            verbose=False,
        )

        elapsed = (
            time.perf_counter()
            - start
        )

        detections: list[
            dict[str, Any]
        ] = []

        # ====================================================
        # PROCESS RESULTS
        # ====================================================

        for result in results:

            boxes = result.boxes

            if boxes is None:
                continue

            for index, box in enumerate(
                boxes,
                start=1,
            ):

                # --------------------------------------------
                # CLASS ID
                # --------------------------------------------

                class_id = int(
                    box.cls[0].item()
                )

                # --------------------------------------------
                # LABEL
                # --------------------------------------------

                names = result.names

                if isinstance(
                    names,
                    dict,
                ):

                    label = names.get(
                        class_id,
                        f"class_{class_id}",
                    )

                else:

                    label = names[
                        class_id
                    ]

                label = str(
                    label
                )

                # --------------------------------------------
                # CONFIDENCE
                # --------------------------------------------

                confidence = float(
                    box.conf[0].item()
                )

                # --------------------------------------------
                # BOUNDING BOX
                # --------------------------------------------

                coordinates = (
                    box.xyxy[0]
                    .cpu()
                    .tolist()
                )

                x1, y1, x2, y2 = [
                    round(
                        float(value),
                        2,
                    )
                    for value in coordinates
                ]

                width = max(
                    0.0,
                    x2 - x1,
                )

                height = max(
                    0.0,
                    y2 - y1,
                )

                center_x = (
                    x1 + x2
                ) / 2.0

                center_y = (
                    y1 + y2
                ) / 2.0

                # --------------------------------------------
                # PRAMAAN MAPPING
                # --------------------------------------------

                pramaan_type = (
                    map_to_pramaan(
                        label
                    )
                )

                # --------------------------------------------
                # DETECTION
                # --------------------------------------------

                detection = {

                    "detection_id":
                        f"M2-{len(detections) + 1:03d}",

                    "visual_label":
                        label,

                    "visual_confidence":
                        round(
                            confidence,
                            4,
                        ),

                    "pramaan_type_candidate":
                        pramaan_type,

                    "bbox": {

                        "x1":
                            x1,

                        "y1":
                            y1,

                        "x2":
                            x2,

                        "y2":
                            y2,

                        "width":
                            round(
                                width,
                                2,
                            ),

                        "height":
                            round(
                                height,
                                2,
                            ),

                        "center_x":
                            round(
                                center_x,
                                2,
                            ),

                        "center_y":
                            round(
                                center_y,
                                2,
                            ),
                    },

                    # ----------------------------------------
                    # IMPORTANT FORENSIC SAFETY
                    # ----------------------------------------

                    "status":
                        "VISUAL_CANDIDATE",

                    "requires_investigator_confirmation":
                        True,

                    "confirmed_evidence":
                        False,

                    "source": {

                        "module":
                            "M2",

                        "model":
                            self.model_name,

                        "image":
                            image_path.name,
                    },
                }

                detections.append(
                    detection
                )

        # ====================================================
        # ANNOTATED IMAGE
        # ====================================================

        annotated_path = None

        if (
            save_annotated
            and results
        ):

            if annotated_dir is None:

                annotated_dir = (
                    image_path.parent
                    / "m2_output"
                )

            annotated_dir = Path(
                annotated_dir
            )

            annotated_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            annotated_path = (
                annotated_dir
                / (
                    image_path.stem
                    + "_m2.jpg"
                )
            )

            # result.save() writes the plotted image.
            results[0].save(
                filename=str(
                    annotated_path
                )
            )

        # ====================================================
        # SUMMARY BY TYPE
        # ====================================================

        type_counts: dict[
            str,
            int,
        ] = {}

        for detection in detections:

            evidence_type = detection[
                "pramaan_type_candidate"
            ]

            type_counts[
                evidence_type
            ] = (
                type_counts.get(
                    evidence_type,
                    0,
                )
                + 1
            )

        # ====================================================
        # FINAL OUTPUT
        # ====================================================

        output = {

            "module":
                "M2",

            "model":
                self.model_name,

            "purpose":
                "visual_evidence_candidate_detection",

            "image": {

                "filename":
                    image_path.name,

                "path":
                    str(
                        image_path.resolve()
                    ),
            },

            "detection_count":
                len(
                    detections
                ),

            "detections":
                detections,

            "summary": {

                "candidate_types":
                    type_counts,

                "requires_investigator_confirmation":
                    True,
            },

            "runtime": {

                "generation_seconds":
                    round(
                        elapsed,
                        3,
                    ),

                "device":
                    self.device,

                "confidence_threshold":
                    self.confidence,

                "image_size":
                    self.image_size,
            },

            "annotated_image":
                (
                    str(
                        annotated_path.resolve()
                    )
                    if annotated_path
                    else None
                ),

            "limitations": [

                (
                    "M2 detections are visual candidates, "
                    "not confirmed forensic evidence."
                ),

                (
                    "Open-vocabulary confidence is a model "
                    "detection score, not forensic certainty."
                ),

                (
                    "Small, obscured, transparent, biological, "
                    "or trace evidence may not be detected."
                ),

                (
                    "A missing M2 detection must never be "
                    "interpreted as evidence being absent."
                ),
            ],
        }

        return output


# ============================================================
# SAVE RESULT
# ============================================================

def save_result(
    result: dict[str, Any],
    output_file: str | Path,
) -> Path:

    output_file = Path(
        output_file
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file.write_text(

        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),

        encoding="utf-8",
    )

    return output_file


# ============================================================
# STANDALONE TEST
# ============================================================

if __name__ == "__main__":

    print("\n")
    print("=" * 70)
    print(
        "STARTING PRAMAAN-X M2 TEST"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # CHANGE THIS TO YOUR TEST CRIME-SCENE IMAGE
    # --------------------------------------------------------

    TEST_IMAGE = Path(
        r"D:\ibm\test_scene.jpg"
    )

    if not TEST_IMAGE.exists():

        print(
            "\nM2 is installed, but the test image "
            "does not exist."
        )

        print(
            "\nPut a test image here:"
        )

        print(
            TEST_IMAGE
        )

        print(
            "\nThen run this file again."
        )

        raise SystemExit(
            0
        )

    # --------------------------------------------------------
    # LOAD M2
    # --------------------------------------------------------

    detector = (
        ForensicYOLOWorldDetector()
    )

    # --------------------------------------------------------
    # DETECT
    # --------------------------------------------------------

    result = detector.detect(
        TEST_IMAGE,
        save_annotated=True,
    )

    # --------------------------------------------------------
    # PRINT
    # --------------------------------------------------------

    print("\n")
    print("=" * 70)
    print(
        "PRAMAAN-X M2 RESULT"
    )
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    saved = save_result(
        result,
        OUTPUT_FILE,
    )

    print("\n")
    print("=" * 70)

    print(
        "M2 completed successfully."
    )

    print(
        "Saved M2 JSON to:"
    )

    print(
        saved
    )

    if result[
        "annotated_image"
    ]:

        print(
            "\nAnnotated image:"
        )

        print(
            result[
                "annotated_image"
            ]
        )

    print("=" * 70)