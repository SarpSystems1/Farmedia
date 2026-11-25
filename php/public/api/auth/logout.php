<?php
/**
 * POST or GET /api/auth/logout  (Authorization: Bearer <access_token>)
 * 204 on success. Ends this device's session only. Repeating the call is harmless.
 *
 * GET is accepted because the brief asks for it. A GET that changes state can be triggered from
 * another site (a forced sign-out), so the app should prefer POST.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\ApiException;

Api::handle(static function (): ?array {
    $method = $_SERVER['REQUEST_METHOD'] ?? '';
    if ($method !== 'POST' && $method !== 'GET') {
        header('Allow: GET, POST');
        throw ApiException::methodNotAllowed();
    }
    Accounts::logout(Api::bearerToken());
    return null;   // 204 No Content
});
