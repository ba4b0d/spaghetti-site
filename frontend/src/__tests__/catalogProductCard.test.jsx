import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// The catalog page resolves everything from the public catalogue API.
const apiMock = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  getCatalogCategories: vi.fn(),
  getCatalogCollections: vi.fn(),
}));

vi.mock('../lib/api', () => apiMock);

import Catalog from '../pages/Catalog';

const renderCatalog = () =>
  render(
    <MemoryRouter initialEntries={['/']}>
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

  apiMock.getCatalog.mockResolvedValue({ data: [PRODUCT] });
  apiMock.getCatalogCategories.mockResolvedValue({ data: [] });
  apiMock.getCatalogCollections.mockResolvedValue({ data: [] });
});

describe('Catalog product card — no share control', () => {
  it('renders product cards without any share affordance or Telegram link', async () => {
    const { container } = renderCatalog();

    // A card renders for the product.
    expect(
      await screen.findByRole('link', { name: /مشاهده جاکلیدی تستی/ })
    ).toBeInTheDocument();

    // The generic share control lives on the product detail page, NOT on cards.
    expect(screen.queryByRole('button', { name: /گذاری محصول/ })).toBeNull();
    expect(container.querySelector('a[href*="t.me"]')).toBeNull();
  });

  it('does not reserve code-badge padding for the removed share button', async () => {
    const { container } = renderCatalog();

    await screen.findByRole('link', { name: /مشاهده جاکلیدی تستی/ });

    // Regression: the badge row used to carry pl-12 to keep clear of a share
    // icon pinned to the image corner; with the icon gone the padding must go.
    expect(container.querySelector('.pl-12')).toBeNull();
  });
});
