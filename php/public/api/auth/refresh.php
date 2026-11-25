<?php
/**
 * POST /api/auth/refresh  {"refresh_token": "..."}
 * 200: a new session. The refresh token that was sent stops working.
 * 401 unknown, expired or revoked refresh token.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('POST');
    $in = Api::jsonBody();
    return Accounts::refresh_session(Api::string($in, 'refresh_token', 512));
});
