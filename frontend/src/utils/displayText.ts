const SENSITIVE_VALUE = /(authorization|registration[ _-]?token|connector[ _-]?secret|jwt[ _-]?secret|password)(\s*[:=]\s*|\s+)(?:bearer\s+)?[^\s,;]+/gi;

export function customerFacingText(value: string): string {
  return value
    .replace(/\bPEKA SaaS\b/gi, 'PEKA')
    .replace(/\bSaaS\b/gi, 'PEKA')
    .replace(SENSITIVE_VALUE, '$1: [REDACTED]');
}
