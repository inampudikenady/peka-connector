import { ApiError } from '../api/client';

const messages: Record<string, string> = {
  TOKEN_NOT_FOUND: 'The registration token is invalid.',
  TOKEN_EXPIRED: 'The registration token has expired. Generate a new token in PEKA.',
  TOKEN_USED: 'The registration token has already been used. Generate a new token in PEKA.',
  TOKEN_REVOKED: 'The registration token was revoked. Generate a new token in PEKA.',
  INSTANCE_ALREADY_REGISTERED: 'This connector appliance is already registered in PEKA.',
  TENANT_MISMATCH: 'The registration token is not valid for this connector registration.',
  REGISTRATION_NOT_PERMITTED: 'Connector registration is not permitted.',
};

export interface RegistrationErrorPresentation {
  message: string;
  guidance?: string;
}

export function registrationErrorPresentation(error: unknown): RegistrationErrorPresentation {
  const apiError = error instanceof ApiError ? error : null;
  const code = apiError?.code;
  const message = code && messages[code]
    ? messages[code]
    : error instanceof Error && error.message && error.message !== 'Request failed'
      ? error.message
      : 'Connector registration failed.';
  return {
    message,
    guidance: code === 'INSTANCE_ALREADY_REGISTERED'
      ? 'This appliance may have been registered previously. Restore the original local connector state, or retire/delete the existing PEKA connector before registering again.'
      : undefined,
  };
}

export class RegistrationAttemptGuard {
  private active = false;

  async run<T>(
    operation: () => Promise<T>,
    onStart: () => void,
    onFinish: () => void,
  ): Promise<T | undefined> {
    if (this.active) return undefined;
    this.active = true;
    onStart();
    try {
      return await operation();
    } finally {
      onFinish();
      this.active = false;
    }
  }
}
