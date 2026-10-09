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

  it('reads the staff queue with credentials', async () => {
    const { mod, commerceClient } = await loadCommerceApi();
    const config = { signal: new AbortController().signal };

    mod.getStaffRequests(config);

    expect(commerceClient.get).toHaveBeenCalledWith('/staff/requests', config);
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
