import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, within, fireEvent, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Modal from '../../components/Modal';
import FormField from '../../components/FormField';
import CatalogLayout from '../../components/CatalogLayout';
import Layout from '../../components/Layout';

const testState = vi.hoisted(() => ({
  auth: {
    logout: vi.fn(),
    isAdmin: false,
    user: { username: 'employee', role: 'employee' },
  },
  api: {
    getCatalogCategories: vi.fn(),
    getPublicBrand: vi.fn(),
  },
}));

vi.mock('../../lib/auth', () => ({
  useAuth: () => testState.auth,
}));

vi.mock('../../lib/api', () => ({
  getCatalogCategories: testState.api.getCatalogCategories,
  getPublicBrand: testState.api.getPublicBrand,
  getBlogPosts: vi.fn(),
}));

vi.mock('../../lib/seo', () => ({
  useSEO: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  testState.auth = {
    logout: vi.fn(),
    isAdmin: false,
    user: { username: 'employee', role: 'employee' },
  };
  testState.api.getCatalogCategories.mockResolvedValue({
    data: [
      {
        id: 1,
        name: 'دسته اصلی',
        children: [{ id: 2, name: 'زیر دسته' }],
      },
    ],
  });
  testState.api.getPublicBrand.mockResolvedValue({ data: { enable_blog: false } });
  document.body.style.overflow = '';
});

afterEach(() => {
  cleanup();
  document.querySelectorAll('[data-testid="modal-trigger"]').forEach((element) => element.remove());
  document.body.style.overflow = '';
});

describe('audited accessibility fixes 2026-08-23', () => {
  it('modal moves focus inside, traps tab navigation, and restores focus on close', async () => {
    const user = userEvent.setup();
    const trigger = document.createElement('button');
    trigger.textContent = 'open modal';
    trigger.dataset.testid = 'modal-trigger';
    document.body.appendChild(trigger);
    trigger.focus();

    const onClose = vi.fn();
    const { rerender } = render(
      <Modal isOpen={true} onClose={onClose} title="ویرایش محصول">
        <button type="button">ذخیره</button>
      </Modal>
    );

    const dialog = screen.getByRole('dialog', { name: 'ویرایش محصول' });
    const closeButton = screen.getByRole('button', { name: 'بستن پنجره' });
    await waitFor(() => expect(document.activeElement).toBe(closeButton));
    expect(dialog.getAttribute('aria-modal')).toBe('true');

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'ذخیره' }));

    await user.tab();
    expect(document.activeElement).toBe(closeButton);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(
      <Modal isOpen={false} onClose={onClose} title="ویرایش محصول">
        <button type="button">ذخیره</button>
      </Modal>
    );
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    trigger.remove();
  });

  it('form field exposes label, required state, invalid state, and error description', () => {
    render(
      <FormField
        label="نام محصول"
        name="product_name"
        value=""
        onChange={vi.fn()}
        onBlur={vi.fn()}
        touched={{ product_name: true }}
        errors={{ product_name: 'نام محصول الزامی است' }}
        required
      />
    );

    const input = screen.getByRole('textbox', { name: /نام محصول/ });
    expect(input.getAttribute('id')).toBe('product_name');
    expect(input.getAttribute('aria-required')).toBe('true');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('aria-describedby')).toBe('product_name-error');
    expect(screen.getByText('نام محصول الزامی است').getAttribute('id')).toBe('product_name-error');
  });

  it('catalog mobile drawer receives focus, traps focus, restores focus, and hides page content while open', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <CatalogLayout>
          <a href="/outside">محتوای صفحه</a>
        </CatalogLayout>
      </MemoryRouter>
    );

    const menuButton = screen.getByRole('button', { name: 'باز کردن منو' });
    await user.click(menuButton);

    const drawer = screen.getByRole('navigation', { name: 'پیوندهای موبایل' }).closest('aside');
    const closeButton = screen.getByRole('button', { name: 'بستن منوی موبایل' });
    await waitFor(() => expect(document.activeElement).toBe(closeButton));
    expect(menuButton.getAttribute('aria-expanded')).toBe('true');
    expect(drawer.getAttribute('aria-modal')).toBe('true');
    expect(screen.getByRole('main').hasAttribute('inert')).toBe(true);

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(within(drawer).getByRole('button', { name: 'دسته اصلی' }));

    await user.keyboard('{Escape}');
    await waitFor(() => expect(document.activeElement).toBe(menuButton));
    expect(menuButton.getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByRole('main').hasAttribute('inert')).toBe(false);
  });

  it('catalog desktop categories menu opens by keyboard and announces state', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <CatalogLayout>
          <p>catalog</p>
        </CatalogLayout>
      </MemoryRouter>
    );

    await waitFor(() => expect(testState.api.getCatalogCategories).toHaveBeenCalled());
    const categoriesButton = screen.getByRole('button', { name: /دسته.*بندی/ });
    categoriesButton.focus();
    await user.keyboard('{Enter}');

    expect(categoriesButton.getAttribute('aria-expanded')).toBe('true');
    expect(categoriesButton.getAttribute('aria-controls')).toBe('catalog-mega-menu');
    expect(screen.getByRole('menu', { name: 'دسته‌بندی محصولات' })).toBeDefined();
  });

  it('admin layout mobile sidebar receives focus, traps focus, restores focus, and hides content while open', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Layout>
          <a href="/admin-content">محتوای مدیریت</a>
        </Layout>
      </MemoryRouter>
    );

    const menuButton = screen.getByRole('button', { name: 'باز کردن منو' });
    await user.click(menuButton);

    const sidebar = screen.getByRole('dialog', { name: 'منوی مدیریت' });
    const firstLink = within(sidebar).getByRole('link', { name: /داشبورد/ });
    await waitFor(() => expect(document.activeElement).toBe(firstLink));
    expect(menuButton.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('main').hasAttribute('inert')).toBe(true);

    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    const sidebarLinks = within(sidebar).getAllByRole('link');
    expect(document.activeElement).toBe(sidebarLinks[sidebarLinks.length - 1]);

    await user.keyboard('{Escape}');
    await waitFor(() => expect(document.activeElement).toBe(menuButton));
    expect(menuButton.getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByRole('main').hasAttribute('inert')).toBe(false);
  });
});
