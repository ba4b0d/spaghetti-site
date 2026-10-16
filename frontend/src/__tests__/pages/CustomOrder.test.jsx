import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CustomOrder from '../../pages/CustomOrder';
import * as api from '../../lib/api';

vi.mock('../../lib/api', () => ({
  getContact: vi.fn(),
}));

vi.mock('../../lib/seo', () => ({
  useSEO: vi.fn(),
  buildWebSiteJsonLd: vi.fn(() => ({})),
}));

describe('CustomOrder Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getContact.mockResolvedValue({
      data: {
        contact_telegram: '@my_spaghetti_tg',
        contact_bale: '@my_spaghetti_bale',
        contact_phone: '09981923856',
      },
    });
  });

  it('renders order steps and does not render the removed fast order form', async () => {
    render(
      <MemoryRouter>
        <CustomOrder />
      </MemoryRouter>
    );

    expect(screen.getByText('نحوه سفارش')).toBeDefined();
    expect(screen.getByText('پیدا کردن عکس طرح مورد نظر')).toBeDefined();
    expect(screen.getByText('تحویل')).toBeDefined();

    // Fast order section must NOT be present
    expect(screen.queryByText('درخواست سریع سفارش')).toBeNull();
    expect(screen.queryByText('ثبت درخواست استعلام قیمت')).toBeNull();
    expect(screen.queryByPlaceholderText('نام و نام خانوادگی')).toBeNull();
    expect(screen.queryByPlaceholderText('شماره موبایل یا آیدی تلگرام')).toBeNull();
  });

  it('renders the 3 CTAs: Telegram, Bale, and Phone beside each other', async () => {
    render(
      <MemoryRouter>
        <CustomOrder />
      </MemoryRouter>
    );

    const telegramBtn = screen.getByRole('link', { name: /ارسال پیام در تلگرام/ });
    const baleBtn = screen.getByRole('link', { name: /ارسال پیام در بله/ });
    const phoneBtn = screen.getByRole('link', { name: /تماس تلفنی/ });

    expect(telegramBtn).toBeDefined();
    expect(baleBtn).toBeDefined();
    expect(phoneBtn).toBeDefined();

    await waitFor(() => {
      expect(telegramBtn.getAttribute('href')).toBe('https://t.me/my_spaghetti_tg');
      expect(baleBtn.getAttribute('href')).toBe('https://ble.ir/my_spaghetti_bale');
      expect(phoneBtn.getAttribute('href')).toBe('tel:+989981923856');
    });

    expect(telegramBtn.getAttribute('target')).toBe('_blank');
    expect(baleBtn.getAttribute('target')).toBe('_blank');
  });

  it('includes a link to the contact page', () => {
    render(
      <MemoryRouter>
        <CustomOrder />
      </MemoryRouter>
    );

    const contactLink = screen.getByRole('link', { name: /مشاهده سایر اطلاعات در صفحه تماس با ما/ });
    expect(contactLink.getAttribute('href')).toBe('/contact');
  });
});
