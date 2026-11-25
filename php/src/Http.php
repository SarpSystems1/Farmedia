<?php
/**
 * Outbound HTTPS calls with cURL. HTTPS only, certificates verified, no redirects followed.
 *
 * send() returns the raw result, so a caller can decide whether to retry (see Suppliers).
 * getJson() and postJson() throw an ApiException for any failure.
 */

declare(strict_types=1);

namespace Farmedia;

final class Http
{
    /**
     * One request. Never throws for HTTP or transport errors; the caller reads the result.
     *
     * @param list<string> $headers
     * @param array<string, scalar>|string|null $body form fields (array) or a raw body (string); null for GET
     * @return array{status: int, body: string, error: int, message: string}
     */
    public static function send(
        string $method,
        string $url,
        array $headers = [],
        array|string|null $body = null,
        int $timeout = 10
    ): array {
        if (!str_starts_with($url, 'https://')) {
            return ['status' => 0, 'body' => '', 'error' => -1, 'message' => 'Only HTTPS endpoints are allowed.'];
        }
        $ch = curl_init($url);
        if ($ch === false) {
            return ['status' => 0, 'body' => '', 'error' => -1, 'message' => 'cURL could not start.'];
        }

        $options = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
            CURLOPT_REDIR_PROTOCOLS => CURLPROTO_HTTPS,
            CURLOPT_USERAGENT => 'Farmedia/3.0',
        ];
        if ($body === null) {
            $options[CURLOPT_HTTPGET] = true;
        } else {
            $options[CURLOPT_POST] = true;
            $options[CURLOPT_POSTFIELDS] = $body;
        }
        curl_setopt_array($ch, $options);

        $raw = curl_exec($ch);
        $result = [
            'status' => (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE),
            'body' => $raw === false ? '' : (string) $raw,
            'error' => $raw === false ? curl_errno($ch) : 0,
            'message' => $raw === false ? curl_error($ch) : '',
        ];
        curl_close($ch);
        return $result;
    }

    /**
     * GET a JSON document.
     *
     * @param array<string, scalar> $query
     * @param list<string> $headers
     * @return array<mixed>
     */
    public static function getJson(string $url, array $query, int $timeout = 10, array $headers = []): array
    {
        $result = self::send('GET', $url . '?' . http_build_query($query), $headers, null, $timeout);
        return self::expectJson($result, $url);
    }

    /**
     * POST a JSON body and read a JSON reply.
     *
     * @param list<string> $headers extra headers, e.g. "x-api-key: ..."
     * @param array<mixed> $body
     * @return array<mixed>
     */
    public static function postJson(string $url, array $headers, array $body, int $timeout = 30): array
    {
        $payload = json_encode($body, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
        $result = self::send(
            'POST',
            $url,
            array_merge(['Content-Type: application/json', 'Accept: application/json'], $headers),
            $payload,
            $timeout
        );
        return self::expectJson($result, $url);
    }

    /**
     * Turns a raw result into decoded JSON, or throws the matching ApiException.
     *
     * @param array{status: int, body: string, error: int, message: string} $result
     * @return array<mixed>
     */
    public static function expectJson(array $result, string $url): array
    {
        if ($result['error'] !== 0) {
            // Logged for the operator. The message can contain the URL, and never a key (keys are headers).
            error_log('[farmedia] request error ' . $result['error'] . ': ' . $result['message']);
            if ($result['error'] === CURLE_OPERATION_TIMEDOUT) {
                throw ApiException::upstreamTimeout();
            }
            throw ApiException::upstreamFailure('The request could not be completed.');
        }
        if ($result['status'] < 200 || $result['status'] >= 300) {
            // Only the status is logged. The reply body can echo request data.
            error_log('[farmedia] upstream status ' . $result['status'] . ' from ' . (string) parse_url($url, PHP_URL_HOST));
            throw ApiException::upstreamFailure('Upstream returned status ' . $result['status'] . '.');
        }
        $data = json_decode($result['body'], true);
        if (!is_array($data)) {
            throw ApiException::upstreamFailure('Upstream returned invalid JSON.');
        }
        return $data;
    }
}
