"""Razorpay Standard Checkout request/response schemas."""
from typing import Optional

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    payment_id: str = Field(min_length=1, max_length=32, description="The FAILED payment to collect (PAY-XXXXX).")


class CreateOrderResponse(BaseModel):
    payment_id: str
    case_id: Optional[str] = None
    order_id: str
    amount: float  # INR
    amount_paise: int  # subunits passed to the checkout modal
    currency: str


class VerifyPaymentRequest(BaseModel):
    payment_id: str = Field(min_length=1, max_length=32)
    razorpay_order_id: str = Field(min_length=4, description="order_id returned by create-order")
    razorpay_payment_id: str = Field(min_length=4, description="payment id from the checkout success handler")
    razorpay_signature: str = Field(min_length=8, description="signature from the checkout success handler")


class VerifyPaymentResponse(BaseModel):
    payment_id: str
    case_id: Optional[str] = None
    order_id: str
    razorpay_payment_id: str
    status: str  # "success" | "already_paid"
    net_recovered: float
