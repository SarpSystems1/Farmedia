<?php
/**
 * HTTP helpers shared by every endpoint: JSON in and out, error mapping, security headers.
 */

declare(strict_types=1);

namespace Farmedia;

use JsonException;
use Throwable;

final class Api
{
    private const MAX_BODY_BYTES = 16384;

    /**
     * Runs $action and writes its array result as JSON. Returning null sends 204 No Content.
     * Any ApiException becomes its error response. Any other Throwable is logged and answered
     * with a generic 500.
     *
     * @param callable(): ?array<mixed> $action
     */
    public static function handle(callable $action, int $successStatus = 200): void
    {
        self::securityHeaders();
        try {
            $body = $action();
            if ($body === null) {
                http_response_code(204);
                return;
            }
            self::send($successStatus, $body);
        } catch (ApiException $e) {
            self::send($e->status, $e->toArray(self::lang()));
        } catch (Throwable $e) {
            // The details go to the server log only. PDO messages can contain SQL.
            error_log('[farmedia] ' . $e::class . ': ' . $e->getMessage());
            self::send(500, ApiException::internal()->toArray(self::lang()));
        }
    }

    /** Refuses any HTTP method not listed. Sends an Allow header with the accepted ones. */
    public static function requireMethod(string ...$methods): void
    {
        if (!in_array($_SERVER['REQUEST_METHOD'] ?? '', $methods, true)) {
            header('Allow: ' . implode(', ', $methods));
            throw ApiException::methodNotAllowed();
        }
    }

    /**
     * Like handle(), but the JSON is sent as a file download (Content-Disposition: attachment).
     * Used for the personal-data export, which must not be cached.
     *
     * @param callable(): array<mixed> $action
     */
    public static function handleDownload(callable $action, string $filename): void
    {
        self::securityHeaders();
        try {
            $body = $action();
        } catch (ApiException $e) {
            self::send($e->status, $e->toArray(self::lang()));
            return;
        } catch (Throwable $e) {
            error_log('[farmedia] ' . $e::class . ': ' . $e->getMessage());
            self::send(500, ApiException::internal()->toArray(self::lang()));
            return;
        }
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        http_response_code(200);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }

    /**
     * The request body as an associative array. Requires a JSON content type and a size limit,
     * which also stops plain HTML forms from posting to these endpoints.
     *
     * @return array<string, mixed>
     */
    public static function jsonBody(): array
    {
        $contentType = $_SERVER['CONTENT_TYPE'] ?? '';
        if (stripos($contentType, 'application/json') !== 0) {
            throw ApiException::invalidInput('body', 'Content-Type must be application/json.');
        }

        $raw = file_get_contents('php://input', false, null, 0, self::MAX_BODY_BYTES + 1);
        if ($raw === false) {
            throw ApiException::invalidInput('body', 'The request body could not be read.');
        }
        if (strlen($raw) > self::MAX_BODY_BYTES) {
            throw ApiException::payloadTooLarge();
        }

        try {
            $data = json_decode($raw, true, 16, JSON_THROW_ON_ERROR);
        } catch (JsonException) {
            throw ApiException::invalidInput('body', 'The request body must be valid JSON.');
        }
        if (!is_array($data)) {
            throw ApiException::invalidInput('body', 'The request body must be a JSON object.');
        }
        return $data;
    }

    /**
     * A text field from a decoded body. Required unless $default is given; must be a string no
     * longer than $maxLength characters.
     *
     * @param array<string, mixed> $in
     */
    public static function string(array $in, string $field, int $maxLength, ?string $default = null): string
    {
        if (!array_key_exists($field, $in) || $in[$field] === null) {
            if ($default !== null) {
                return $default;
            }
            throw ApiException::invalidInput($field, "$field is required.");
        }
        $value = $in[$field];
        if (!is_string($value)) {
            throw ApiException::invalidInput($field, "$field must be a string.");
        }
        if (mb_strlen($value, 'UTF-8') > $maxLength) {
            throw ApiException::invalidInput($field, "$field is too long.");
        }
        return $value;
    }

    /**
     * A required number from a body or query string, within [$min, $max]. Numeric strings are accepted,
     * because query values always are strings.
     *
     * @param array<string, mixed> $in
     */
    public static function number(array $in, string $field, float $min, float $max): float
    {
        $value = self::optionalNumber($in, $field, $min, $max);
        if ($value === null) {
            throw ApiException::invalidInput($field, "$field is required.");
        }
        return $value;
    }

    /** As number(), but a missing or empty value gives null. */
    public static function optionalNumber(array $in, string $field, float $min, float $max): ?float
    {
        if (!array_key_exists($field, $in) || $in[$field] === null || $in[$field] === '') {
            return null;
        }
        $value = $in[$field];
        if (!is_numeric($value)) {
            throw ApiException::invalidInput($field, "$field must be a number.");
        }
        $number = (float) $value;
        if ($number < $min || $number > $max) {
            throw ApiException::invalidInput($field, "$field must be between $min and $max.");
        }
        return $number;
    }

    /**
     * The access token from "Authorization: Bearer <token>". Some servers (CGI/FastCGI) move the
     * header to REDIRECT_HTTP_AUTHORIZATION, so both places are read.
     */
    public static function bearerToken(): string
    {
        $header = trim((string) ($_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? ''));
        if (!preg_match('/^Bearer\s+(\S+)$/i', $header, $m)) {
            throw ApiException::authFailed('Missing or malformed bearer token.');
        }
        return $m[1];
    }

    /** Response language from ?lang=. Turkish unless English is asked for. */
    public static function lang(): string
    {
        return (($_GET['lang'] ?? '') === 'en') ? 'en' : 'tr';
    }

    private static function send(int $status, array $body): void
    {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }

    private static function securityHeaders(): void
    {
        // Account responses contain personal data and must not be cached by a proxy or browser.
        header('Cache-Control: no-store');
        header('X-Content-Type-Options: nosniff');
        header('X-Frame-Options: DENY');
        header('Referrer-Policy: strict-origin-when-cross-origin');
        if (strtolower(trim(Env::get('APP_ENV', 'development'))) === 'production') {
            header('Strict-Transport-Security: max-age=31536000; includeSubDomains');
        }
    }
}
