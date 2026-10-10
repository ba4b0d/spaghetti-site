import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import path from 'node:path';

// The checkout page resolves display names from the public catalogue and talks
// to commerceApi for the request — both are mocked exactly as in
// commerceCart.test.jsx so the page renders its real (non-empty cart) view.
const commerceApiMock = vi.hoisted(() => ({ submitCommerceRequest: vi.fn() }));
const catalogApiMock = vi.hoisted(() => ({ getCatalog: vi.fn() }));

vi.mock('../lib/commerceApi', () => commerceApiMock);
vi.mock('../lib/api', () => ({
  getCatalog: catalogApiMock.getCatalog,
  getCatalogProduct: vi.fn(),
}));

import * as cart from '../lib/cart';
import CheckoutRequest from '../pages/CheckoutRequest';

// The approved brand surface lives in index.css; load it so the assertions can
// tie the rendered inline tokens back to a real declaration.
const indexCss = readFileSync(path.resolve(process.cwd(), 'src/index.css'), 'utf8');

/** Value of a CSS custom property declared in a stylesheet string. */
function tokenValue(css, token) {
  const match = css.match(new RegExp(`${token}\\s*:\\s*([^;]+);`));
  return match ? match[1].trim() : null;
}

/** True when a #rrggbb value is a near-white (every channel >= 0xe0). */
function isNearWhite(value) {
  const match = /^#([0-9a-f]{6})$/i.exec(String(value).trim());
  if (!match) return false;
  const n = parseInt(match[1], 16);
  return [n >> 16, n >> 8, n].every((channel) => (channel & 0xff) >= 0xe0);
}

function renderCheckout() {
  return render(
    <MemoryRouter>
      <CheckoutRequest />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  cart.clearCart();
  catalogApiMock.getCatalog.mockResolvedValue({
    data: [{ id: 12, name: 'جاکلیدی تستی', final_price: 30000, slug: 'test-keychain' }],
  });
});

describe('CheckoutRequest brand header band', () => {
  it('renders a page-header band wrapping the back link, title and description', async () => {
    cart.addItem(12, 1);
    renderCheckout();

    // Non-empty cart view: the header band is present.
    const band = await screen.findByTestId('checkout-header-band');
    expect(band).toBeInTheDocument();

    expect(band).toContainElement(screen.getByRole('link', { name: /بازگشت به کاتالوگ/ }));
    expect(band).toContainElement(
      screen.getByRole('heading', { name: 'ثبت درخواست سفارش' })
    );
    expect(band).toContainElement(screen.getByText(/عدد کالا در سبد شما/));
  });

  it('renders the title and the back link in the approved brand white, never dark text', async () => {
    cart.addItem(12, 1);
    renderCheckout();

    const title = await screen.findByRole('heading', { name: 'ثبت درخواست سفارش' });
    const backLink = screen.getByRole('link', { name: /بازگشت به کاتالوگ/ });

    // jsdom preserves the custom-property reference, so "computed" colour is the
    // brand token itself — the same declaration index.css resolves to white.
    expect(window.getComputedStyle(title).color).toBe('var(--brand-header-fg)');
    expect(window.getComputedStyle(backLink).color).toBe('var(--brand-header-fg)');

    // Regression: these used to inherit the dark page text colour.
    expect(window.getComputedStyle(title).color).not.toBe('var(--text-primary)');
    expect(window.getComputedStyle(backLink).color).not.toBe('var(--text-primary)');
  });

  it('uses the approved brand header surface tokens on the band', async () => {
    cart.addItem(12, 1);
    renderCheckout();

    const band = await screen.findByTestId('checkout-header-band');
    const inlineStyle = band.getAttribute('style') || '';

    expect(inlineStyle).toContain('var(--brand-header-gradient)');
    expect(inlineStyle).toContain('var(--brand-header-border)');
    expect(inlineStyle).toContain('var(--brand-header-shadow)');
    expect(inlineStyle).toContain('var(--brand-header-fg)');
    expect(inlineStyle).not.toContain('var(--text-primary)');
    expect(window.getComputedStyle(band).background).toBe('var(--brand-header-gradient)');
  });

  it('renders the description paragraph as a translucent white', async () => {
    cart.addItem(12, 1);
    renderCheckout();

    const description = await screen.findByText(/عدد کالا در سبد شما/);
    const declared = description.getAttribute('style') || '';

    const translucentWhite =
      (declared.includes('color-mix') && declared.includes('transparent')) ||
      /rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.\d+\s*\)/.test(declared);

    expect(translucentWhite).toBe(true);
    expect(declared).not.toContain('var(--text-secondary)');
  });

  it('index.css defines the brand surface as an approved white on a navy→orange gradient', () => {
    const fg = tokenValue(indexCss, '--brand-header-fg');
    // The approved brand white is #fff8f0 — assert it really is (near-)white.
    expect(fg).toBeTruthy();
    expect(isNearWhite(fg)).toBe(true);

    const gradient = tokenValue(indexCss, '--brand-header-gradient');
    expect(gradient).toContain('linear-gradient');
    expect(gradient).toContain('#2a3350'); // navy start of the band
    expect(gradient).toContain('--brand-orange'); // warm orange end of the band;
  });

  it('leaves the receipt / empty-cart CTA white via .btn-primary (unchanged)', () => {
    // Those back links are btn-primary, which index.css already pins to white —
    // so no change is needed there, but the white foreground must hold.
    expect(indexCss).toMatch(/\.btn-primary\s*\{[^}]*color:\s*#ffffff\s*;/i);
  });
});
