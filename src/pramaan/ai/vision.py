import json
import re
from pathlib import Path

import torch
from transformers import AutoProcessor

# ============================================================
# TRANSFORMERS VERSION COMPATIBILITY
# ============================================================

try:
    # Transformers v5+
    from transformers import AutoModelForImageTextToText as VisionModel
    MODEL_API = "AutoModelForImageTextToText"
except ImportError:
    try:
        # Transformers v4
        from transformers import AutoModelForVision2Seq as VisionModel
        MODEL_API = "AutoModelForVision2Seq"
    except ImportError:
        raise ImportError(
            "\nCould not find a compatible vision model class.\n"
            "Run:\n"
            "C:\\Python314\\python.exe -m pip install --upgrade transformers torch torchvision Pillow\n"
        )


# ============================================================
# PRAMAAN M5
# GRANITE VISION EVIDENCE SHADOW SCAN
# ============================================================

MODEL_NAME = "ibm-granite/granite-vision-3.3-2b"


PRAMAAN_EVIDENCE_TYPES = [
    "bloodstain",
    "reference_blood",
    "semen_stain",
    "sexual_assault_kit",
    "saliva_swab",
    "cigarette_butt",
    "drinking_vessel",
    "litter_wrapper",
    "hair",
    "fingernail_scrapings",
    "charred_remains",
    "condom",
    "clothing",
    "footwear_item",
    "glass_fragments",
    "paint_transfer",
    "soil",
    "fibres",
    "latent_print_surface",
    "footwear_impression",
    "tyre_impression",
    "tool_marks",
    "sharp_weapon",
    "blunt_weapon",
    "ligature",
    "firearm",
    "cartridge_case",
    "projectile",
    "gsr_kit",
    "viscera",
    "body_fluid_tox",
    "poison_container",
    "accelerant_container",
    "fire_debris",
    "narcotics",
    "mobile_phone",
    "cctv_dvr",
    "computer_storage",
    "questioned_document",
    "vehicle",
    "other_object",
]


class GraniteEvidenceShadowScanner:

    def __init__(self):

        print("=" * 70)
        print("PRAMAAN M5")
        print("Granite Vision Evidence Shadow Scan")
        print("=" * 70)

        print(f"\nModel API: {MODEL_API}")

        # ----------------------------------------------------
        # DEVICE SELECTION
        # ----------------------------------------------------

        if torch.cuda.is_available():

            self.device = "cuda"

            if torch.cuda.is_bf16_supported():
                self.dtype = torch.bfloat16
            else:
                self.dtype = torch.float16

            print("Device: NVIDIA GPU")

        else:

            self.device = "cpu"
            self.dtype = torch.float32

            print("Device: CPU")
            print(
                "WARNING: Granite Vision will be much slower on CPU."
            )

        print(f"Model: {MODEL_NAME}")
        print("\nLoading processor...")

        # ----------------------------------------------------
        # PROCESSOR
        # ----------------------------------------------------

        self.processor = AutoProcessor.from_pretrained(
            MODEL_NAME
        )

        print("Processor loaded.")

        print("\nLoading Granite Vision model...")
        print(
            "NOTE: First run downloads the pretrained model."
        )

        # ----------------------------------------------------
        # MODEL
        # ----------------------------------------------------

        self.model = VisionModel.from_pretrained(
            MODEL_NAME,
            torch_dtype=self.dtype
        )

        self.model = self.model.to(self.device)

        self.model.eval()

        print("\nM5 loaded successfully.")
        print("=" * 70)

    # ========================================================
    # BUILD FORENSIC PROMPT
    # ========================================================

    def build_prompt(self, manifest=None):

        evidence_types = ", ".join(
            PRAMAAN_EVIDENCE_TYPES
        )

        if manifest:

            manifest_text = "\n".join(
                f"- {item}"
                for item in manifest
            )

        else:

            manifest_text = (
                "No investigator manifest was supplied."
            )

        prompt = f"""
You are PRAMAAN M5, an AI-assisted visual screening component
for forensic evidence triage.

Your task is to inspect the supplied scene photograph and identify
VISIBLE OBJECTS OR FEATURES that may deserve investigator review.

IMPORTANT RULES:

1. Do not determine guilt.
2. Do not identify people.
3. Do not claim that an object is confirmed forensic evidence.
4. Do not invent objects that are not visibly supported.
5. Do not automatically add evidence to the case.
6. If uncertain, explicitly say that you are uncertain.
7. Every candidate requires investigator confirmation.

PRAMAAN evidence taxonomy:

{evidence_types}

The investigator currently recorded these exhibits:

{manifest_text}

Inspect the image.

For every visually supported candidate:

- describe what is visible
- suggest the closest PRAMAAN evidence type
- describe its approximate location in the image
- provide visual confidence: HIGH, MEDIUM, or LOW
- compare it against the investigator manifest
- state whether it appears already listed
- briefly explain why it may deserve review

Return ONLY JSON.

Use exactly this structure:

{{
    "scene_summary": "brief scene description",

    "candidates": [
        {{
            "visual_description": "visible object or feature",

            "suggested_type": "PRAMAAN evidence type",

            "location": "approximate image location",

            "visual_confidence": "HIGH",

            "manifest_status": "LISTED",

            "reason": "why investigator review may be useful"
        }}
    ],

    "possible_unlisted_count": 0,

    "requires_investigator_review": true
}}

Allowed manifest_status values:

LISTED
POSSIBLY_LISTED
NOT_LISTED
UNKNOWN

Allowed visual_confidence values:

HIGH
MEDIUM
LOW

If nothing relevant is clearly visible, return:

{{
    "scene_summary": "brief scene description",
    "candidates": [],
    "possible_unlisted_count": 0,
    "requires_investigator_review": false
}}

Remember:

Visual candidate does NOT mean confirmed evidence.
"""

        return prompt.strip()

    # ========================================================
    # JSON CLEANING
    # ========================================================

    @staticmethod
    def extract_json(text):

        text = text.strip()

        # Remove markdown JSON fences
        text = re.sub(
            r"^```json\s*",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"^```\s*",
            "",
            text
        )

        text = re.sub(
            r"\s*```$",
            "",
            text
        )

        text = text.strip()

        # First attempt
        try:

            return json.loads(text)

        except json.JSONDecodeError:

            pass

        # Second attempt:
        # find first { and last }

        start = text.find("{")
        end = text.rfind("}")

        if start != -1 and end != -1:

            json_text = text[start:end + 1]

            try:

                return json.loads(json_text)

            except json.JSONDecodeError:

                pass

        # Never silently invent results

        return {

            "scene_summary": "",

            "candidates": [],

            "possible_unlisted_count": 0,

            "requires_investigator_review": True,

            "parse_error": True,

            "raw_model_output": text
        }

    # ========================================================
    # VALIDATE RESULT
    # ========================================================

    @staticmethod
    def validate_result(result):

        if "candidates" not in result:

            result["candidates"] = []

        if not isinstance(
            result["candidates"],
            list
        ):

            result["candidates"] = []

        valid_types = set(
            PRAMAAN_EVIDENCE_TYPES
        )

        valid_confidence = {
            "HIGH",
            "MEDIUM",
            "LOW"
        }

        valid_manifest_status = {
            "LISTED",
            "POSSIBLY_LISTED",
            "NOT_LISTED",
            "UNKNOWN"
        }

        cleaned = []

        for candidate in result["candidates"]:

            if not isinstance(
                candidate,
                dict
            ):
                continue

            evidence_type = candidate.get(
                "suggested_type",
                "other_object"
            )

            if evidence_type not in valid_types:

                evidence_type = "other_object"

            confidence = str(
                candidate.get(
                    "visual_confidence",
                    "LOW"
                )
            ).upper()

            if confidence not in valid_confidence:

                confidence = "LOW"

            manifest_status = str(
                candidate.get(
                    "manifest_status",
                    "UNKNOWN"
                )
            ).upper()

            if (
                manifest_status
                not in valid_manifest_status
            ):

                manifest_status = "UNKNOWN"

            cleaned.append({

                "visual_description":
                    candidate.get(
                        "visual_description",
                        "Unknown object"
                    ),

                "suggested_type":
                    evidence_type,

                "location":
                    candidate.get(
                        "location",
                        "Unknown"
                    ),

                "visual_confidence":
                    confidence,

                "manifest_status":
                    manifest_status,

                "reason":
                    candidate.get(
                        "reason",
                        ""
                    )
            })

        result["candidates"] = cleaned

        # Calculate possible unlisted candidates ourselves
        # rather than trusting the model count.

        unlisted = sum(

            1

            for candidate in cleaned

            if candidate["manifest_status"]
            == "NOT_LISTED"
        )

        result[
            "possible_unlisted_count"
        ] = unlisted

        result[
            "requires_investigator_review"
        ] = bool(cleaned)

        return result

    # ========================================================
    # SCAN IMAGE
    # ========================================================

    def scan(
        self,
        image_path,
        manifest=None
    ):

        image_path = Path(
            image_path
        ).resolve()

        # ----------------------------------------------------
        # CHECK FILE
        # ----------------------------------------------------

        if not image_path.exists():

            raise FileNotFoundError(
                f"\nImage not found:\n{image_path}"
            )

        allowed_extensions = {
            ".jpg",
            ".jpeg",
            ".png"
        }

        if (
            image_path.suffix.lower()
            not in allowed_extensions
        ):

            raise ValueError(
                "M5 supports JPG, JPEG and PNG."
            )

        print("\nImage:")
        print(image_path)

        # ----------------------------------------------------
        # PROMPT
        # ----------------------------------------------------

        prompt = self.build_prompt(
            manifest
        )

        # Granite official conversation format

        conversation = [

            {
                "role": "user",

                "content": [

                    {
                        "type": "image",
                        "url": str(image_path)
                    },

                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]

        print(
            "\nPreparing image for Granite Vision..."
        )

        # ----------------------------------------------------
        # PROCESS INPUT
        # ----------------------------------------------------

        inputs = (
            self.processor.apply_chat_template(

                conversation,

                add_generation_prompt=True,

                tokenize=True,

                return_dict=True,

                return_tensors="pt"
            )
        )

        # Move tensors to device

        inputs = {

            key:
                value.to(self.device)
                if hasattr(value, "to")
                else value

            for key, value
            in inputs.items()
        }

        print(
            "Running Evidence Shadow Scan..."
        )

        # ----------------------------------------------------
        # GENERATE
        # ----------------------------------------------------

        with torch.inference_mode():

            output = self.model.generate(

                **inputs,

                max_new_tokens=700,

                do_sample=False
            )

        # ----------------------------------------------------
        # DECODE ONLY NEW TOKENS
        # ----------------------------------------------------

        input_length = (
            inputs["input_ids"].shape[-1]
        )

        generated_tokens = (
            output[0][input_length:]
        )

        response = (
            self.processor.decode(

                generated_tokens,

                skip_special_tokens=True
            )
        )

        # ----------------------------------------------------
        # PARSE JSON
        # ----------------------------------------------------

        result = self.extract_json(
            response
        )

        result = self.validate_result(
            result
        )

        # Add provenance information

        result["model"] = MODEL_NAME

        result["model_api"] = MODEL_API

        result["image"] = image_path.name

        result["status"] = (
            "AI_CANDIDATE_ONLY"
        )

        result["human_confirmation_required"] = True

        return result


# ============================================================
# PRINT RESULT
# ============================================================

def print_shadow_scan(result):

    print("\n")
    print("=" * 70)

    print(
        "PRAMAAN M5 - EVIDENCE SHADOW SCAN"
    )

    print("=" * 70)

    print("\nImage:")

    print(
        result.get(
            "image",
            "Unknown"
        )
    )

    print("\nScene Summary:")

    print(
        result.get(
            "scene_summary",
            "No summary returned."
        )
    )

    candidates = result.get(
        "candidates",
        []
    )

    print(
        f"\nCandidates detected: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # DISPLAY CANDIDATES
    # --------------------------------------------------------

    for number, candidate in enumerate(
        candidates,
        start=1
    ):

        print("\n" + "-" * 70)

        print(
            f"CANDIDATE {number}"
        )

        print("-" * 70)

        print(
            "Visible object:",
            candidate.get(
                "visual_description"
            )
        )

        print(
            "Suggested type:",
            candidate.get(
                "suggested_type"
            )
        )

        print(
            "Location:",
            candidate.get(
                "location"
            )
        )

        print(
            "Visual confidence:",
            candidate.get(
                "visual_confidence"
            )
        )

        print(
            "Manifest status:",
            candidate.get(
                "manifest_status"
            )
        )

        print(
            "Reason:",
            candidate.get(
                "reason"
            )
        )

    # --------------------------------------------------------
    # GUARDRAIL
    # --------------------------------------------------------

    print("\n" + "=" * 70)

    unlisted = result.get(
        "possible_unlisted_count",
        0
    )

    if unlisted > 0:

        print(
            f"PRAMAAN GUARDRAIL:"
        )

        print(
            f"{unlisted} possible unlisted "
            f"visual candidate(s) detected."
        )

        print(
            "Investigator confirmation required."
        )

    else:

        print(
            "No unlisted visual candidates "
            "were reported."
        )

    print("\nSTATUS:")

    print(
        "AI CANDIDATE ONLY - "
        "NOT CONFIRMED FORENSIC EVIDENCE"
    )

    print("=" * 70)


# ============================================================
# MAIN TEST
# ============================================================

if __name__ == "__main__":

    try:

        # ----------------------------------------------------
        # LOAD MODEL
        # ----------------------------------------------------

        scanner = (
            GraniteEvidenceShadowScanner()
        )

        # ----------------------------------------------------
        # TEST IMAGE
        # ----------------------------------------------------

        TEST_IMAGE = (
            r"D:\ibm\download.webp"
        )

        # ----------------------------------------------------
        # EXISTING INVESTIGATOR MANIFEST
        # ----------------------------------------------------

        manifest = [

            "EX-001 bloodstain near victim",

            "EX-002 mobile phone near table",

            "EX-003 knife recovered near body"
        ]

        # ----------------------------------------------------
        # RUN M5
        # ----------------------------------------------------

        result = scanner.scan(

            image_path=TEST_IMAGE,

            manifest=manifest
        )

        # ----------------------------------------------------
        # DISPLAY RESULT
        # ----------------------------------------------------

        print_shadow_scan(
            result
        )

        # ----------------------------------------------------
        # SAVE JSON
        # ----------------------------------------------------

        output_file = Path(
            r"D:\ibm\m5_shadow_scan.json"
        )

        output_file.write_text(

            json.dumps(

                result,

                indent=2,

                ensure_ascii=False
            ),

            encoding="utf-8"
        )

        print(
            "\nM5 JSON saved to:"
        )

        print(
            output_file
        )

    except KeyboardInterrupt:

        print(
            "\nM5 stopped by user."
        )

    except Exception as error:

        print("\n" + "=" * 70)

        print(
            "M5 ERROR"
        )

        print("=" * 70)

        print(
            type(error).__name__
        )

        print(
            str(error)
        )

        print("=" * 70)

        raise