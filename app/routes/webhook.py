import json
import logging
from fastapi import APIRouter, Request, HTTPException, Header, status
from typing import Optional
from app.service import verify_webhook_signature, process_webhook_event

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Webhook"])

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Receives Instagram comment webhook events"
)
async def handle_webhook(
    request: Request,
    x_pseudogram_signature: Optional[str] = Header(None, alias="X-PseudoGram-Signature")
):
    # 1. Read raw body bytes for HMAC verification
    raw_body = await request.body()
    
    # 2. Verify signature if configured
    if not verify_webhook_signature(raw_body, x_pseudogram_signature or ""):
        logger.warning("Rejected webhook due to invalid HMAC signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )
    
    # 3. Parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Malformed JSON in webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON body"
        )
    
    # 4. Fast atomic ingestion into DB queue (returns in < 5ms)
    result = await process_webhook_event(payload)
    
    return {"status": "ok", "result": result}
