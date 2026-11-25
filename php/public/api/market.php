<?php
/**
 * GET /api/market.php?latitude=..&longitude=..&precision=city&radius_km=..  (Authorization: Bearer <access_token>)
 * Nearby seed, machinery and input suppliers, map search links, and cost benchmarks for the chosen place.
 * precision "country" returns needs_place instead of a search: a country-wide radius would show unrelated dealers.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\ApiException;
use Farmedia\CostInsights;
use Farmedia\Regions;
use Farmedia\Suppliers;

Api::handle(static function (): array {
    Api::requireMethod('GET');
    Accounts::authenticate(Api::bearerToken());
    $in = $_GET;

    $lat = Api::number($in, 'latitude', -90, 90);
    $lon = Api::number($in, 'longitude', -180, 180);
    $precision = Api::string($in, 'precision', 8, 'city');
    if (!in_array($precision, ['district', 'city', 'state', 'country'], true)) {
        throw ApiException::invalidInput('precision', 'precision must be district, city, state or country.');
    }
    $radiusKm = Api::optionalNumber($in, 'radius_km', 0.001, 300);
    $lang = Api::string($in, 'lang', 8, 'tr') === 'tr' ? 'tr' : 'en';
    $farmSize = Api::optionalNumber($in, 'farm_size', 0, 1000000000);
    $city = Api::string($in, 'city', 100, '');
    $state = Api::string($in, 'state', 100, '');
    $country = Api::string($in, 'country', 100, '');
    $countryCode = Api::string($in, 'country_code', 2, '');

    $code = Regions::resolve($countryCode, $country);
    $radius = $radiusKm ?? Suppliers::radiusForPrecision($precision);

    if ($precision === 'country') {
        $suppliers = ['status' => 'needs_place', 'items' => []];
    } else {
        try {
            $suppliers = ['status' => 'ok', 'items' => Suppliers::find($lat, $lon, (float) $radius)];
        } catch (ApiException) {
            $suppliers = ['status' => 'unavailable', 'items' => []];
        }
    }

    $countryName = Regions::countryName($code, $lang);
    $place = [$city, $state, $countryName !== '' ? $countryName : $country];

    return [
        'suppliers' => $suppliers,
        'radius_km' => $radius,
        'country_code' => $code,
        // Cooperative network: shown for Turkey only.
        'coop_url' => $code === 'TR' ? 'https://www.tarimkredi.org.tr' : null,
        'search_links' => Suppliers::searchLinks($lang, $place),
        'costs' => CostInsights::build($lang, $farmSize, $code),
    ];
});
