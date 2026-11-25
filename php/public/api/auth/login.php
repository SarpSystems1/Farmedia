<?php
/**
 * POST /api/auth/login  {"email": "...", "password": "..."}
 * 200: {"session": {access_token, refresh_token, expires_in, token_type}, "user": {id, email}}
 * 401 wrong e-mail or password, 403 e-mail not confirmed, 422 bad input.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('POST');
    $in = Api::jsonBody();
    return Accounts::login(
        Api::string($in, 'email', 254),
        Api::string($in, 'password', Accounts::PASSWORD_MAX)
    );
});
