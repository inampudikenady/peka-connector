import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import { RegistrationAttemptGuard, registrationErrorPresentation } from './registration';

describe('registrationErrorPresentation', () => {
  it.each([
    ['TOKEN_NOT_FOUND', 'The registration token is invalid.'],
    ['TOKEN_EXPIRED', 'The registration token has expired. Generate a new token in PEKA.'],
    ['TOKEN_USED', 'The registration token has already been used. Generate a new token in PEKA.'],
    ['TOKEN_REVOKED', 'The registration token was revoked. Generate a new token in PEKA.'],
    ['INSTANCE_ALREADY_REGISTERED', 'This connector appliance is already registered in PEKA.'],
    ['TENANT_MISMATCH', 'The registration token is not valid for this connector registration.'],
    ['REGISTRATION_NOT_PERMITTED', 'Connector registration is not permitted.'],
  ])('maps %s to its user-facing message', (code, expected) => {
    expect(registrationErrorPresentation(new ApiError('remote message', 400, code)).message).toBe(expected);
  });

  it('uses the sanitized API message for validation and unknown codes', () => {
    expect(registrationErrorPresentation(new ApiError('The connector name is invalid.', 400, 'VALIDATION_FAILED')).message).toBe('The connector name is invalid.');
    expect(registrationErrorPresentation(new ApiError('A future safe explanation.', 400, 'FUTURE_CODE')).message).toBe('A future safe explanation.');
  });

  it('shows recovery guidance for an already-registered instance', () => {
    const result = registrationErrorPresentation(new ApiError('remote', 409, 'INSTANCE_ALREADY_REGISTERED'));
    expect(result.guidance).toContain('Restore the original local connector state');
    expect(result.guidance).toContain('retire/delete the existing PEKA connector');
  });

  it('uses a generic fallback for malformed errors', () => {
    expect(registrationErrorPresentation(new ApiError('Request failed', 502)).message).toBe('Connector registration failed.');
  });
});

describe('RegistrationAttemptGuard', () => {
  it('allows only one POST-equivalent operation while pending', async () => {
    let release: (() => void) | undefined;
    const operation = vi.fn(() => new Promise<string>((resolve) => { release = () => resolve('registered'); }));
    const guard = new RegistrationAttemptGuard();
    const first = guard.run(operation, vi.fn(), vi.fn());
    const second = guard.run(operation, vi.fn(), vi.fn());
    expect(operation).toHaveBeenCalledTimes(1);
    expect(await second).toBeUndefined();
    release?.();
    expect(await first).toBe('registered');
  });

  it('clears token memory and releases the guard after failure', async () => {
    let token = 'one-time-token';
    let oldError = 'old error';
    const guard = new RegistrationAttemptGuard();
    await expect(guard.run(
      async () => { throw new Error('registration failed'); },
      () => { oldError = ''; },
      () => { token = ''; },
    )).rejects.toThrow('registration failed');
    expect(token).toBe('');
    expect(oldError).toBe('');
    await guard.run(async () => 'retry', vi.fn(), vi.fn());
  });
});
