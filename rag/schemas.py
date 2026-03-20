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


# ── Task B: Severity Scoring (4 dimensions, 1-5 each) ────────

class SeverityScore(BaseModel):
    """Complainant severity scoring — 4 dimensions on 1-5 scale."""

    rhetorical_aggressiveness: int = Field(
        ge=1, le=5,
        description="1=Procedural/hedged, 3=Assertive, 5=Hostile/geopolitical framing.",
    )
    systemic_reach: int = Field(
        ge=1, le=5,
        description="1=Product-specific, 3=Sector-wide, 5=Regime-challenging (as-such).",
    )
    escalation_ultimatum: int = Field(
        ge=1, le=5,
        description="1=Routine procedural, 3=Breakdown of negotiations, 5=Retaliatory/rebalancing.",
    )
    domestic_victimhood: int = Field(
        ge=1, le=5,
        description="1=No domestic pain mentioned, 3=Economic loss with data, 5=Existential threat.",
    )
    reasoning: str = Field(
        description="Brief explanation per dimension (max 2 sentences each).",
    )
    evidence: str = Field(
        description="Key direct quotes from the text supporting the scores.",
    )


# ── Task B: Third Party Engagement (3 dimensions, 1-5 each) ──

class ThirdPartyScore(BaseModel):
    """Third party engagement scoring — 3 dimensions on 1-5 scale."""

    engagement_intensity: int = Field(
        ge=1, le=5,
        description="1=Formulaic/procedural, 3=Substantive motivation, 5=Highly engaged/challenging.",
    )
    evidentiary_depth: int = Field(
        ge=1, le=5,
        description="1=No data, 3=Specific trade data, 5=Crisis-level dependency stats.",
    )
    rhetorical_severity: int = Field(
        ge=1, le=5,
        description="1=Neutral/observational, 3=Critical/negative impact, 5=Existential/crisis rhetoric.",
    )
    reasoning: str = Field(
        description="Brief explanation per dimension.",
    )
    evidence: str = Field(
        description="Key quotes from the document supporting the scores.",
    )
    alignment: str = Field(
        description="Third party alignment: 'Neutral', 'Complainant', or 'Respondent'.",
    )


# ── Multi-query generation ─────────────────────────────────────

class QueryVariants(BaseModel):
    """Alternative query formulations for multi-query retrieval."""

    queries: List[str] = Field(
        description="Exactly 3 alternative phrasings of the original query."
    )
