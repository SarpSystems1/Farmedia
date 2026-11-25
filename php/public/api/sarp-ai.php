<?php
/**
 * POST /api/sarp-ai.php  (Authorization: Bearer <access_token>)
 *   {"question": "...", "city": "...", "country_code": "TR", "lang": "tr|en", "farm_context": {...}}
 * 200: {"question": "...", "city": "..." | null, "sarp_ai_answer": "..."}
 *
 * The farm_context is sent only when the user agreed to share it (KVKK transfer consent); the
 * web UI does that check before it sends the field.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\ApiException;
use Farmedia\Regions;
use Farmedia\SarpAi;

Api::handle(static function (): array {
    Api::requireMethod('POST');
    Accounts::authenticate(Api::bearerToken());
    $in = Api::jsonBody();

    $question = trim(Api::string($in, 'question', 2000));
    if ($question === '') {
        throw ApiException::invalidInput('question', 'Question cannot be empty.');
    }
    $city = trim(Api::string($in, 'city', 100, ''));
    $lang = Api::string($in, 'lang', 2, 'tr');
    $country = is_string($in['country_code'] ?? null) ? Regions::normalize($in['country_code']) : null;
    $farm = $in['farm_context'] ?? null;

    return SarpAi::advise([
        'question' => $question,
        'city' => $city,
        'lang' => $lang === 'en' ? 'en' : 'tr',
        'country_code' => $country,
        'farm_context' => is_array($farm) ? $farm : null,
    ]);
});
