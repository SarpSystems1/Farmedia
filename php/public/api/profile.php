<?php
/**
 * GET   /api/profile.php  -> {"profile": {...} | null}
 * PATCH /api/profile.php  (also POST) partial update, e.g. {"first_name": "...", "alert_sms_consent": true}
 *                         -> {"profile": {...updated row...}}
 * Every query uses the user id of the bearer token, never an id from the request.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('GET', 'POST', 'PATCH');
    $token = Api::bearerToken();
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
        return ['profile' => Accounts::getProfile($token)];
    }
    return ['profile' => Accounts::updateProfile($token, Api::jsonBody())];
});
