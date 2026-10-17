import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import HowToOrder from '../../pages/HowToOrder';
import * as api from '../../lib/api';

vi.mock('../../lib/api', () => ({
  getContact: vi.fn(),
}));

vi.mock('../../lib/seo', () => ({
  useSEO: vi.fn(),
  buildWebSiteJsonLd: vi.fn(() => ({})),
}));

describe('HowToOrder Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getContact.mockResolvedValue({
      data: {
        contact_telegram: '@spaghetti_test_tg',
        contact_bale: '@spaghetti_test_bale',
        contact_phone: '09981923856',
      },
    });
  });

  it('renders switcher tabs and defaults to site order mode', async () => {
    render(
      <MemoryRouter>
        <HowToOrder />
      </MemoryRouter>
    );

    // Verify switcher tabs exist
    expect(screen.getByRole('tab', { name: /سفارش مستقیم از سایت/ })).toBeDefined();
    expect(screen.getByRole('tab', { name: /سفارش در پیام‌رسان‌ها/ })).toBeDefined();

    // Verify site steps are visible by default
    expect(screen.getByText('انتخاب محصول و افزودن به سبد')).toBeDefined();
    expect(screen.getByText(/تأیید سریع با پیامک/)).toBeDefined();
    expect(screen.getByText('پرداخت امن آنلاین')).toBeDefined();

    // Site CTAs
    expect(screen.getByRole('link', { name: /مشاهده کاتالوگ/ })).toBeDefined();
  });

  it('switches to messenger tab and displays original messenger steps and telegram/bale CTAs', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <HowToOrder />
      </MemoryRouter>
    );

    const messengerTab = screen.getByRole('tab', { name: /سفارش در پیام‌رسان‌ها/ });
    await user.click(messengerTab);

    // Verify original messenger steps and descriptions are present
    expect(screen.getByText('کد محصول')).toBeDefined();
    expect(screen.getByText('کد محصول را یادداشت نمایید.')).toBeDefined();
    expect(screen.getByText('ارسال پیام')).toBeDefined();
    expect(screen.getByText(/برای انتخاب رنگ و سفارش هر محصول، کد آن را از طریق تلگرام، اینستاگرام و یا بله/)).toBeDefined();
    expect(screen.getByText('انتخاب رنگ')).toBeDefined();

    // Verify Telegram and Bale CTAs are rendered with proper hrefs
    const telegramBtn = screen.getByRole('link', { name: /ارسال پیام در تلگرام/ });
    const baleBtn = screen.getByRole('link', { name: /ارسال پیام در بله/ });

    expect(telegramBtn).toBeDefined();
    expect(baleBtn).toBeDefined();

    await waitFor(() => {
      expect(telegramBtn.getAttribute('href')).toBe('https://t.me/spaghetti_test_tg');
      expect(baleBtn.getAttribute('href')).toBe('https://ble.ir/spaghetti_test_bale');
    });
  });

  it('does not render two-column mode and only provides site and messenger tabs', () => {
    render(
      <MemoryRouter>
        <HowToOrder />
      </MemoryRouter>
    );

    expect(screen.queryByRole('tab', { name: /نمایش دو ستونه/ })).toBeNull();
    expect(screen.queryByText('روش اول: سفارش آنلاین از سایت')).toBeNull();
    expect(screen.queryByText('روش دوم: سفارش در پیام‌رسان‌ها')).toBeNull();
  });
});
