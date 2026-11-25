<?php
/**
 * GET /api/health.php  -> {"status": "online"}. No sign-in and no database: used by the container health check.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('GET');
    return ['status' => 'online'];
});
