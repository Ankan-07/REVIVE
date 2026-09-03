import React, { useState } from 'react';
import { CreditCard, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import {
  createOrder,
  verifyPayment,
  RazorpayCheckoutResult,
  VerifyPaymentResponse,
  RAZORPAY_KEY_ID,
} from '../api/checkout';

interface RazorpayOptions {
  key: string;
  amount: number; // paise
  currency: string;
  name: string;
  description: string;
  order_id: string;
  prefill?: { email?: string; contact?: string };
  theme?: { color: string };
  handler: (response: RazorpayCheckoutResult) => void;
  modal?: { ondismiss?: () => void };
}

interface WindowWithRazorpay extends Window {
  Razorpay?: new (options: RazorpayOptions) => {
    open: () => void;
    on: (event: string, handler: (response: any) => void) => void;
  };
}

let checkoutScriptPromise: Promise<boolean> | null = null;

/** Lazily inject Razorpay's checkout.js once; resolves true when ready. */
function loadCheckoutScript(): Promise<boolean> {
  if (typeof window === 'undefined') return Promise.resolve(false);
  if ((window as WindowWithRazorpay).Razorpay) return Promise.resolve(true);
  if (!checkoutScriptPromise) {
    checkoutScriptPromise = new Promise((resolve) => {
      const script = document.createElement('script');
      script.src = 'https://checkout.razorpay.com/v1/checkout.js';
      script.async = true;
      script.onload = () => resolve(true);
      script.onerror = () => {
        checkoutScriptPromise = null;
        resolve(false);
      };
      document.body.appendChild(script);
    });
  }
  return checkoutScriptPromise;
}

interface Props {
  paymentId: string;
  amountInr: number;
  onVerified: (result: VerifyPaymentResponse) => void;
  onError?: (message: string) => void;
}

export function RazorpayCheckout({ paymentId, amountInr, onVerified, onError }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  if (!RAZORPAY_KEY_ID) {
    return null;
  }

  const handleError = (message: string) => {
    setError(message);
    onError?.(message);
  };

  const handleClick = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      // 1. Create a REAL Razorpay order for this failed payment.
      const order = await createOrder(paymentId);

      // 2. Load checkout.js and open the payment modal.
      const loaded = await loadCheckoutScript();
      if (!loaded) {
        handleError('Could not load the Razorpay checkout. Check your connection and try again.');
        return;
      }

      const Razorpay = (window as WindowWithRazorpay).Razorpay!;
      const rzp = new Razorpay({
        key: RAZORPAY_KEY_ID!,
        amount: order.amount_paise,
        currency: order.currency,
        name: 'Revenue Rescue Engine',
        description: `Recover payment ${paymentId}`,
        order_id: order.order_id,
        theme: { color: '#4f46e5' },
        handler: async (response) => {
          try {
            // 3. Send (order_id, payment_id, signature) back for server-side verification.
            const verified = await verifyPayment(paymentId, response);
            if (verified.status === 'already_paid') {
              setSuccess('This payment was already verified and settled.');
            } else {
              setSuccess(
                `Payment verified — ₹${verified.net_recovered.toLocaleString()} net recovered.`,
              );
            }
            onVerified(verified);
          } catch (err) {
            handleError(err instanceof Error ? err.message : 'Payment verification failed.');
          }
        },
        modal: { ondismiss: () => setBusy(false) },
      });

      // Spec: surface payment.failed events from the modal itself.
      rzp.on('payment.failed', (response: any) => {
        const description = response?.error?.description || response?.error?.reason || 'Unknown error';
        handleError(`Payment failed: ${description}`);
      });

      rzp.open();
      // The modal handles its own lifecycle; keep busy until dismiss/handler resolves.
      setBusy(true);
    } catch (err) {
      handleError(err instanceof Error ? err.message : 'Could not start Razorpay checkout.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <button
        onClick={handleClick}
        disabled={busy}
        className="flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white text-sm font-semibold rounded-lg transition shadow-lg shadow-indigo-900/20"
      >
        {busy ? (
          <><Loader2 className="w-4 h-4 animate-spin" /> Starting checkout…</>
        ) : (
          <><CreditCard className="w-4 h-4" /> Pay ₹{amountInr.toLocaleString()} now (test card)</>
        )}
      </button>

      {error && (
        <div className="flex items-start gap-2 bg-rose-500/10 border border-rose-500/20 text-rose-400 p-3 rounded-lg text-xs">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 p-3 rounded-lg text-xs">
          <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{success}</span>
        </div>
      )}
    </div>
  );
}
