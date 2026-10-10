// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import PaymentResult from '../../pages/PaymentResult';
import { NO_REFERRER_META_ID } from '../../hooks/useNoReferrerPolicy';

function renderAt(search = '') {
  return render(
    <MemoryRouter initialEntries={[`/pay/result${search}`]}>
      <PaymentResult />
    </MemoryRouter>
  );
}

afterEach(() => {
  cleanup();
});

describe('PaymentResult query handling', () => {
  it('treats a success hint as non-authoritative and never claims payment', () => {
    renderAt('?payment=success');

    // Neutral, non-committal copy — the query is only a presentation hint.
    expect(screen.getByText('درخواست پرداخت شما دریافت شد')).toBeInTheDocument();
    const text = document.body.textContent;
    expect(text).not.toMatch(/پرداخت (با )?موفق/);
    expect(text).not.toMatch(/با موفقیت انجام شد/);
    // The server remains the authority for the final status.
    expect(text).toMatch(/سرور/);
  });

  it('shows the failed hint without implying a charge', () => {
    renderAt('?payment=failed');
    expect(screen.getByText('پرداخت ناموفق بود یا لغو شد')).toBeInTheDocument();
  });

  it('shows the pending hint', () => {
    renderAt('?payment=pending');
    expect(screen.getByText('در حال بررسی نتیجه پرداخت')).toBeInTheDocument();
  });

  it('falls back to a neutral state for an unknown or harmful hint', () => {
    renderAt('?payment=<script>alert(1)</script>');
    expect(screen.getByText('وضعیت پرداخت نامشخص است')).toBeInTheDocument();
    // The untrusted raw value is never echoed into the DOM.
    expect(document.body.textContent).not.toContain('<script>');
  });

  it('renders a neutral state when no hint is present', () => {
    renderAt();
    expect(screen.getByText('وضعیت پرداخت نامشخص است')).toBeInTheDocument();
  });
});

describe('PaymentResult safety', () => {
  it('never reads, logs or echoes a token accidentally placed in the URL', () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const secret = 'SECRET-BEARER-TOKEN';

    renderAt(`?payment=success&token=${secret}`);

    expect(document.body.textContent).not.toContain(secret);
    const allCalls = [logSpy, errSpy, warnSpy, infoSpy].flatMap((spy) =>
      spy.mock.calls.map((args) => JSON.stringify(args))
    );
    expect(allCalls.some((line) => line.includes(secret))).toBe(false);

    logSpy.mockRestore();
    errSpy.mockRestore();
    warnSpy.mockRestore();
    infoSpy.mockRestore();
  });

  it('applies a document no-referrer policy while mounted', () => {
    const { unmount } = renderAt('?payment=success');
    const meta = document.getElementById(NO_REFERRER_META_ID);
    expect(meta).not.toBeNull();
    expect(meta.getAttribute('content')).toBe('no-referrer');
    unmount();
    expect(document.getElementById(NO_REFERRER_META_ID)).toBeNull();
  });
});
