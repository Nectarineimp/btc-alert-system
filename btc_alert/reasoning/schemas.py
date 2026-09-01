from typing import Literal
from pydantic import BaseModel, Field

class MicrostructureAnalysis(BaseModel):
    regime: Literal[
        "Spot-Led Expansion", 
        "Leverage Squeeze / Exhaustion Risk", 
        "Absorption at Resistance", 
        "Mean Reverting / Consolidation"
    ] = Field(description="Dominant market microstructure state")
    
    uncertainty_level: Literal["Low", "Medium", "High"] = Field(
        description="Confidence score based on spot vs perp volume divergence and value area acceptance"
    )
    
    verbal_summary: str = Field(
        description="Concise 2-sentence natural language takeaway on order flow conviction and market bias"
    )
    
    key_risk_factor: str = Field(
        description="Single primary technical or liquidity risk to monitor"
    )