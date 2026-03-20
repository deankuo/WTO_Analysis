"""Pydantic models for structured LLM output.

Used with `llm.with_structured_output(Schema)` to guarantee
well-typed responses from extraction and scoring prompts.
"""

from typing import List, Literal

from pydantic import BaseModel, Field


# ── Task A Stage 1: Industry / Product Extraction ─────────────

class IndustryExtraction(BaseModel):
    """Extracted industry/product information from a WTO dispute case."""

    product_descriptions: List[str] = Field(
        description=(
            "All products or industries mentioned in the dispute. "
            "Use natural language descriptions, e.g., 'hot-rolled steel products', "
            "'fresh and chilled Atlantic salmon', 'automobile parts and components'."
        )
    )
    explicit_hs_codes: List[str] = Field(
        default_factory=list,
        description=(
            "Any Harmonized System codes explicitly mentioned in the text. "
            "Include 2-digit, 4-digit, or 6-digit codes as found. "
            "Leave empty if no explicit codes are mentioned."
        ),
    )
    is_systemic: bool = Field(
        description=(
            "True if the dispute challenges a systemic measure "
            "(e.g., an entire anti-dumping law, customs procedures, IP regime) "
            "rather than targeting specific traded products."
        )
    )
    is_services: bool = Field(
        description="True if the dispute concerns services (GATS) rather than goods."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "'high' if explicit HS codes found; "
            "'medium' if clear product descriptions but no HS codes; "
            "'low' if vague descriptions or systemic/services case."
        )
    )
    notes: str = Field(
        default="",
        description="Brief note on any ambiguity or edge cases.",
    )


# ── Task A Stage 2: HS Section Classification ─────────────────

class HSClassification(BaseModel):
    """Classification of product descriptions into HS sections."""

    sections: List[int] = Field(
        description="List of HS section numbers (1-21) that correspond to the products described."
    )
    reasoning: str = Field(
        description="Brief explanation of why these sections were selected."
    )


# ── Task B: Severity Scoring ──────────────────────────────────

class SeverityScore(BaseModel):
    """Complainant severity scoring (1-5 scale)."""

    score: int = Field(
        ge=1, le=5,
        description=(
            "1=Procedural/hedged (e.g., DS3), "
            "2=Formal/technical, "
            "3=Assertive with data/losses (e.g., DS267), "
            "4=Strong systemic impairment claims, "
            "5=Aggressive/geopolitical confrontation (e.g., DS574)"
        ),
    )
    reasoning: str = Field(
        description="2-sentence explanation of why this score was chosen (max 50 words).",
    )
    evidence: str = Field(
        description="Direct quote from the text that best supports the score.",
    )


# ── Task B: Third Party Engagement ───────────────────────────

class ThirdPartyScore(BaseModel):
    """Third party engagement scoring (1-5 scale)."""

    score: int = Field(
        ge=1, le=5,
        description=(
            "1=Formulaic/procedural (e.g., DS109), "
            "2=Minimalist with sector identification, "
            "3=Substantive/evidentiary (e.g., DS434), "
            "4=Strategic/systemic policy concerns, "
            "5=Existential/urgent rhetoric (e.g., DS27)"
        ),
    )
    reasoning: str = Field(
        description="2-sentence explanation of why this score was chosen (max 50 words).",
    )
    evidence: str = Field(
        description="The most telling phrase or sentence from the document.",
    )
    interest_type: str = Field(
        description="Classify as either 'Systemic' (rule-focused) or 'Commercial' (market-access focused).",
    )


# ── Multi-query generation ─────────────────────────────────────

class QueryVariants(BaseModel):
    """Alternative query formulations for multi-query retrieval."""

    queries: List[str] = Field(
        description="Exactly 3 alternative phrasings of the original query."
    )
