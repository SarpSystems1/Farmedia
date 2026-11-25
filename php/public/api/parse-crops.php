<?php
/**
 * POST /api/parse-crops.php  {"text": "domates, biber ve 2 dekar buğday", "lang": "tr"}
 * (Authorization: Bearer <access_token>)
 * 200: {"crops": [{id, name, family, frost_c, heat_c, water}], "unknown": ["..."]}
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\Crops;

Api::handle(static function (): array {
    Api::requireMethod('POST');
    Accounts::authenticate(Api::bearerToken());
    $in = Api::jsonBody();

    return Crops::parse(
        Api::string($in, 'text', 5000, ''),
        Api::string($in, 'lang', 8, 'tr')
    );
});
