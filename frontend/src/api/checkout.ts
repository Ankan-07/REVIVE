import { apiFetch, jsonPost } from './client';

export interface CreateOrderResponse {
  payment_id: string;
  case_id?: string | null;
  order_id: string;
  amount: number; // INR
  amount_paise: number; // subunits for the checkout modal
  currency: string;
}

export interface VerifyPaymentResponse {
  payment_id: string;
  case_id?: string | null;
  order_id: string;
  razorpay_payment_id: string;
  status: 'success' | 'already_paid';
  net_recovered: number;
}

export interface RazorpayCheckoutResult {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

export function createOrder(paymentId: string): Promise<CreateOrderResponse> {
  return apiFetch(
    '/razorpay/create-order',
    jsonPost({ payment_id: paymentId }),
    'Failed to create Razorpay order',
  );
}

export function verifyPayment(
  paymentId: string,
  result: RazorpayCheckoutResult,
): Promise<VerifyPaymentResponse> {
  return apiFetch(
    '/razorpay/verify-payment',
    jsonPost({
      payment_id: paymentId,
      razorpay_order_id: result.razorpay_order_id,
      razorpay_payment_id: result.razorpay_payment_id,
      razorpay_signature: result.razorpay_signature,
    }),
    'Payment verification failed',
  );
}

/** Public Razorpay KEY_ID (safe to ship; the SECRET must never reach the frontend). */
export const RAZORPAY_KEY_ID: string | undefined = import.meta.env
  .VITE_RAZORPAY_KEY_ID as string | undefined;

export const razorpayCheckoutEnabled = Boolean(RAZORPAY_KEY_ID);
