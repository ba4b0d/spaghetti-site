import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';

// The catalog page resolves everything from the public catalogue API.
const apiMock = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  getCatalogCategories: vi.fn(),
  getCatalogCollections: vi.fn(),
}));

vi.mock('../lib/api', () => apiMock);

import Catalog from '../pages/Catalog';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

const renderCatalog = () =>
  render(
    <MemoryRouter initialEntries={['/']}>
      <LocationProbe />
      <Routes>
        <Route path="/" element={<Catalog />} />
      </Routes>
    </MemoryRouter>
  );

const PRODUCT = {
  id: 5,
  name: 'جاکلیدی تستی',
  product_id: 'SP-5',
  final_price: 30000,
  slug: 'test-keychain',
  images: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();

  // jsdom lacks matchMedia; Catalog only calls it for a populated collections
  // row, but stub it defensively so the page renders regardless of data.
  if (!window.matchMedia) {
    window.matchMedia = () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    });
  }

  // Default jsdom has no Web Share API.
  Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });

  apiMock.getCatalog.mockResolvedValue({ data: [PRODUCT] });
  apiMock.getCatalogCategories.mockResolvedValue({ data: [] });
  apiMock.getCatalogCollections.mockResolvedValue({ data: [] });
});

describe('Catalog product card — generic share', () => {
  it('renders a generic share button and no Telegram share link', async () => {
    const { container } = renderCatalog();

    const shareButton = await screen.findByRole('button', { name: 'اشتراک‌گذاری محصول' });
    expect(shareButton).toBeInTheDocument();
    expect(shareButton).toHaveAttribute('title', 'اشتراک‌گذاری محصول');

    // No Telegram share affordance remains on the card.
    expect(screen.queryByLabelText('اشتراک در تلگرام')).toBeNull();
    expect(container.querySelector('a[href*="t.me"]')).toBeNull();

    // The share control must be a sibling of the card link, never nested in it.
    expect(shareButton.closest('a')).toBeNull();
  });

  it('copies the product URL and shows a transient confirmation without the Web Share API', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });

    renderCatalog();
    const shareButton = await screen.findByRole('button', { name: 'اشتراک‌گذاری محصول' });

    vi.useFakeTimers();
    try {
      fireEvent.click(shareButton);
      await act(async () => {});

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText.mock.calls[0][0]).toContain('/catalog/test-keychain');
      expect(shareButton).toHaveAttribute('aria-label', 'کپی شد ✓');

      act(() => {
        vi.advanceTimersByTime(1800);
      });
      expect(shareButton).toHaveAttribute('aria-label', 'اشتراک‌گذاری محصول');
    } finally {
      vi.useRealTimers();
    }
  });

  it('invokes the Web Share API and never navigates the card', async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: share });

    renderCatalog();
    const shareButton = await screen.findByRole('button', { name: 'اشتراک‌گذاری محصول' });

    fireEvent.click(shareButton);
    await act(async () => {});

    expect(share).toHaveBeenCalledTimes(1);
    expect(share.mock.calls[0][0]).toMatchObject({
      title: 'جاکلیدی تستی',
      url: expect.stringContaining('/catalog/test-keychain'),
    });
    // stopPropagation + preventDefault keep the card from navigating.
    expect(screen.getByTestId('location').textContent).toBe('/');
  });
});
