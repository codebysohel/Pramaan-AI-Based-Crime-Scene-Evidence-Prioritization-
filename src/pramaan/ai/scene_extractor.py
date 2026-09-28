"""
PRAMAAN-X M1
IBM Granite Fast Crime-Scene Evidence Extractor

Model:
    ibm-granite/granite-3.3-2b-instruct

Purpose:
    Convert free-text investigator scene notes into structured
    candidate evidence records.

IMPORTANT:
    M1 does NOT:
    - calculate EPI
    - assign forensic priority
    - perform final forensic classification
    - determine guilt
    - invent evidence

PRAMAAN's deterministic classifier.py performs final evidence
classification after extraction.

This implementation is optimized for CPU-only hackathon machines.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
)


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "ibm-granite/granite-3.3-2b-instruct"

# Compact JSON allows us to keep this small.
MAX_NEW_TOKENS = 220

# Standalone test output.
OUTPUT_FILE = Path(
    r"D:\ibm\m1_scene_output.json"
)

# Avoid excessive CPU thread contention.
CPU_THREADS = min(
    max(os.cpu_count() or 4, 1),
    8,
)

torch.set_num_threads(
    CPU_THREADS
)

try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass


# ============================================================
# JSON EXTRACTION
# ============================================================

def extract_json(text: str) -> dict[str, Any]:
    """
    Extract the first JSON object from Granite output.

    Granite is instructed to output JSON only, but this function
    also removes accidental Markdown fences.
    """

    text = text.strip()

    # Remove ```json and ``` fences if Granite adds them.
    text = re.sub(
        r"```(?:json)?",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = text.replace(
        "```",
        "",
    ).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1:
        raise ValueError(
            "Granite output did not contain a JSON object."
        )

    if end == -1 or end <= start:
        raise ValueError(
            "Granite output appears to contain incomplete JSON."
        )

    json_text = text[
        start:end + 1
    ]

    result = json.loads(
        json_text
    )

    if not isinstance(
        result,
        dict,
    ):
        raise ValueError(
            "Granite output must be a JSON object."
        )

    return result


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_quantity(
    value: Any,
) -> int:
    """
    Convert quantity into a safe positive integer.
    """

    try:
        quantity = int(
            value or 1
        )

    except (
        TypeError,
        ValueError,
    ):
        quantity = 1

    # Defensive upper bound.
    return max(
        1,
        min(
            quantity,
            500,
        ),
    )


def safe_distance(
    value: Any,
) -> float | None:
    """
    Convert distance to float if possible.
    """

    if value is None:
        return None

    try:
        distance = float(
            value
        )

        if distance < 0:
            return None

        return distance

    except (
        TypeError,
        ValueError,
    ):
        return None


def clean_optional_text(
    value: Any,
) -> str | None:
    """
    Normalize optional text fields.
    """

    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    return value[:500]


# ============================================================
# GRANITE M1
# ============================================================

class GraniteSceneExtractor:
    """
    Fast CPU-oriented IBM Granite scene evidence extractor.
    """

    def __init__(
        self,
    ) -> None:

        print("=" * 70)
        print(
            "PRAMAAN-X M1 — IBM GRANITE FAST CPU EXTRACTOR"
        )
        print("=" * 70)

        print(
            f"CPU threads: {CPU_THREADS}"
        )

        print(
            f"Model: {MODEL_NAME}"
        )

        # ----------------------------------------------------
        # TOKENIZER
        # ----------------------------------------------------

        print(
            "\nLoading tokenizer..."
        )

        self.tokenizer = (
            AutoTokenizer.from_pretrained(
                MODEL_NAME,
            )
        )

        # ----------------------------------------------------
        # MODEL
        # ----------------------------------------------------

        print(
            "Loading Granite model..."
        )

        self.model = (
            AutoModelForCausalLM.from_pretrained(
                MODEL_NAME,

                # Let Transformers use the model's native dtype.
                # This avoids forcing ~8 GB float32 weights.
                dtype="auto",

                low_cpu_mem_usage=True,
            )
        )

        self.model.to(
            "cpu"
        )

        self.model.eval()

        print(
            "\nM1 loaded successfully."
        )

        print(
            "Running CPU-only fast extraction mode."
        )

        print("=" * 70)


    # ========================================================
    # PROMPT
    # ========================================================

    def build_prompt(
        self,
        scene_text: str,
    ) -> list[dict[str, str]]:
        """
        Build a deliberately small extraction prompt.

        Compact JSON keys are used because repeating long JSON
        field names consumes many generation tokens.

        Compact keys:
            c = crime type
            i = items
            d = description
            q = quantity
            l = location
            m = distance in metres
            n = condition
            p = packaging
            s = exact source phrase
        """

        system_prompt = """
Extract explicitly stated crime-scene exhibits.

RULES:
- Never invent evidence.
- Extract only physical or digital items explicitly written.
- Copy a short exact supporting phrase from the notes into "s".
- Preserve stated quantities.
- Use null when information is absent.
- Do not classify evidence.
- Do not calculate priority.
- Do not explain.
- Output ONE-LINE MINIFIED JSON only.
- Stop immediately after the final }.

Keys:
c=crime type
i=items
d=description
q=quantity
l=location
m=distance metres
n=condition
p=packaging
s=exact source phrase

Format:
{"c":null,"i":[{"d":"item","q":1,"l":null,"m":null,"n":null,"p":null,"s":"exact phrase"}]}
""".strip()

        user_prompt = (
            "SCENE NOTES:\n"
            + scene_text.strip()
        )

        return [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]


    # ========================================================
    # EXTRACTION
    # ========================================================

    def extract(
        self,
        scene_text: str,
    ) -> dict[str, Any]:
        """
        Run Granite and return normalized PRAMAAN M1 output.
        """

        if not scene_text:
            raise ValueError(
                "Scene text cannot be empty."
            )

        if not scene_text.strip():
            raise ValueError(
                "Scene text cannot be blank."
            )

        print(
            "\nBuilding compact M1 prompt..."
        )

        messages = self.build_prompt(
            scene_text
        )

        # ----------------------------------------------------
        # GRANITE CHAT TEMPLATE
        # ----------------------------------------------------

        try:

            prompt = (
                self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    thinking=False,
                )
            )

        except TypeError:

            # Compatibility fallback for Transformers versions
            # where thinking=False is not supported.

            prompt = (
                self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            )

        # ----------------------------------------------------
        # TOKENIZE
        # ----------------------------------------------------

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            add_special_tokens=False,
        )

        inputs = {
            key: value.to(
                "cpu"
            )
            for key, value
            in inputs.items()
        }

        input_tokens = int(
            inputs[
                "input_ids"
            ].shape[1]
        )

        print(
            f"Prompt tokens: {input_tokens}"
        )

        print(
            f"Maximum output tokens: "
            f"{MAX_NEW_TOKENS}"
        )

        print(
            "Running Granite extraction..."
        )

        # ----------------------------------------------------
        # GENERATE
        # ----------------------------------------------------

        start_time = (
            time.perf_counter()
        )

        with torch.inference_mode():

            generated = (
                self.model.generate(
                    **inputs,

                    max_new_tokens=(
                        MAX_NEW_TOKENS
                    ),

                    # Deterministic output.
                    do_sample=False,

                    # No beam search.
                    num_beams=1,

                    # Important for autoregressive performance.
                    use_cache=True,

                    pad_token_id=(
                        self.tokenizer.eos_token_id
                    ),

                    eos_token_id=(
                        self.tokenizer.eos_token_id
                    ),
                )
            )

        elapsed = (
            time.perf_counter()
            - start_time
        )

        # ----------------------------------------------------
        # GET ONLY GENERATED TOKENS
        # ----------------------------------------------------

        new_tokens = generated[
            0,
            input_tokens:
        ]

        generated_token_count = int(
            new_tokens.numel()
        )

        raw_output = (
            self.tokenizer.decode(
                new_tokens,

                skip_special_tokens=True,

                # Prevent the harmless BPE warning you saw.
                clean_up_tokenization_spaces=False,
            )
        )

        print(
            f"Granite generation finished "
            f"in {elapsed:.1f} seconds."
        )

        print(
            f"Generated tokens: "
            f"{generated_token_count}"
        )

        # ----------------------------------------------------
        # SHOW RAW OUTPUT
        # ----------------------------------------------------

        print("\n")
        print("-" * 70)
        print("RAW GRANITE OUTPUT")
        print("-" * 70)

        print(
            raw_output
        )

        print("-" * 70)

        # ----------------------------------------------------
        # PARSE JSON
        # ----------------------------------------------------

        try:

            result = extract_json(
                raw_output
            )

        except (
            json.JSONDecodeError,
            ValueError,
        ) as exc:

            print(
                "\nERROR: Granite returned invalid "
                "or incomplete JSON."
            )

            print(
                f"Generated "
                f"{generated_token_count}/"
                f"{MAX_NEW_TOKENS} allowed tokens."
            )

            if (
                generated_token_count
                >= MAX_NEW_TOKENS
            ):

                raise RuntimeError(
                    "M1 reached MAX_NEW_TOKENS before "
                    "finishing valid JSON. "
                    "The output needs to be shortened or "
                    "MAX_NEW_TOKENS increased slightly."
                ) from exc

            raise RuntimeError(
                "Granite returned malformed JSON."
            ) from exc

        # ----------------------------------------------------
        # READ COMPACT ITEM ARRAY
        # ----------------------------------------------------

        raw_items = result.get(
            "i",
            [],
        )

        if not isinstance(
            raw_items,
            list,
        ):

            raise ValueError(
                "Granite field 'i' must be a JSON array."
            )

        # ----------------------------------------------------
        # NORMALIZE TO PRAMAAN FORMAT
        # ----------------------------------------------------

        clean_items: list[
            dict[str, Any]
        ] = []

        scene_lower = (
            scene_text
            .lower()
        )

        for index, item in enumerate(
            raw_items,
            start=1,
        ):

            if not isinstance(
                item,
                dict,
            ):
                continue

            # ------------------------------------------------
            # DESCRIPTION
            # ------------------------------------------------

            description = str(
                item.get(
                    "d",
                    "",
                )
            ).strip()

            if not description:
                continue

            description = (
                description[:500]
            )

            # ------------------------------------------------
            # SOURCE PROVENANCE
            # ------------------------------------------------

            source_text = str(
                item.get(
                    "s",
                    "",
                )
                or ""
            ).strip()

            source_text = (
                source_text[:1000]
            )

            # Exact substring provenance check.
            #
            # If Granite produces wording not found in the
            # investigator notes, GuardRail can review it.

            source_verified = bool(
                source_text
                and source_text.lower()
                in scene_lower
            )

            # ------------------------------------------------
            # QUANTITY
            # ------------------------------------------------

            quantity = safe_quantity(
                item.get(
                    "q",
                    1,
                )
            )

            # ------------------------------------------------
            # DISTANCE
            # ------------------------------------------------

            distance = safe_distance(
                item.get(
                    "m"
                )
            )

            # ------------------------------------------------
            # NORMALIZED RECORD
            # ------------------------------------------------

            normalized = {

                "item_id":
                    f"M1-{index:03d}",

                "description":
                    description,

                "quantity":
                    quantity,

                "location":
                    clean_optional_text(
                        item.get("l")
                    ),

                "distance_m":
                    distance,

                "condition":
                    clean_optional_text(
                        item.get("n")
                    ),

                "packaging":
                    clean_optional_text(
                        item.get("p")
                    ),

                "source_text":
                    source_text,

                "source_verified":
                    source_verified,
            }

            clean_items.append(
                normalized
            )

        # ----------------------------------------------------
        # FINAL NORMALIZED M1 RESULT
        # ----------------------------------------------------

        output = {

            "module":
                "M1",

            "model":
                MODEL_NAME,

            "purpose":
                "scene_evidence_extraction",

            "crime_type":
                clean_optional_text(
                    result.get("c")
                ),

            "item_count":
                len(clean_items),

            "items":
                clean_items,

            "runtime": {

                "prompt_tokens":
                    input_tokens,

                "generated_tokens":
                    generated_token_count,

                "generation_seconds":
                    round(
                        elapsed,
                        2,
                    ),

                "device":
                    "cpu",

                "cpu_threads":
                    CPU_THREADS,
            },
        }

        return output


# ============================================================
# STANDALONE TEST
# ============================================================

if __name__ == "__main__":

    # Keep this test deliberately short while developing.
    #
    # PRAMAAN's deterministic parser will independently parse
    # the same notes later and reconciliation.py will compare
    # both results.

    TEST_SCENE = """
Suspected homicide scene.

A wet blood-stained shirt was recovered beside the victim's body.
Three half-burnt cigarette butts were found 3 metres from the body.
A kitchen knife was recovered from underneath the bed.
""".strip()

    print("\n")
    print("=" * 70)
    print("STARTING PRAMAAN-X M1 TEST")
    print("=" * 70)

    extractor = (
        GraniteSceneExtractor()
    )

    result = extractor.extract(
        TEST_SCENE
    )

    print("\n")
    print("=" * 70)
    print("PRAMAAN-X M1 NORMALIZED RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )

    # --------------------------------------------------------
    # SAVE RESULT
    # --------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n")
    print("=" * 70)

    print(
        "M1 completed successfully."
    )

    print(
        "Saved M1 output to:"
    )

    print(
        OUTPUT_FILE
    )

    print("=" * 70)