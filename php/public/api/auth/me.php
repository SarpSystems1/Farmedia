<?php
/**
 * GET /api/auth/me  (Authorization: Bearer <access_token>)
 * 200: {"user": {id, email}, "profile": {...} | null}
 * 401 missing, unknown, expired or revoked token.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('GET');
    return Accounts::get_current_user(Api::bearerToken());
});
