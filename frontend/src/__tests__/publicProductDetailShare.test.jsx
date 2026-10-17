import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// The product detail page resolves the product from the public catalogue API.
const apiMock = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  getCatalogProductBySlug: vi.fn(),
  getCatalogProduct: vi.fn(),
}));

vi.mock('../lib/api', () => apiMock);

import PublicProductDetail from '../pages/PublicProductDetail';

const PRODUCT = {
  id: 5,
  name: 'جاکلیدی تستی',
  product_id: 'SP-5',
  final_price: 30000,
  slug: 'test-keychain',
  images: [],
  category: '',
};

const renderDetail = () =>
  render(
    <MemoryRouter initialEntries={['/catalog/test-keychain']}>
      <Routes>
        <Route path="/catalog/:slug" element={<PublicProductDetail />} />
      </Routes>
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();

  // Default jsdom has neither the Web Share API nor a clipboard.
  Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });

  apiMock.getCatalogProductBySlug.mockResolvedValue({ data: PRODUCT });
  apiMock.getCatalogProduct.mockResolvedValue({ data: PRODUCT });
  apiMock.getCatalog.mockResolvedValue({ data: [PRODUCT] });
});

describe('PublicProductDetail — generic share', () => {
  it('renders one generic icon-only share control and no Telegram share affordance', async () => {
    const { container } = renderDetail();

    const shareButton = await screen.findByRole('button', { name: /گذاری محصول/ });
    expect(shareButton).toBeInTheDocument();
    // It is a real button, never an anchor — a share must not navigate away.
    expect(shareButton.tagName).toBe('BUTTON');
    expect(container.querySelector('a[href*="t.me"]')).toBeNull();
    expect(screen.queryByText('اشتراک در تلگرام')).toBeNull();

    // Exactly one generic share control on the page.
    expect(screen.getAllByRole('button', { name: /گذاری محصول/ })).toHaveLength(1);
  });

  it('preserves the Add to cart and Contact CTAs', async () => {
    renderDetail();

    expect(await screen.findByRole('button', { name: /افزودن به سبد خرید/ })).toBeInTheDocument();

    const contact = screen.getByRole('link', { name: /تماس برای سفارش/ });
    expect(contact).toHaveAttribute('href', '/contact');
  });

  it('falls back to clipboard copy with an accessible status when the Web Share API is unavailable', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    renderDetail();
    const shareButton = await screen.findByRole('button', { name: /گذاری محصول/ });

    vi.useFakeTimers();
    try {
      fireEvent.click(shareButton);
      await act(async () => {});

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText.mock.calls[0][0]).toContain('/catalog/test-keychain');

      // Accessible confirmation: label flips and a polite status region announces.
      expect(shareButton).toHaveAttribute('aria-label', 'کپی شد ✓');
      expect(screen.getByRole('status')).toHaveTextContent('لینک محصول کپی شد');

      act(() => {
        vi.advanceTimersByTime(1800);
      });
      expect(shareButton.getAttribute('aria-label')).toMatch(/گذاری محصول/);
    } finally {
      vi.useRealTimers();
    }
  });

  it('invokes the Web Share API when available and never navigates', async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: share });

    renderDetail();
    const shareButton = await screen.findByRole('button', { name: /گذاری محصول/ });

    fireEvent.click(shareButton);
    await act(async () => {});

    expect(share).toHaveBeenCalledTimes(1);
    expect(share.mock.calls[0][0]).toMatchObject({
      title: 'جاکلیدی تستی',
      url: expect.stringContaining('/catalog/test-keychain'),
    });
  });
});
