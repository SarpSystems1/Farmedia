<?php
/**
 * POST /api/auth/register
 *
 * Document root must be php/public, so this file is reached as /api/auth/register.php.
 * Keep php/src and the .env file outside the document root.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('POST');
    return Accounts::register(Api::jsonBody());
}, 201);
