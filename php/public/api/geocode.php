<?php
/**
 * GET /api/geocode.php?country=TR&state=&city=Bursa&district=&lang=tr  (Authorization: Bearer <access_token>)
 * 200: {latitude, longitude, display_name, country_code, precision}. 404 when nothing matches.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\Geocoding;

Api::handle(static function (): array {
    Api::requireMethod('GET');
    Accounts::authenticate(Api::bearerToken());

    return Geocoding::locate(
        Api::string($_GET, 'country', 100),
        Api::string($_GET, 'state', 100, ''),
        Api::string($_GET, 'city', 100, ''),
        Api::string($_GET, 'district', 100, ''),
        Api::string($_GET, 'lang', 10, 'tr')
    );
});
