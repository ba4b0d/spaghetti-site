import { describe, it, expect, vi, beforeEach } from 'vitest';

// The history client must be a DEDICATED Axios instance: no default
// Authorization header, no cookies, bearer attached per request. We mock axios
// and import the real module so its `axios.create` config is asserted as-is.
const axiosState = vi.hoisted(() => ({ clients: [] }));

vi.mock('axios', () => ({
  default: {
    create: vi.fn((config) => {
      const client = {
        config,
        get: vi.fn(() => Promise.resolve({ data: {} })),
        post: vi.fn(() => Promise.resolve({ data: {} })),
        interceptors: { response: { use: vi.fn() } },
      };
      axiosState.clients.push(client);
      return client;
    }),
  },
}));

async function load() {
  vi.resetModules();
  axiosState.clients.length = 0;
  const mod = await import('../../lib/commerceHistoryApi');
  return { mod, client: axiosState.clients[0] };
}

describe('commerceHistoryApi — explicit bearer, no cookie, no default Authorization', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates a dedicated client with no default Authorization header and no cookies', async () => {
    const { client } = await load();

    expect(client.config.baseURL).toBe('/api/v1/commerce');
    expect(client.config.withCredentials).toBe(false);
    const headerNames = Object.keys(client.config.headers || {}).map((h) => h.toLowerCase());
    expect(headerNames).not.toContain('authorization');
  });

  it('sends OTP calls with no Authorization header at all', async () => {
    const { mod, client } = await load();

    mod.requestHistoryOtp({ mobile: '09123456789' });
    mod.verifyHistoryOtp({ mobile: '09123456789', challenge_id: 7, code: '12345' });

    const [issueUrl, issueBody, issueConfig] = client.post.mock.calls[0];
    expect(issueUrl).toBe('/history/otp');
    expect(issueBody).toEqual({ mobile: '09123456789' });
    expect(issueConfig).toBeUndefined();

    const [verifyUrl, verifyBody] = client.post.mock.calls[1];
    expect(verifyUrl).toBe('/history/verify');
    expect(verifyBody).toEqual({
      mobile: '09123456789',
      challenge_id: 7,
      code: '12345',
    });
  });

  it('attaches the bearer header per request, with params, on the history read', async () => {
    const { mod, client } = await load();
    const { signal } = new AbortController();

    mod.getCustomerHistory('tok-1', { limit: 10, offset: 20 }, { signal });

    expect(client.get).toHaveBeenCalledTimes(1);
    expect(client.get).toHaveBeenCalledWith('/history', {
      signal,
      params: { limit: 10, offset: 20 },
      headers: { Authorization: 'Bearer tok-1' },
    });
  });

  it('defaults limit/offset when omitted', async () => {
    const { mod, client } = await load();

    mod.getCustomerHistory('tok-2');

    expect(client.get).toHaveBeenCalledWith('/history', {
      params: { limit: 20, offset: 0 },
      headers: { Authorization: 'Bearer tok-2' },
    });
  });

  it('attaches the bearer header on sign-out', async () => {
    const { mod, client } = await load();

    mod.signOutHistory('tok-3');

    expect(client.post).toHaveBeenCalledWith('/history/sign-out', null, {
      headers: { Authorization: 'Bearer tok-3' },
    });
  });

  it('refuses to send an anonymous history read or sign-out', async () => {
    const { mod, client } = await load();

    await expect(mod.getCustomerHistory('')).rejects.toThrow();
    await expect(mod.signOutHistory(null)).rejects.toThrow();
    await expect(mod.getCustomerHistory(undefined)).rejects.toThrow();

    expect(client.get).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });
});
