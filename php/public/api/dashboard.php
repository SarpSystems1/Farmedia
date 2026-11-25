<?php
/**
 * GET or POST /api/dashboard.php  (Authorization: Bearer <access_token>)
 * Weather for the chosen point, the recommendations and warnings, and the parsed crop lists.
 * Body or query: latitude, longitude, lang (tr|en), role (hobby|farm), farm_size, crops_last,
 * crops_current, crops_next.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\Crops;
use Farmedia\Insights;
use Farmedia\Weather;

Api::handle(static function (): array {
    Api::requireMethod('GET', 'POST');
    Accounts::authenticate(Api::bearerToken());
    $in = ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST' ? Api::jsonBody() : $_GET;

    $lat = Api::number($in, 'latitude', -90, 90);
    $lon = Api::number($in, 'longitude', -180, 180);
    $lang = Api::string($in, 'lang', 8, 'tr');
    $role = Api::string($in, 'role', 16, 'hobby');
    $farmSize = Api::optionalNumber($in, 'farm_size', 0, 1000000);
    $crops = [
        'last' => Api::string($in, 'crops_last', 2000, ''),
        'current' => Api::string($in, 'crops_current', 2000, ''),
        'next' => Api::string($in, 'crops_next', 2000, ''),
    ];

    $forecast = Weather::forecast($lat, $lon);
    $isFarm = $role === 'farm';

    // Last and next season only count for a farm. The current crops always count.
    $parsed = [];
    foreach ($crops as $key => $text) {
        $parsed[$key] = Crops::parse(($isFarm || $key === 'current') ? $text : '', $lang);
    }

    $insights = Insights::build(
        $forecast,
        $lang,
        $isFarm ? 'farm' : 'hobby',
        $isFarm ? $farmSize : null,
        $parsed['last']['crops'],
        $parsed['current']['crops'],
        $parsed['next']['crops']
    );

    return [
        'forecast' => [
            'current' => $forecast['current'] ?? [],
            'current_units' => $forecast['current_units'] ?? [],
            'daily' => $forecast['daily'] ?? [],
            'timezone' => $forecast['timezone'] ?? null,
            'elevation' => $forecast['elevation'] ?? null,
        ],
        'insights' => $insights,
        'crops' => $parsed,
    ];
});
