import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  clearHistorySession,
  HISTORY_SESSION_KEY,
  readHistorySession,
  writeHistorySession,
} from '../../lib/commerceHistorySession';

// Real jsdom sessionStorage descriptor, restored after each test.
const realSessionDescriptor = Object.getOwnPropertyDescriptor(window, 'sessionStorage');

const setSessionStorage = (value) =>
  Object.defineProperty(window, 'sessionStorage', {
    configurable: true,
    writable: true,
    value,
  });

const rawEntry = () => window.sessionStorage.getItem(HISTORY_SESSION_KEY);

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  if (realSessionDescriptor) {
    Object.defineProperty(window, 'sessionStorage', realSessionDescriptor);
  }
});

describe('commerceHistorySession — tab-scoped, expiring, exception-safe', () => {
  it('round-trips a session through sessionStorage only', () => {
    const expiresAt = Date.now() + 60_000;

    expect(writeHistorySession('tok-1', expiresAt)).toBe(true);
    expect(readHistorySession()).toEqual({ token: 'tok-1', expiresAt });

    // The stored shape is a JSON object under the one known key.
    expect(JSON.parse(rawEntry())).toEqual({ token: 'tok-1', expiresAt });
  });

  it('never touches localStorage', () => {
    const localSpy = {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      key: vi.fn(() => null),
      get length() {
        return 0;
      },
    };
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      writable: true,
      value: localSpy,
    });

    writeHistorySession('tok', Date.now() + 60_000);
    readHistorySession();
    clearHistorySession();

    expect(localSpy.getItem).not.toHaveBeenCalled();
    expect(localSpy.setItem).not.toHaveBeenCalled();
    expect(localSpy.removeItem).not.toHaveBeenCalled();
  });

  it('returns null and clears an expired session', () => {
    writeHistorySession('tok-expired', Date.now() - 1_000);

    expect(readHistorySession()).toBeNull();
    // The stale bearer is removed, not left to be reused.
    expect(rawEntry()).toBeNull();
  });

  it('treats an expiry exactly at now as expired', () => {
    const now = Date.now();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    writeHistorySession('tok-now', now);

    expect(readHistorySession()).toBeNull();
  });

  it('accepts an ISO-8601 expiry string and stores epoch millis', () => {
    const iso = new Date(Date.now() + 120_000).toISOString();

    expect(writeHistorySession('tok-iso', iso)).toBe(true);
    const session = readHistorySession();
    expect(session.token).toBe('tok-iso');
    expect(session.expiresAt).toBe(Date.parse(iso));
  });

  it('returns null and removes a malformed entry', () => {
    window.sessionStorage.setItem(HISTORY_SESSION_KEY, 'not-json{');

    expect(readHistorySession()).toBeNull();
    expect(rawEntry()).toBeNull();
  });

  it('returns null for an entry missing token or expiry', () => {
    window.sessionStorage.setItem(HISTORY_SESSION_KEY, JSON.stringify({ token: 'only' }));
    expect(readHistorySession()).toBeNull();

    window.sessionStorage.setItem(
      HISTORY_SESSION_KEY,
      JSON.stringify({ expiresAt: Date.now() + 60_000 })
    );
    expect(readHistorySession()).toBeNull();
  });

  it('returns null when no session is stored', () => {
    expect(readHistorySession()).toBeNull();
  });

  it('rejects an invalid write without storing anything', () => {
    expect(writeHistorySession('', Date.now() + 60_000)).toBe(false);
    expect(writeHistorySession('tok', 'not-a-date')).toBe(false);
    expect(writeHistorySession(null, Date.now() + 60_000)).toBe(false);
    expect(rawEntry()).toBeNull();
  });

  it('degrades to null/false (never throws) when storage methods throw', () => {
    const blocked = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    };
    setSessionStorage(blocked);

    expect(readHistorySession()).toBeNull();
    expect(writeHistorySession('tok', Date.now() + 60_000)).toBe(false);
    expect(() => clearHistorySession()).not.toThrow();
  });

  it('degrades safely when accessing the storage property itself throws', () => {
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get() {
        throw new Error('access denied');
      },
    });

    expect(readHistorySession()).toBeNull();
    expect(writeHistorySession('tok', Date.now() + 60_000)).toBe(false);
    expect(() => clearHistorySession()).not.toThrow();
  });

  it('clearHistorySession removes the key', () => {
    writeHistorySession('tok', Date.now() + 60_000);
    expect(rawEntry()).not.toBeNull();

    clearHistorySession();
    expect(rawEntry()).toBeNull();
    expect(readHistorySession()).toBeNull();
  });
});
