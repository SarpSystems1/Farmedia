<?php
/**
 * GET /api/profile/export.php  (Authorization: Bearer <access_token>)
 * Downloads the signed-in user's data as farmedia-export.json.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handleDownload(static function (): array {
    Api::requireMethod('GET');
    return Accounts::exportUserData(Api::bearerToken());
}, 'farmedia-export.json');
