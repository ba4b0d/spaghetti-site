// @vitest-environment jsdom
//
// Behaviour of the token-free same-origin intermediate page (/pay/redirect).
//
// The private /pay/<token> page cannot navigate to BitPay directly (its
// document is `Referrer-Policy: no-referrer`, which makes BitPay answer
// «آدرس ارجاعی نامعتبر»). It parks the validated portal URL in sessionStorage
// and hard-navigates here; this page re-validates the parked URL, clears it,
// and navigates on with an origin-only Referer. It must never echo the URL or
// any token into the DOM, and it must refuse anything that is not an exactly
// allow-listed gateway URL (no open redirect).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import PaymentHandoff from '../../pages/PaymentHandoff';
import {
  GATEWAY_HANDOFF_KEY,
  GATEWAY_HANDOFF_MAX_AGE_MS,
  writeGatewayHandoff,
} from '../../lib/paymentHandoff';
import { ORIGIN_REFERRER_META_ID } from '../../hooks/useOriginReferrerPolicy';

const TOKEN = 'raw-BEARER-token-999';
const BITPAY_OK_URL = 'https://bitpay.ir/payment/gateway-987654-get';

function renderAt(navigate = vi.fn()) {
  const utils = render(
    <MemoryRouter initialEntries={['/pay/redirect']}>
      <Routes>
        <Route path="/pay/redirect" element={<PaymentHandoff navigate={navigate} />} />
      </Routes>
    </MemoryRouter>
  );
  return { ...utils, navigate };
}

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
});

describe('PaymentHandoff (/pay/redirect)', () => {
  it('navigates to the validated gateway URL and clears the parked hand-off', async () => {
    writeGatewayHandoff(BITPAY_OK_URL, 'bitpay');

    const { navigate } = renderAt();

    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(navigate).toHaveBeenCalledWith(BITPAY_OK_URL);
    // Consumed: a refresh must not re-navigate.
    expect(window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY)).toBeNull();
  });

  it('does nothing and shows a safe state when no hand-off is parked', async () => {
    const { navigate } = renderAt();

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('refuses a tampered URL (open-redirect attempt) instead of navigating', async () => {
    writeGatewayHandoff('https://evil.example.com/pay', 'bitpay');

    const { navigate } = renderAt();

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY)).toBeNull();
  });

  it('refuses a provider/URL mismatch (a BitPay URL under the digipay provider)', async () => {
    writeGatewayHandoff(BITPAY_OK_URL, 'digipay');

    const { navigate } = renderAt();

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('refuses an expired hand-off', async () => {
    window.sessionStorage.setItem(
      GATEWAY_HANDOFF_KEY,
      JSON.stringify({
        url: BITPAY_OK_URL,
        provider: 'bitpay',
        ts: Date.now() - GATEWAY_HANDOFF_MAX_AGE_MS - 1,
      })
    );

    const { navigate } = renderAt();

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('never renders the gateway URL or a bearer token into the DOM', async () => {
    writeGatewayHandoff(BITPAY_OK_URL, 'bitpay');

    renderAt();

    await waitFor(() => expect(document.body.textContent).toBeTruthy());
    expect(document.body.textContent).not.toContain(BITPAY_OK_URL);
    expect(document.body.textContent).not.toContain('gateway-987654-get');
    expect(document.body.textContent).not.toContain(TOKEN);
  });

  it('applies an origin-only document referrer policy while mounted', async () => {
    writeGatewayHandoff(BITPAY_OK_URL, 'bitpay');

    const { unmount } = renderAt();

    const meta = document.getElementById(ORIGIN_REFERRER_META_ID);
    expect(meta).not.toBeNull();
    expect(meta.getAttribute('name')).toBe('referrer');
    expect(meta.getAttribute('content')).toBe('origin');

    unmount();
    expect(document.getElementById(ORIGIN_REFERRER_META_ID)).toBeNull();
  });
});
