<?php
/**
 * Application error with an HTTP status, a stable error code and a translation key.
 * Port of services/errors.py. The JSON shape matches the Python API:
 *   {"error": {"code", "status", "message", "detail"}}
 */

declare(strict_types=1);

namespace Farmedia;

use RuntimeException;

final class ApiException extends RuntimeException
{
    /** @param array<string, string> $params */
    public function __construct(
        public readonly int $status,
        public readonly string $errorCode,
        public readonly string $messageKey,
        public readonly string $detail,
        public readonly array $params = [],
    ) {
        parent::__construct($detail);
    }

    public static function invalidInput(string $field, string $detail): self
    {
        return new self(422, 'invalid_input', 'error.invalid_input', $detail, ['field' => $field]);
    }

    public static function consentRequired(string $detail, string $messageKey = 'error.consent_required'): self
    {
        return new self(422, 'consent_required', $messageKey, $detail);
    }

    public static function ruleViolation(string $detail): self
    {
        return new self(422, 'rule_violation', 'error.rule_violation', $detail);
    }

    public static function notConfigured(string $detail): self
    {
        return new self(503, 'not_configured', 'error.not_configured', $detail);
    }

    public static function unavailable(): self
    {
        return new self(503, 'service_unavailable', 'error.unavailable', 'The database is not reachable.');
    }

    public static function authFailed(string $detail = 'Invalid email or password.'): self
    {
        return new self(401, 'auth_failed', 'error.auth_failed', $detail);
    }

    public static function emailNotConfirmed(): self
    {
        return new self(403, 'email_not_confirmed', 'error.email_not_confirmed', 'Confirm your email address before signing in.');
    }

    public static function upstreamFailure(string $detail): self
    {
        return new self(502, 'upstream_failure', 'error.upstream_failure', $detail);
    }

    public static function upstreamTimeout(): self
    {
        return new self(504, 'upstream_timeout', 'error.upstream_timeout', 'The upstream service did not respond in time.');
    }

    public static function locationNotFound(string $query): self
    {
        return new self(404, 'location_not_found', 'error.location_not_found', 'Location not found: ' . $query, ['query' => $query]);
    }

    public static function methodNotAllowed(): self
    {
        return new self(405, 'method_not_allowed', 'error.method_not_allowed', 'HTTP method not allowed.');
    }

    public static function payloadTooLarge(): self
    {
        return new self(413, 'payload_too_large', 'error.payload_too_large', 'Request body is too large.');
    }

    public static function internal(): self
    {
        return new self(500, 'internal_error', 'error.internal', 'Unexpected internal error.');
    }

    /** @return array{error: array{code: string, status: int, message: string, detail: string}} */
    public function toArray(string $lang): array
    {
        return [
            'error' => [
                'code'    => $this->errorCode,
                'status'  => $this->status,
                'message' => Messages::translate($lang, $this->messageKey, $this->params),
                'detail'  => $this->detail,
            ],
        ];
    }
}
