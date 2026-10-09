import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';

// The drawer resolves display names (never authoritative prices) from the
// public catalogue; the layout also loads categories/brand on mount.
const apiMock = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  getCatalogProduct: vi.fn(),
  getCatalogCategories: vi.fn(),
  getPublicBrand: vi.fn(),
  recordSiteView: vi.fn(),
}));

vi.mock('../lib/api', () => apiMock);

import * as cart from '../lib/cart';
import CartDrawer from '../components/CartDrawer';
import CatalogLayout from '../components/CatalogLayout';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

// A real trigger button outside the dialog so focus-restore can be verified.
function DrawerHarness({ onClose }) {
  const [open, setOpen] = React.useState(false);
  return (
    <MemoryRouter initialEntries={['/catalog']}>
      <LocationProbe />
      <button type="button" onClick={() => setOpen(true)}>
        بازکردن سبد
      </button>
      <CartDrawer
        open={open}
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
      />
      <Routes>
        <Route path="/catalog" element={<div>صفحه کاتالوگ</div>} />
        <Route path="/checkout" element={<div>صفحه ثبت درخواست</div>} />
      </Routes>
    </MemoryRouter>
  );
}

const openDrawer = async (user) => {
  await user.click(screen.getByRole('button', { name: 'بازکردن سبد' }));
  await screen.findByRole('dialog', { name: 'سبد خرید' });
};

const currentPath = () => screen.getByTestId('location').textContent;

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  apiMock.getCatalog.mockResolvedValue({
    data: [{ id: 12, name: 'جاکلیدی تستی', final_price: 30000, slug: 'test-keychain' }],
  });
  apiMock.getCatalogCategories.mockResolvedValue({ data: [] });
  apiMock.getPublicBrand.mockResolvedValue({ data: {} });
  apiMock.recordSiteView.mockResolvedValue({ data: {} });
});

// ── focus management (MEDIUM finding) ───────────────────────────────

describe('CartDrawer focus management', () => {
  it('moves focus into the dialog when it opens', async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    const closeButton = screen.getByRole('button', { name: 'بستن سبد خرید' });
    await waitFor(() => expect(closeButton).toHaveFocus());
  });

  it('traps Tab inside the dialog and never reaches background controls', async () => {
    cart.addItem(12, 1);
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    const trigger = screen.getByRole('button', { name: 'بازکردن سبد' });
    const closeButton = screen.getByRole('button', { name: 'بستن سبد خرید' });
    const checkoutLink = screen.getByRole('link', { name: /ادامه و ثبت درخواست/ });
    await waitFor(() => expect(closeButton).toHaveFocus());

    // Tab from the last focusable wraps back to the first — no escape.
    checkoutLink.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
    expect(trigger).not.toHaveFocus();

    // Shift+Tab from the first focusable wraps to the last — no escape.
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    expect(checkoutLink).toHaveFocus();
    expect(trigger).not.toHaveFocus();
  });

  it('pulls focus back into the dialog when it has escaped to the page', async () => {
    cart.addItem(12, 1);
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    const trigger = screen.getByRole('button', { name: 'بازکردن سبد' });
    const closeButton = screen.getByRole('button', { name: 'بستن سبد خرید' });

    // Simulate focus landing on background content, then Tab.
    trigger.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
  });

  it('restores focus to the trigger after closing with Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DrawerHarness onClose={onClose} />);
    await openDrawer(user);

    const trigger = screen.getByRole('button', { name: 'بازکردن سبد' });
    const closeButton = screen.getByRole('button', { name: 'بستن سبد خرید' });
    // Focus must actually be inside the dialog before we close it, otherwise
    // the restore assertion below would pass vacuously.
    await waitFor(() => expect(closeButton).toHaveFocus());

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(trigger).toHaveFocus());
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'سبد خرید' })).not.toBeInTheDocument()
    );
  });

  it('restores focus to the trigger after closing with the close button', async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    const trigger = screen.getByRole('button', { name: 'بازکردن سبد' });
    await user.click(screen.getByRole('button', { name: 'بستن سبد خرید' }));

    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

// ── disabled checkout CTA (LOW finding) ─────────────────────────────

describe('CartDrawer checkout CTA', () => {
  it('marks the empty-cart CTA as disabled and blocks activation (pointer + keyboard)', async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    const cta = screen.getByRole('link', { name: /ادامه و ثبت درخواست/ });
    expect(cta).toHaveAttribute('aria-disabled', 'true');

    // Pointer/programmatic activation must not navigate.
    fireEvent.click(cta);
    expect(currentPath()).toBe('/catalog');

    // Keyboard activation (Enter fires a click on anchors) must not navigate.
    cta.focus();
    await user.keyboard('{Enter}');
    expect(currentPath()).toBe('/catalog');
  });

  it('is excluded from the focus trap when disabled', async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    const closeButton = screen.getByRole('button', { name: 'بستن سبد خرید' });
    const cta = screen.getByRole('link', { name: /ادامه و ثبت درخواست/ });

    // The only focusable control in an empty drawer is the close button; Tab
    // must never land on the disabled CTA.
    await waitFor(() => expect(closeButton).toHaveFocus());
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
    expect(cta).not.toHaveFocus();
  });

  it('navigates to checkout and closes the drawer when the cart is not empty', async () => {
    cart.addItem(12, 2);
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DrawerHarness onClose={onClose} />);
    await openDrawer(user);

    const cta = screen.getByRole('link', { name: /ادامه و ثبت درخواست/ });
    expect(cta).toHaveAttribute('aria-disabled', 'false');

    await user.click(cta);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(currentPath()).toBe('/checkout');
  });
});

// ── cart behaviour preserved ────────────────────────────────────────

describe('CartDrawer cart behaviour', () => {
  it('renders persisted lines and resolves display names', async () => {
    cart.addItem(12, 2);
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    expect(await screen.findByText('جاکلیدی تستی')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('increments and decrements quantities and removes at zero', async () => {
    cart.addItem(12, 1);
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    await screen.findByText('جاکلیدی تستی');

    await user.click(screen.getByRole('button', { name: /افزایش تعداد جاکلیدی تستی/ }));
    expect(cart.readCart()).toEqual([{ id: 12, qty: 2 }]);

    await user.click(screen.getByRole('button', { name: /کاهش تعداد جاکلیدی تستی/ }));
    expect(cart.readCart()).toEqual([{ id: 12, qty: 1 }]);

    await user.click(screen.getByRole('button', { name: /کاهش تعداد جاکلیدی تستی/ }));
    expect(cart.readCart()).toEqual([]);
    expect(await screen.findByText(/سبد خرید خالی است/)).toBeInTheDocument();
  });

  it('removes a line via the trash button', async () => {
    cart.addItem(12, 3);
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await openDrawer(user);

    await screen.findByText('جاکلیدی تستی');
    await user.click(screen.getByRole('button', { name: /حذف جاکلیدی تستی از سبد خرید/ }));

    expect(cart.readCart()).toEqual([]);
  });
});

// ── background is inert while the cart modal is open ────────────────

describe('CatalogLayout background inert', () => {
  it('marks the page content inert while the cart drawer is open and clears it on close', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter initialEntries={['/catalog']}>
        <Routes>
          <Route
            path="/catalog"
            element={
              <CatalogLayout>
                <div>محتوا</div>
              </CatalogLayout>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    const main = container.querySelector('main');
    const footer = container.querySelector('footer');
    expect(main).not.toHaveAttribute('inert');

    await user.click(screen.getByRole('button', { name: /سبد خرید/ }));
    await screen.findByRole('dialog', { name: 'سبد خرید' });

    await waitFor(() => expect(main).toHaveAttribute('inert'));
    expect(footer).toHaveAttribute('inert');

    await act(async () => {
      fireEvent.keyDown(window, { key: 'Escape' });
    });

    await waitFor(() => expect(main).not.toHaveAttribute('inert'));
    expect(footer).not.toHaveAttribute('inert');
  });
});
