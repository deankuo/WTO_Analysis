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
    """Severity scoring for a WTO dispute consultation request."""

    rhetorical_intensity: int = Field(
        ge=1, le=3,
        description="1=neutral/hedged language, 2=direct/assertive, 3=aggressive/strong",
    )
    rhetorical_evidence: str = Field(
        description="Quote or paraphrase the specific language that justifies the score (max 100 words).",
    )
    core_principles: int = Field(
        ge=1, le=3,
        description="1=narrow provisions only, 2=broad WTO principles (MFN, NT), 3=frames as systemic threat",
    )
    core_principles_evidence: str = Field(
        description="List the specific principles or provisions invoked (max 100 words).",
    )
    escalation_signals: int = Field(
        ge=1, le=3,
        description="1=routine request, 2=references prior failures/patterns, 3=implies retaliation or all remedies",
    )
    escalation_evidence: str = Field(
        description="Quote or paraphrase escalation language if present (max 100 words).",
    )


# ── Task B: Third Party Severity ──────────────────────────────

class ThirdPartyScore(BaseModel):
    """Severity scoring for a third party's interest in a WTO dispute."""

    engagement_intensity: int = Field(
        ge=1, le=3,
        description=(
            "1=Routine/formulaic request ('substantial trade interest'), "
            "2=Specific interest stated with economic rationale, "
            "3=Strong language emphasizing systemic concerns or direct trade impact"
        ),
    )
    engagement_evidence: str = Field(
        description="Quote or paraphrase the specific language justifying the score (max 100 words).",
    )
    stake_specificity: int = Field(
        ge=1, le=3,
        description=(
            "1=Generic claim of trade interest, no specifics, "
            "2=Mentions specific products, trade volumes, or affected industries, "
            "3=Detailed economic stakes with quantified trade impact"
        ),
    )
    stake_evidence: str = Field(
        description="Quote or paraphrase the specificity of interest (max 100 words).",
    )
    systemic_framing: int = Field(
        ge=1, le=3,
        description=(
            "1=Focused on bilateral interest only, "
            "2=References broader WTO obligations or precedent concerns, "
            "3=Frames as threat to multilateral system or core WTO principles"
        ),
    )
    systemic_evidence: str = Field(
        description="Quote or paraphrase any systemic framing language (max 100 words).",
    )


# ── Multi-query generation ─────────────────────────────────────

class QueryVariants(BaseModel):
    """Alternative query formulations for multi-query retrieval."""

    queries: List[str] = Field(
        description="Exactly 3 alternative phrasings of the original query."
    )
