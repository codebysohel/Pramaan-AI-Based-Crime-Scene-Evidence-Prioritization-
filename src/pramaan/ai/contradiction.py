from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch


MODEL_NAME = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"


class EvidenceContradictionDetector:
    """
    PRAMAAN M4 - Evidence Contradiction Detector

    Compares two forensic/evidence statements and classifies
    their relationship as:

        entailment
        neutral
        contradiction

    The model is used only to FLAG possible conflicts.
    It does not automatically modify evidence records.
    """

    def __init__(self):
        print("Loading PRAMAAN M4 DeBERTa NLI model...")

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_NAME
        )

        self.model.eval()

        print("M4 model loaded successfully.\n")

    def check(self, statement_a: str, statement_b: str):
        """
        Compare two statements.

        statement_a = premise
        statement_b = hypothesis
        """

        if not statement_a.strip() or not statement_b.strip():
            raise ValueError("Both statements must contain text.")

        inputs = self.tokenizer(
            statement_a,
            statement_b,
            return_tensors="pt",
            truncation=True,
            max_length=512
        )

        with torch.no_grad():
            outputs = self.model(**inputs)

        probabilities = torch.softmax(
            outputs.logits,
            dim=-1
        )[0]

        predicted_id = int(
            torch.argmax(probabilities).item()
        )

        label = self.model.config.id2label[predicted_id]

        confidence = float(
            probabilities[predicted_id].item()
        )

        all_scores = {}

        for i, probability in enumerate(probabilities):

            current_label = self.model.config.id2label[i]

            all_scores[current_label.lower()] = round(
                float(probability.item()),
                4
            )

        return {
            "statement_a": statement_a,
            "statement_b": statement_b,
            "label": label.lower(),
            "confidence": round(confidence, 4),
            "scores": all_scores
        }


def print_result(result):

    print("=" * 70)

    print("Statement A:")
    print(result["statement_a"])

    print("\nStatement B:")
    print(result["statement_b"])

    print("\nPrediction:")
    print(result["label"].upper())

    print(
        "Confidence:",
        f"{result['confidence'] * 100:.2f}%"
    )

    print("\nAll scores:")

    for label, score in result["scores"].items():

        print(
            f"  {label:15} "
            f"{score * 100:.2f}%"
        )

    if result["label"] == "contradiction":

        print(
            "\n⚠ PRAMAAN GuardRail: "
            "Possible evidence-record conflict."
        )

        print(
            "Investigator review required."
        )

    print("=" * 70)


if __name__ == "__main__":

    detector = EvidenceContradictionDetector()

    test_cases = [

        (
            "The blood-stained shirt was wet when recovered.",
            "The blood-stained shirt was dry when recovered."
        ),

        (
            "A knife was recovered near the victim.",
            "A sharp weapon was recovered near the victim."
        ),

        (
            "A mobile phone was recovered from the suspect.",
            "A cigarette butt was found near the road."
        ),

        (
            "The cigarette butt was found three metres from the body.",
            "The cigarette butt was recovered approximately three metres from the victim."
        ),

        (
            "Exhibit EX-12 was sealed in a paper evidence bag.",
            "Exhibit EX-12 was sealed in a plastic evidence bag."
        )
    ]

    print("\n")
    print("PRAMAAN M4")
    print("Evidence Contradiction Detection")
    print("=" * 70)

    for statement_a, statement_b in test_cases:

        result = detector.check(
            statement_a,
            statement_b
        )

        print_result(result)