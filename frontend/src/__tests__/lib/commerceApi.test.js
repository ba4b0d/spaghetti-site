import { describe, it, expect, vi, beforeEach } from 'vitest';

const axiosState = vi.hoisted(() => ({ clients: [] }));

vi.mock('axios', () => ({
  default: {
    create: vi.fn((config) => {
      const client = {
        config,
        get: vi.fn(),
        post: vi.fn(),
        put: vi.fn(),
        delete: vi.fn(),
        interceptors: { response: { use: vi.fn() } },
      };
      axiosState.clients.push(client);
      return client;
    }),
  },
}));

async function loadCommerceApi() {
  vi.resetModules();
  axiosState.clients.length = 0;
  const mod = await import('../../lib/commerceApi');
  return { mod, commerceClient: axiosState.clients[0] };
}

describe('commerceApi public contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses a dedicated client scoped to /api/v1/commerce', async () => {
    const { commerceClient } = await loadCommerceApi();
    expect(commerceClient.config.baseURL).toBe('/api/v1/commerce');
  });

  it('submits a public request with the payload and abort config', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const payload = { customer_name: 'رضا', mobile: '09123456789', items: [{ product_id: 1, qty: 2 }] };
    const config = { signal: new AbortController().signal };

    mod.submitCommerceRequest(payload, config);

    expect(commerceClient.post).toHaveBeenCalledWith('/requests', payload, config);
  });

  it('reads the staff queue with pagination params and credentials', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const config = { signal: new AbortController().signal };

    mod.getStaffRequests({ limit: 50, offset: 0 }, config);

    expect(commerceClient.get).toHaveBeenCalledWith('/staff/requests', {
      params: { limit: 50, offset: 0 },
      ...config,
    });
  });

  it('lists staff invoices with pagination params', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const config = { signal: new AbortController().signal };

    mod.getStaffInvoices({ limit: 100, offset: 100 }, config);

    expect(commerceClient.get).toHaveBeenCalledWith('/staff/invoices', {
      params: { limit: 100, offset: 100 },
      ...config,
    });
  });

  it('creates a staff draft invoice', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const payload = {
      customer_name: 'رضا',
      mobile: '09123456789',
      items: [{ description: 'قطعه', qty: 1, unit_toman: 1000 }],
    };

    mod.createStaffInvoice(payload);

    expect(commerceClient.post).toHaveBeenCalledWith('/staff/invoices', payload);
  });

  it('revises a staff invoice by id', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const payload = { customer_name: 'رضا', mobile: '09123456789', items: [] };

    mod.updateStaffInvoice(7, payload);

    expect(commerceClient.put).toHaveBeenCalledWith('/staff/invoices/7', payload);
  });

  it('approves a staff invoice by id', async () => {
    const { mod, commerceClient } = await loadCommerceApi();

    mod.approveStaffInvoice(7);

    expect(commerceClient.post).toHaveBeenCalledWith('/staff/invoices/7/approve');
  });

  it('revokes a staff invoice by id', async () => {
    const { mod, commerceClient } = await loadCommerceApi();

    mod.revokeStaffInvoice(7);

    expect(commerceClient.post).toHaveBeenCalledWith('/staff/invoices/7/revoke');
  });

  it('reads a public invoice by its private token', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const config = { signal: new AbortController().signal };

    mod.getPublicInvoice('tok_ABC-123', config);

    expect(commerceClient.get).toHaveBeenCalledWith('/invoices/tok_ABC-123', config);
  });

  it('url-encodes the token path so it never lands in a query string', async () => {
    const { mod, commerceClient } = await loadCommerceApi();

    mod.getPublicInvoice('a/b?c=1');

    const [url, config] = commerceClient.get.mock.calls[0];
    expect(url).toBe('/invoices/a%2Fb%3Fc%3D1');
    expect(url).not.toContain('?');
    expect(config).toBeUndefined();
  });

  it('starts a BitPay payment via the explicit token-scoped pay endpoint', async () => {
    const { mod, commerceClient } = await loadCommerceApi();

    mod.payInvoice('tok_XYZ', 'bitpay');

    expect(commerceClient.post).toHaveBeenCalledWith('/invoices/tok_XYZ/pay/bitpay');
  });

  it('still maps the parked DigiPay method to its own endpoint when named', async () => {
    const { mod, commerceClient } = await loadCommerceApi();

    mod.payInvoice('tok_XYZ', 'digipay');

    expect(commerceClient.post).toHaveBeenCalledWith('/invoices/tok_XYZ/pay');
  });

  it('rejects an unknown or missing method instead of defaulting', async () => {
    const { mod, commerceClient } = await loadCommerceApi();

    await expect(mod.payInvoice('tok_XYZ')).rejects.toThrow(/unsupported payment method/);
    await expect(mod.payInvoice('tok_XYZ', 'paypal')).rejects.toThrow(/unsupported payment method/);
    expect(commerceClient.post).not.toHaveBeenCalled();
  });

  it('rejects inherited Object.prototype names instead of coercing them to a path', async () => {
    // `PAY_INVOICE_PATHS[method]` on a plain object resolves inherited names
    // (toString/constructor/__proto__/valueOf/…) to a truthy function/object,
    // which the old `if (!path)` guard accepted — a prototype-lookup exploit
    // that issued a bogus POST. Only own, string keys may ever match.
    const { mod, commerceClient } = await loadCommerceApi();

    for (const name of [
      'toString',
      'constructor',
      'valueOf',
      '__proto__',
      'hasOwnProperty',
      'isPrototypeOf',
      'propertyIsEnumerable',
    ]) {
      await expect(mod.payInvoice('tok_XYZ', name)).rejects.toThrow(
        /unsupported payment method/
      );
    }
    // Non-string keys must not be coerced into a lookup either.
    await expect(mod.payInvoice('tok_XYZ', {})).rejects.toThrow(/unsupported payment method/);
    await expect(mod.payInvoice('tok_XYZ', ['bitpay'])).rejects.toThrow(
      /unsupported payment method/
    );
    expect(commerceClient.post).not.toHaveBeenCalled();
  });

  it('reads the public payment-method readiness endpoint', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const config = { signal: new AbortController().signal };

    mod.getPaymentMethods(config);

    expect(commerceClient.get).toHaveBeenCalledWith('/payment-methods', config);
  });

  it('does not force a login redirect on a public 401', async () => {
    const { commerceClient } = await loadCommerceApi();
    const errorHandler = commerceClient.interceptors.response.use.mock.calls[0][1];
    expect(typeof errorHandler).toBe('function');

    const before = window.location.href;
    await expect(errorHandler({ response: { status: 401 } })).rejects.toBeDefined();
    expect(window.location.href).toBe(before);
  });
});
