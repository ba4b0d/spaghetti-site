// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Orders from '../../pages/Orders';
import { getOrders, getOrderStatuses, getProductsAll, restoreOrder } from '../../lib/api';

vi.mock('../../lib/api', () => ({
  getOrders: vi.fn(),
  createOrder: vi.fn(),
  updateOrder: vi.fn(),
  deleteOrder: vi.fn(),
  restoreOrder: vi.fn(),
  getOrderStatuses: vi.fn(),
  exportOrdersCsv: vi.fn(),
  getProductsAll: vi.fn(),
}));

const statuses = [
  { value: 'new', label: 'جدید' },
  { value: 'quoted', label: 'قیمتدادهشده' },
  { value: 'printing', label: 'در حال چاپ' },
  { value: 'ready', label: 'آماده تحویل' },
  { value: 'delivered', label: 'تحویلشده' },
  { value: 'cancelled', label: 'لغو' },
];

const activeOrder = {
  id: 1,
  customer_name: 'Active Customer',
  contact: '0912',
  status: 'new',
  total_quoted: 100,
  paid_amount: 0,
  remaining: 100,
  is_active: true,
  items: [{ product_label: 'Active item' }],
};

const archivedOrder = {
  id: 2,
  customer_name: 'Archived Customer',
  contact: '0935',
  status: 'new',
  total_quoted: 200,
  paid_amount: 0,
  remaining: 200,
  is_active: false,
  items: [{ product_label: 'Archived item' }],
};

function ok(data) {
  return Promise.resolve({ data });
}

describe('Orders archive recovery', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    getOrderStatuses.mockResolvedValue({ data: statuses });
    getProductsAll.mockResolvedValue({ data: [] });
    restoreOrder.mockResolvedValue({ data: { ...archivedOrder, is_active: true } });
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('alert', vi.fn());
  });

  it('test_loads_archived_orders_when_archive_filter_is_enabled', async () => {
    getOrders.mockImplementation((params = {}) => {
      if (params.include_inactive) return ok([activeOrder, archivedOrder]);
      return ok([activeOrder]);
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Orders />
      </MemoryRouter>
    );

    await screen.findByText('Active Customer');
    expect(screen.queryByText('Archived Customer')).toBeNull();
    expect(getOrders).toHaveBeenLastCalledWith({}, expect.any(Object));

    await user.click(screen.getByRole('button', { name: /نمایش بایگانی/i }));

    await screen.findByText('Archived Customer');
    expect(getOrders).toHaveBeenLastCalledWith({ include_inactive: true }, expect.any(Object));
  });

  it('test_restores_an_archived_order_and_reloads_active_orders', async () => {
    getOrders.mockImplementation((params = {}) => {
      if (params.include_inactive) return ok([activeOrder, archivedOrder]);
      return ok([activeOrder]);
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Orders />
      </MemoryRouter>
    );

    await screen.findByText('Active Customer');
    await user.click(screen.getByRole('button', { name: /نمایش بایگانی/i }));
    await screen.findByText('Archived Customer');

    await user.click(screen.getByRole('button', { name: /بازیابی سفارش Archived Customer/i }));

    await waitFor(() => expect(restoreOrder).toHaveBeenCalledWith(2));
    await waitFor(() => expect(getOrders).toHaveBeenLastCalledWith({ include_inactive: true }, expect.any(Object)));
  });
});
