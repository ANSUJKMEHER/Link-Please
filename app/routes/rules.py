import uuid
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from app.db import create_rule, get_all_rules, delete_rule

router = APIRouter(tags=["Rules"])

class RuleCreateRequest(BaseModel):
    keyword: str = Field(..., description="The keyword to match case-insensitively")
    dm_message: str = Field(..., description="The DM text to send to the commenter")

class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str

@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new keyword-to-DM automation rule"
)
async def create_new_rule(payload: RuleCreateRequest):
    rule_id = f"rule_{uuid.uuid4().hex[:10]}"
    result = await create_rule(
        rule_id=rule_id,
        keyword=payload.keyword,
        dm_message=payload.dm_message
    )
    return result

@router.get(
    "/rules",
    response_model=List[RuleResponse],
    summary="List all active rules"
)
async def list_rules():
    return await get_all_rules()

@router.delete(
    "/rules/{rule_id}",
    summary="Delete a rule by ID"
)
async def remove_rule(rule_id: str):
    deleted = await delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted", "rule_id": rule_id}
